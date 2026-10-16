"""
Base API for implementing NPC Maker genetic services.

# Using Genetic Algorithms

Use the class `GeneticsClient` to start running and interact with a genetics
server.

# Implementing New Genetic Algorithms

Subclasses implement GeneticsServer.reproduce() to create founders and
offspring. The base class adapts that method to the Genetics gRPC service and
provides a `.main()` method for running the implementation as a listening
server.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from concurrent import futures
import os
import socket
import subprocess
import time
from pathlib import Path

import grpc

from . import genetics_pb2, genetics_pb2_grpc
from .individual import Individual
from . import MAX_MESSAGE_SIZE

__all__ = ("GeneticsClient", "GeneticsServer")


def _free_address() -> str:
    """Return a loopback address with an available ephemeral port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return f"127.0.0.1:{sock.getsockname()[1]}"


class GeneticsClient:
    """Start a genetics CLI service and call its reproduction operation.

    Argument ``command`` is the genetics program's CLI invocation. It must be a
    list of strings, starting with the path to an executable. This class
    appends ``--listen HOST:PORT`` arguments to the command line. The genetics
    server will listen on an available loopback port. This class starts the
    process and waits up to ``timeout`` seconds for the gRPC service to become
    ready.

    Use the `reproduce()` method to send parent `Individual` objects and get
    the resulting child. The client owns the subprocess and gRPC channel;
    call the `.close()` method when finished, or use it as a context manager.

    Usage:

    >>> from npc_maker.genetics import GeneticsClient
    >>> 
    >>> with GeneticsClient(["my-genetics-program", "--config", "genes.json"]) as genetics:
    >>>     child = genetics.reproduce([parent_a, parent_b])

    Args:
        command: The genetics program invocation, excluding ``--listen``.
        timeout: Maximum seconds to wait for service startup.
        cwd: Optional working directory for the genetics process. It is
            created if it does not already exist.

    Raises:
        ValueError: If the command is empty or timeout is not positive.
        RuntimeError: If the service exits during startup or does not become
            ready before the timeout.
        OSError: If the command cannot be started.
    """

    def __init__(self, command: list[str], timeout: float = 30, cwd=None):
        if not command:
            raise ValueError("command must not be empty")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if cwd is not None:
            cwd = Path(cwd)
            cwd.mkdir(parents=True, exist_ok=True)

        self.address = _free_address()
        self.process = None
        self.channel = grpc.insecure_channel(self.address, options=[
            ('grpc.max_send_message_length', MAX_MESSAGE_SIZE),
            ('grpc.max_receive_message_length', MAX_MESSAGE_SIZE),
        ])
        try:
            self.process = subprocess.Popen(
                [*command, "--listen", self.address], cwd=cwd)
            ready = grpc.channel_ready_future(self.channel)
            deadline = time.monotonic() + timeout
            while True:
                if self.process.poll() is not None:
                    raise RuntimeError(
                        "genetics service exited during startup "
                        f"(status {self.process.returncode})")
                try:
                    ready.result(timeout=min(0.25, max(0, deadline - time.monotonic())))
                    break
                except grpc.FutureTimeoutError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("timed out waiting for genetics service")
            self.stub = genetics_pb2_grpc.GeneticsStub(self.channel)
        except BaseException:
            self.close()
            raise

    def reproduce(self, parents: Sequence[Individual]) -> Individual:
        """Ask the genetics service to create a founder or offspring.

        Pass an empty sequence to request a founder. For offspring, pass the
        parent individuals. gRPC errors from the service are propagated.
        """
        response = self.stub.Reproduce(genetics_pb2.ReproduceRequest(
            parents=[parent.to_proto() for parent in parents]))
        return Individual.from_proto(response.child)

    def close(self) -> None:
        """Close the channel and stop and reap the genetics subprocess."""
        if self.channel is not None:
            self.channel.close()
            self.channel = None
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()

    def __enter__(self):
        """Return this client for use in a ``with`` block."""
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Stop the service when leaving a ``with`` block."""
        self.close()


class GeneticsServer(genetics_pb2_grpc.GeneticsServicer, ABC):
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

    def main(self, listen: str) -> None:
        """Run this genetics implementation as a gRPC server.

        Call this method on an initialized implementation. ``listen`` is a
        gRPC address such as "127.0.0.1:50051". This method blocks until the
        server is stopped.
        """
        if not isinstance(listen, str) or not listen:
            raise ValueError("listen must be a non-empty host:port address")

        executor = futures.ThreadPoolExecutor()
        server = grpc.server(executor, options=[
            ('grpc.max_send_message_length', MAX_MESSAGE_SIZE),
            ('grpc.max_receive_message_length', MAX_MESSAGE_SIZE),
        ])
        genetics_pb2_grpc.add_GeneticsServicer_to_server(self, server)

        # Zero indicates a bind failure; port 0 may request an ephemeral port.
        if server.add_insecure_port(listen) == 0:
            executor.shutdown(wait=True)
            raise RuntimeError(f"could not bind genetics server to {listen!r}")

        try:
            server.start()
            server.wait_for_termination()
        except KeyboardInterrupt:
            pass
        finally:
            server.stop(0).wait()
            executor.shutdown(wait=True)
