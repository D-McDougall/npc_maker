#!/usr/bin/env python3

"""
Replay previously saved individuals through the NPC Maker's Evolution service.

This presents a saved population through the Evolution API. Each Spawn request
selects one saved individual according to the configured score function and
parent selection algorithm, and returns that individual as a single parent to
be cloned and used without genetic modification.

This program does not modify the population. Dead individuals are discarded.


# Custom Scoring

The --score option controls how saved individuals are ranked by the selection
algorithm. It accepts any of the following:

* The name of a numeric field of the individual's Metadata or telemetry.
  Metadata fields take precedence over telemetry keys of the same name.

* A Python lambda expression, which is called with the individual's Metadata
  message as its only argument and must return a number. For example:

    --score 'lambda m: m.telemetry["kills"] / m.telemetry["deaths"]'

Individuals which cannot be scored (missing fields, invalid values, or an error
in the lambda expression) are logged as warnings and given a score of -inf, so
they are selected only if nothing better is available.
"""

# Standard Library
from array import array
from concurrent import futures
from pathlib import Path
import argparse
import ast
import logging
import threading
import sys

# Third Party
import grpc

# First Party
from google.protobuf.descriptor import FieldDescriptor

from npc_maker import evolution_pb2, evolution_pb2_grpc
from npc_maker import individual_pb2
from npc_maker.individual import Individual
import mate_selection


def _is_lambda(src):
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError:
        return False
    return isinstance(tree.body, ast.Lambda)


def _compile_lambda(src):
    tree = ast.parse(src, mode="eval")
    if not isinstance(tree.body, ast.Lambda):
        raise ValueError("score expression must be a lambda")
    return eval(compile(tree, "<score>", "eval"), {"__builtins__": __builtins__})


def _validate_selection(src):
    try:
        mate_selection.parse(src)
    except Exception as error:
        raise argparse.ArgumentTypeError(str(error)) from error
    return src


def _validate_score(src):
    """
    Check that custom score is valid.
    """
    # Check for well-known metadata fields.
    descriptor = individual_pb2.Metadata.DESCRIPTOR.fields_by_name
    if src in descriptor:
        field = descriptor[src]
        numeric_types = {
            FieldDescriptor.TYPE_FLOAT, FieldDescriptor.TYPE_DOUBLE,
            FieldDescriptor.TYPE_INT32, FieldDescriptor.TYPE_INT64,
            FieldDescriptor.TYPE_UINT32, FieldDescriptor.TYPE_UINT64,
            FieldDescriptor.TYPE_SINT32, FieldDescriptor.TYPE_SINT64,
            FieldDescriptor.TYPE_FIXED32, FieldDescriptor.TYPE_FIXED64,
            FieldDescriptor.TYPE_SFIXED32, FieldDescriptor.TYPE_SFIXED64,
        }
        if field.is_repeated:
            raise argparse.ArgumentTypeError(f"score field {src!r} is repeated")
        if field.type not in numeric_types:
            raise argparse.ArgumentTypeError(f"score field {src!r} is not numeric")
        return src
    # Check for lambda-expression syntax errors
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError as error:
        if src.lstrip().startswith("lambda"):
            raise argparse.ArgumentTypeError(
                f"invalid score lambda-expression: {error.msg}"
            ) from error
    return src


def _score_function(metadata, score):
    if callable(score):
        return float(score(metadata))
    descriptor = metadata.DESCRIPTOR.fields_by_name
    if score in descriptor:
        if descriptor[score].has_presence and not metadata.HasField(score):
            raise ValueError(f"metadata field {score!r} is not present")
        return float(getattr(metadata, score))
    if score in metadata.telemetry:
        return float(metadata.telemetry[score])
    raise ValueError(f"unrecognized score field {score!r}")


class Player(evolution_pb2_grpc.EvolutionServicer):
    """
    Evolution service which replays a population of saved Individuals.
    """

    def __init__(self, path, selection, score):
        self._path = Path(path)
        self._lock = threading.RLock()

        self._select = mate_selection.parse(selection)
        self._score = _compile_lambda(score) if _is_lambda(score) else score

        # Paths to saved individuals.  These run parallel to _scores.
        self._members = []
        self._scores = array("d")

        # Individuals selected by the selection algorithm but not yet spawned.
        self._buffer = []

        # Used to detect changes to the replay population.
        self._scan_time = None

    def Spawn(self, request, context):
        """
        Select and return one saved Individual.
        """
        # Critical section: lock access to _members, _scores, and _buffer.
        with self._lock:

            self._fill_buffer(context)

            path = self._buffer.pop() # Samples in buffer are already shuffled.

        # Load individual's data files
        try:
            individual = Individual.load(path)
        except FileNotFoundError:
            context.abort(
                grpc.StatusCode.UNAVAILABLE,
                "population temporarily unavailable",
            )

        return evolution_pb2.SpawnResponse(parents=[individual.to_proto()])

    def Death(self, request, context):
        """
        Discard the individual. The replayer does not modify the population.
        """
        return evolution_pb2.DeathResponse()

    def _fill_buffer(self, context):
        """
        Ensure the internal _buffer has at least one element.
        """
        self._scan()

        if not self._members:
            context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "replay population is empty",
            )

        if not self._buffer:
            indices = self._select.select(len(self._members), self._scores)
            self._buffer.extend(self._members[index] for index in indices)

    def _scan(self):
        """
        Update the population if the replay directory has changed.
        """
        scan_time = self._path.stat().st_mtime_ns

        if scan_time == self._scan_time:
            return

        metadata = Individual.load_dir(self._path)

        self._members = [self._path / message.name for message in metadata]

        self._scores = array("d")
        for message in metadata:
            try:
                score = _score_function(message, self._score)
            except Exception as error:
                logging.warning(
                    "cannot score individual %r with %r: %s; using -inf",
                    message.name,
                    self._score,
                    error,
                )
                score = float("-inf")
            self._scores.append(score)

        # A changed population invalidates selections made from the old one.
        self._buffer = []
        self._scan_time = scan_time


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "directory",
        type=Path,
        help="directory containing saved Individual directories",
    )

    parser.add_argument(
        "selection",
        type=_validate_selection,
        help=(
            "mate selection specification, such as 'random', "
            "'proportional', or 'best=10'"
        ),
    )

    parser.add_argument(
        "--score",
        type=_validate_score,
        default="score",
        help=(
            "field used to score individuals (default: score); "
            "numeric metadata fields, telemetry keys, or lambda expression"
        ),
    )

    parser.add_argument(
        "--listen",
        help="gRPC listen address as host:port (mutually exclusive with --host/--port)",
    )

    parser.add_argument(
        "--host",
        help="gRPC listen host (default: [::1])",
    )

    parser.add_argument(
        "--port",
        type=int,
        help="gRPC listen port",
    )

    args = parser.parse_args()

    # Validate arguments
    if args.listen is not None and (args.host is not None or args.port is not None):
        parser.error("--listen is mutually exclusive with --host and --port")

    # Clean the listen argument
    if args.listen is None:
        if args.port is None:
            parser.error("a port must be specified with --port or --listen")
        host = "[::1]" if args.host is None else args.host
        args.listen = f"{host}:{args.port}"
    elif ":" not in args.listen:
        parser.error("--listen must specify a port")

    return args


def serve(directory, selection, score, listen):
    player = Player(directory, selection, score)

    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10)
    )

    evolution_pb2_grpc.add_EvolutionServicer_to_server(
        player,
        server,
    )

    server.add_insecure_port(listen)

    server.start()

    logging.info("npc-player is: %s %s", sys.executable, sys.argv[0])
    logging.info("Listening on: %s", listen)
    logging.info("Replay population: %s", directory)
    logging.info("Mate selection: %s", selection)
    logging.info("Score: %s", score)

    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        logging.info("KeyboardInterrupt, stopping npc-player service")
        server.stop(1).wait()


def main():
    logging.basicConfig(level=logging.INFO)

    args = parse_args()

    if not args.directory.is_dir():
        raise SystemExit(
            f"replay directory does not exist or is not a directory: "
            f"{args.directory}"
        )

    serve(
        args.directory,
        args.selection,
        args.score,
        args.listen,
    )


if __name__ == "__main__":
    main()
