"""
Replay previously saved individuals through the Evolution gRPC service.

The player presents a saved population through the Evolution API. Each Spawn
request selects one saved individual according to the configured score function
and mate-selection algorithm, and then returns a copy of that individual.

The Death RPC is intentionally a no-op: replayed individuals already lived and
their death does not change the replay population.
"""

# Standard Library
from concurrent import futures
from pathlib import Path
import argparse
import logging
import threading

# Third Party
import grpc

# First Party
from npc_maker._protobuf import evolution_pb2
from npc_maker._protobuf import evolution_pb2_grpc
from npc_maker.individual import Individual
import mate_selection


class Player(evolution_pb2_grpc.EvolutionServicer):
    """
    Evolution service which replays a population of saved Individuals.
    """

    def __init__(self, path, selection):
        self._path = Path(path)
        self._lock = threading.RLock()

        self._select = mate_selection.parse(selection)

        # Paths to saved individuals.  These run parallel to _scores.
        self._members = []
        self._scores = []

        # Individuals selected by the selection algorithm but not yet spawned.
        self._buffer = []

        # Used to detect changes to the replay population.
        self._scan_time = None

    def Spawn(self, request, context):
        """
        Select and return one saved Individual.
        """
        with self._lock:
            self._scan()

            if not self._members:
                context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    "replay population is empty",
                )

            if not self._buffer:
                indices = self._select.select(len(self._members), self._scores)
                self._buffer.extend(self._members[index] for index in indices)

            path = self._buffer.pop()

        return evolution_pb2.SpawnResponse(parents=[Individual.load(path).to_proto()])

    def Death(self, request, context):
        """
        Discard the individual. The replayer does not modify the population.
        """
        return evolution_pb2.DeathResponse()

    def _scan(self):
        """
        Update the population if the replay directory has changed.
        """
        scan_time = self._path.stat().st_mtime_ns

        if scan_time == self._scan_time:
            return

        metadata = Individual.load_dir(self._path)

        self._members = [
            self._path / message.name
            for message in metadata
        ]

        self._scores = [
            float(message.score) if message.HasField("score") else float("-inf")
            for message in metadata
        ]

        # A changed population invalidates selections made from the old one.
        self._buffer = []
        self._scan_time = scan_time


def parse_args():
    parser = argparse.ArgumentParser(
        description="Replay saved NPC Maker individuals through gRPC."
    )

    parser.add_argument(
        "directory",
        type=Path,
        help="directory containing saved Individual directories",
    )

    parser.add_argument(
        "selection",
        help=(
            "mate selection specification, such as 'random', "
            "'proportional', or 'best=10'"
        ),
    )

    parser.add_argument(
        "--host",
        default="[::]",
        help="gRPC listen address (default: [::])",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=50051,
        help="gRPC listen port (default: 50051)",
    )

    return parser.parse_args()


def serve(directory, selection, host, port):
    player = Player(directory, selection)

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

    logging.info("NPC player listening on %s", address)
    logging.info("Replay population: %s", directory)
    logging.info("Mate selection: %s", selection)

    server.wait_for_termination()


def main():
    args = parse_args()

    if not args.directory.is_dir():
        raise SystemExit(
            f"replay directory does not exist or is not a directory: "
            f"{args.directory}"
        )

    logging.basicConfig(level=logging.INFO)

    serve(
        args.directory,
        args.selection,
        args.host,
        args.port,
    )


if __name__ == "__main__":
    main()
