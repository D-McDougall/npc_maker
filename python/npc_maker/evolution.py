"""Base API for implementing NPC Maker evolution services.

# Using Evolutionary Algorithms

Use the class `EvolutionClient` to start and interact with an evolution
server.

# Implementing New Evolutionary Algorithms

Subclasses implement `EvolutionServer.spawn()` to select parents and
`EvolutionServer.death()` to receive each individual's final record.
The base class adapts those methods to the Evolution gRPC service and
provides a `.main()` method for running the implementation as a server.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from concurrent import futures
import socket
import subprocess
import time
from pathlib import Path

import grpc

from . import MAX_MESSAGE_SIZE
from . import evolution_pb2, evolution_pb2_grpc
from .individual import Individual

__all__ = ("EvolutionClient", "EvolutionServer")


def _free_address() -> str:
    """Return a loopback address with an available ephemeral port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return f"127.0.0.1:{sock.getsockname()[1]}"


class EvolutionClient:
    """
    Start an evolution CLI service and call its operations.

    Argument ``command`` is the evolution program's CLI invocation. It must
    be a list of strings, starting with the path to an executable. This class
    appends ``--listen HOST:PORT`` arguments to the command line. The evolution 
    server is configured to listen on an available loopback port. This class
    starts the process and waits up to ``timeout`` seconds for the gRPC service
    to become ready.

    Use `.spawn()` to select parents and `.death()` to send final individual
    records. The client owns the subprocess and gRPC channel; call `.close()`
    when finished, or use it as a context manager.

    Args:
        command: The evolution program invocation, excluding ``--listen``.
        timeout: Maximum seconds to wait for service startup.
        cwd: Optional working directory for the evolution process. It is
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
                        "evolution service exited during startup "
                        f"(status {self.process.returncode})")
                try:
                    ready.result(timeout=min(0.25, max(0, deadline - time.monotonic())))
                    break
                except grpc.FutureTimeoutError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("timed out waiting for evolution service")
            self.stub = evolution_pb2_grpc.EvolutionStub(self.channel)
        except BaseException:
            self.close()
            raise

    def spawn(self) -> list[Individual]:
        """
        Ask the evolution service to select zero or more parents.

        gRPC errors from the service are propagated.
        """
        response = self.stub.Spawn(evolution_pb2.SpawnRequest())
        return [Individual.from_proto(parent) for parent in response.parents]

    def death(self, individual: Individual) -> None:
        """
        Send an individual's final record to the evolution service.

        gRPC errors from the service are propagated.
        """
        self.stub.Death(evolution_pb2.DeathRequest(individual=individual.to_proto()))

    def close(self) -> None:
        """
        Close the channel and stop and reap the evolution subprocess.
        """
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
            finally:
                self.process = None

    def __enter__(self):
        """
        Return this client for use in a ``with`` block.
        """
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """
        Stop the service when leaving a ``with`` block.
        """
        self.close()

    def __del__(self):
        self.close()


class EvolutionServer(evolution_pb2_grpc.EvolutionServicer, ABC):
    """
    Base class for an evolutionary algorithm's gRPC service implementation.

    Implement spawn() to select parents for a child and death() to receive an
    individual's final record. Spawned parents must have valid names.
    """

    @abstractmethod
    def spawn(self) -> Sequence[Individual]:
        """
        Select zero or more named parent individuals for a new child.

        Raise ValueError when parent selection is invalid for this algorithm.
        """
        raise NotImplementedError

    @abstractmethod
    def death(self, individual: Individual) -> None:
        """
        Receive an individual's final record after it dies.

        Raise ValueError when the record is invalid for this algorithm.
        """
        raise NotImplementedError

    def Spawn(self, request, context):
        """
        Adapt a protobuf request to spawn() and serialize its result.
        """
        try:
            parents = self.spawn()
        except ValueError as error:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(error))

        if not isinstance(parents, Sequence):
            context.abort(
                grpc.StatusCode.INTERNAL,
                "spawn() must return a sequence of Individuals",
            )

        for parent in parents:
            if not isinstance(parent, Individual):
                context.abort(
                    grpc.StatusCode.INTERNAL,
                    "spawn() must return a sequence of Individuals",
                )
            if not isinstance(parent.name, str) or not parent.name:
                context.abort(
                    grpc.StatusCode.INTERNAL,
                    "spawn() must return Individuals with non-empty names",
                )

        return evolution_pb2.SpawnResponse(
            parents=[parent.to_proto() for parent in parents])

    def Death(self, request, context):
        """
        Adapt a protobuf request to death().
        """
        individual = Individual.from_proto(request.individual)
        try:
            result = self.death(individual)
        except ValueError as error:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(error))

        if result is not None:
            context.abort(
                grpc.StatusCode.INTERNAL,
                "death() must return None",
            )

        return evolution_pb2.DeathResponse()

    def main(self, listen: str) -> None:
        """
        Run this evolution implementation as a gRPC server.

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
        evolution_pb2_grpc.add_EvolutionServicer_to_server(self, server)

        if server.add_insecure_port(listen) == 0:
            executor.shutdown(wait=True)
            raise RuntimeError(f"could not bind evolution server to {listen!r}")

        try:
            server.start()
            server.wait_for_termination()
        except KeyboardInterrupt:
            pass
        finally:
            server.stop(0).wait()
            executor.shutdown(wait=True)
