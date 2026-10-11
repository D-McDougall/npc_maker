"""
Base API for implementing NPC Maker genetic services.

Subclasses implement reproduce() to create founders and offspring. The base
class adapts that method to the Genetics gRPC service and provides main() for
running the implementation as a listening server.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from concurrent import futures

import grpc

from . import genetics_pb2, genetics_pb2_grpc
from .individual import Individual

__all__ = ("Genetics",)


class Genetics(genetics_pb2_grpc.GeneticsServicer, ABC):
    """Base class for a genetic algorithm's gRPC service implementation.

    Implement reproduce() to create founders and offspring. An empty parent
    sequence requests a founder. For offspring, implementations should use
    Individual.reproduce() to initialize lineage metadata.

    The base class deliberately does not require genetic fields such as genome,
    epigenome, or phenome to be set. Those requirements depend on the algorithm.
    """

    @abstractmethod
    def reproduce(self, parents: Sequence[Individual]) -> Individual:
        """Create a founder or offspring from the supplied parents.

        An empty parent sequence requests a founder. Raise ValueError when the
        request is invalid for this algorithm. The returned individual's name
        must be non-empty; genetic fields are algorithm-specific.
        """
        raise NotImplementedError

    def Reproduce(self, request, context):
        """Adapt a protobuf request to reproduce() and serialize its result."""
        parents = [
            Individual.from_proto(parent)
            for parent in request.parents
        ]

        try:
            child = self.reproduce(parents)
        except ValueError as error:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(error))

        if not isinstance(child, Individual):
            context.abort(
                grpc.StatusCode.INTERNAL,
                "reproduce() must return an Individual",
            )

        if not isinstance(child.name, str) or not child.name:
            context.abort(
                grpc.StatusCode.INTERNAL,
                "reproduce() must return an Individual with a non-empty name",
            )

        return genetics_pb2.ReproduceResponse(child=child.to_proto())

    @classmethod
    def main(cls, listen: str, *args, **kwargs) -> None:
        """Run this genetics implementation as a gRPC server.

        listen is a gRPC address such as "127.0.0.1:50051". Additional
        positional and keyword arguments are passed to the implementation's
        constructor, supporting algorithms that require configuration.
        This method blocks until the server is stopped.
        """
        if not isinstance(listen, str) or not listen:
            raise ValueError("listen must be a non-empty host:port address")

        server = grpc.server(futures.ThreadPoolExecutor())
        genetics_pb2_grpc.add_GeneticsServicer_to_server(
            cls(*args, **kwargs),
            server,
        )

        # Zero indicates a bind failure; port 0 may request an ephemeral port.
        if server.add_insecure_port(listen) == 0:
            raise RuntimeError(f"could not bind genetics server to {listen!r}")

        try:
            server.start()
            server.wait_for_termination()
        except KeyboardInterrupt:
            pass
        finally:
            server.stop(0).wait()
