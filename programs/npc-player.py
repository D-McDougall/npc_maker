""" 
Replay previously saved individuals through the NPC Maker's Evolution service.

This presents a saved population through the Evolution API. Each Spawn request
selects one saved individual according to the configured score function and
parent selection algorithm, and returns that individual as a single parent to
be cloned and used without genetic modification.

This program does not modify the population. Dead individuals are discarded.
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
    return eval(compile(tree, "<score>", "eval"), {"__builtins__": {}})


def _validate_selection(src):
    try:
        mate_selection.parse(src)
    except Exception as error:
        raise argparse.ArgumentTypeError(str(error)) from error
    return src


def _validate_score(src):
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
        if field.label == FieldDescriptor.LABEL_REPEATED:
            raise argparse.ArgumentTypeError(f"score field {src!r} is repeated")
        if field.type not in numeric_types:
            raise argparse.ArgumentTypeError(f"score field {src!r} is not numeric")
        return src
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError as error:
        if src.lstrip().startswith("lambda"):
            raise argparse.ArgumentTypeError(
                f"invalid score lambda: {error.msg}"
            ) from error
    return src


def _score(metadata, score):
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
        with self._lock:

            self._fill_buffer(context)

            path = self._buffer.pop()

            try:
                individual = Individual.load(path)
            except FileNotFoundError:
                # The population may have changed after _scan().  Discard any
                # stale selections and rebuild the population before retrying.

                self._scan_time = None  # Force a rescan & dump the buffer

                self._fill_buffer(context)

                path = self._buffer.pop()

                individual = Individual.load(path)

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
        # Include descendants so in-place updates to an Individual's files
        # invalidate the scan.  Keep the population directory itself in the
        # calculation so additions and removals are also detected.
        scan_time = max(
            path.stat().st_mtime_ns
            for path in [self._path, *self._path.rglob("*")]
        )

        if scan_time == self._scan_time:
            return

        metadata = Individual.load_dir(self._path)

        self._members = [
            self._path / message.name
            for message in metadata
        ]

        self._scores = array("d")
        for message in metadata:
            try:
                score = _score(message, self._score)
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
        description=__doc__
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
        "--host",
        default="[::1]",
        help="gRPC listen address (default: [::1])",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=50051,
        help="gRPC listen port (default: 50051)",
    )

    return parser.parse_args()


def serve(directory, selection, score, host, port):
    player = Player(directory, selection, score)

    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10)
    )

    evolution_pb2_grpc.add_EvolutionServicer_to_server(
        player,
        server,
    )

    address = f"{host}:{port}"
    server.add_insecure_port(address)

    server.start()

    logging.info("npc-player is: %s %s", sys.executable, sys.argv[0])
    logging.info("Listening on: %s", address)
    logging.info("Replay population: %s", directory)
    logging.info("Mate selection: %s", selection)
    logging.info("Score: %s", score)

    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        logging.info("KeyboardInterrupt, stopping npc-player service")
        server.stop(1)


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
        args.host,
        args.port,
    )


if __name__ == "__main__":
    main()
