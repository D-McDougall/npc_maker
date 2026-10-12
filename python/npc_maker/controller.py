"""Client and server APIs for NPC Maker controller sessions.

# Making new controllers:

Subclasses the ControllerServer, which accepts the phenome as an argument to its
constructor. Then call `main()` the main function, which starts a listen
server, and creates one controller instance for each incomming session.

# Running controllers:

Use the ControllerClient class to run a controller process locally.

"""

from abc import ABC, abstractmethod
import atexit
from collections.abc import Mapping
from concurrent import futures
import queue
import socket
import subprocess
import threading
import time
from math import isfinite
from numbers import Real

import grpc

from . import controller_pb2, controller_pb2_grpc
from . import MAX_MESSAGE_SIZE

__all__ = ("ControllerServer", "ControllerClient")

IoValueType = float | str | bytes
IoValues = Mapping[int, IoValueType]


class ControllerClient:
    """Environment-side wrapper for one streaming controller session.

    The controller process and its gRPC connection are reused for every
    client created with the same CLI invocation. Each client owns an
    independent streaming session and phenome.
    """

    _connections = {}
    _connections_lock = threading.Lock()
    _cleanup_registered = False

    def __init__(self, command, phenome: bytes):
        """Open a session using a controller CLI command and its phenome.

        One processes and gRPC connection is shared by all clients with the same
        command; each client gets its own session and controller instance.
        """
        self._connection = self._get_connection(command)
        self._requests = queue.Queue()
        self._responses = {}
        self._condition = threading.Condition()
        self._request_id = 0
        self._closed = False
        self._error = None

        def request_stream():
            while True:
                request = self._requests.get()
                if request is None:
                    return
                yield request

        self._call = self._connection.stub.Session(request_stream())
        self._reader = threading.Thread(target=self._read_responses, daemon=True)
        self._reader.start()
        self._send("initialize", controller_pb2.InitializeRequest(phenome=phenome))

    @classmethod
    def _get_connection(cls, command):
        if isinstance(command, (str, bytes)):
            raise TypeError("controller command must be a sequence of CLI arguments")
        command = tuple(command)
        if not command or any(not isinstance(argument, str) for argument in command):
            raise ValueError("controller command must contain CLI argument strings")

        with cls._connections_lock:
            connection = cls._connections.get(command)
            if connection is not None and connection.process.poll() is None:
                return connection
            # Check for dead controller processes
            if connection is not None:
                connection.close()
                del cls._connections[command]
            connection = _ControllerConnection(command)
            cls._connections[command] = connection
            if not cls._cleanup_registered:
                atexit.register(cls._close_connections)
                cls._cleanup_registered = True
            return connection

    @classmethod
    def _close_connections(cls):
        """Close every cached process and channel during interpreter exit."""
        with cls._connections_lock:
            for connection in cls._connections.values():
                connection.close()
            cls._connections.clear()

    def _send(self, command: str, value) -> int:
        """Queue a command in session order and return its correlation ID."""
        with self._condition:
            if self._closed:
                raise RuntimeError("controller session is closed")
            if self._error is not None:
                raise self._error
            request_id = self._request_id
            self._request_id += 1
            self._requests.put(controller_pb2.ControllerRequest(
                request_id=request_id, **{command: value}))
        return request_id

    def _read_responses(self):
        """Collect streaming replies and wake callers waiting for a reply."""
        try:
            for response in self._call:
                with self._condition:
                    self._responses[response.request_id] = response
                    self._condition.notify_all()
        except grpc.RpcError as error:
            with self._condition:
                self._error = error
                self._condition.notify_all()
        else:
            with self._condition:
                if not self._closed and self._error is None:
                    self._error = RuntimeError("controller session ended")
                self._condition.notify_all()

    def reset(self) -> None:
        """Request that the controller restore its initial state.

        This command is queued without waiting for an acknowledgement.
        """
        self._send("reset", controller_pb2.ResetRequest())

    def set_inputs(self, values) -> None:
        """Send input values, assigning interface IDs by sequence position.

        ``values[0]`` is sent as interface ID 0, ``values[1]`` as ID 1, and so
        on. This method currently writes every value to the protobuf ``number``
        field, so callers should supply numeric values.
        """
        inputs = [controller_pb2.IoValue(id=i, number=value)
                  for i, value in enumerate(values)]
        self._send("set_inputs", controller_pb2.SetInputsRequest(inputs=inputs))

    def advance(self, interval: float) -> None:
        """Request a state advance by ``interval`` seconds, without waiting."""
        self._send("advance", controller_pb2.AdvanceRequest(dt=interval))

    def get_outputs(self, ids):
        """Return a mapping of requested output interface IDs to values.

        This call waits for the matching response. The server reports an
        error if any requested ID is absent.
        """
        request_id = self._send(
            "get_outputs", controller_pb2.GetOutputsRequest(ids=list(ids)))
        with self._condition:
            while request_id not in self._responses:
                if self._error is not None:
                    raise self._error
                if self._closed:
                    raise RuntimeError("controller session closed before response")
                self._condition.wait()
            response = self._responses.pop(request_id)
            return {output.id: _python_value(output)
                    for output in response.outputs}

    def get_output(self, output_id: int = 0) -> IoValueType:
        """Return one output value, defaulting to interface ID 0."""
        outputs = self.get_outputs([output_id])
        if output_id in outputs:
            return outputs[output_id]
        raise RuntimeError(f"controller did not return output {output_id}")

    def close(self) -> None:
        """End this session and stop its response-reader thread."""
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._condition.notify_all()
        self._requests.put(None)
        self._call.cancel()
        if threading.current_thread() is not self._reader:
            self._reader.join(timeout=1)

    def __enter__(self):
        """Return this client for use as a context manager."""
        return self

    def __exit__(self, *_):
        """Close the session when leaving a ``with`` block."""
        self.close()


class _ControllerConnection:
    """Process, channel, and stub cached for a controller CLI invocation."""

    def __init__(self, command):
        """Start a CLI process and wait up to 30 seconds for its gRPC port."""
        address = f"127.0.0.1:{_free_port()}"
        self.process = subprocess.Popen([*command, "--listen", address])
        self.channel = grpc.insecure_channel(address)
        ready = grpc.channel_ready_future(self.channel)
        deadline = time.monotonic() + 30
        try:
            while True:
                if self.process.poll() is not None:
                    raise RuntimeError(
                        "controller exited during startup "
                        f"(status {self.process.returncode})")
                try:
                    ready.result(timeout=0.25)
                    self.stub = controller_pb2_grpc.ControllerStub(self.channel)
                    return
                except grpc.FutureTimeoutError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("timed out waiting for controller")
        except BaseException:
            self.close()
            raise

    def close(self):
        """Close the channel and stop the child process, escalating if needed."""
        self.channel.close()
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()


def _free_port():
    """Return an available loopback TCP port selected by the operating system."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _valid_id(value: object) -> bool:
    """Return whether value is a valid protobuf uint64 interface ID."""
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 2**64


def _python_value(value: controller_pb2.IoValue) -> IoValueType:
    """Convert a protobuf I/O value to a typed Python value."""
    kind = value.WhichOneof("value")
    if kind == "number":
        return value.number
    if kind == "text":
        return value.text
    if kind == "blob":
        return value.blob
    raise ValueError(f"I/O value {value.id} has no value set")


def _protobuf_value(interface_id: int, value: object) -> controller_pb2.IoValue:
    """Convert a typed Python value to its protobuf representation."""
    if not _valid_id(interface_id):
        raise ValueError(f"invalid interface ID: {interface_id!r}")

    if isinstance(value, bool):
        raise ValueError(f"unsupported value for interface {interface_id}: bool")
    if isinstance(value, Real):
        return controller_pb2.IoValue(id=interface_id, number=float(value))
    if isinstance(value, str):
        return controller_pb2.IoValue(id=interface_id, text=value)
    if isinstance(value, bytes):
        return controller_pb2.IoValue(id=interface_id, blob=value)
    raise ValueError(
        f"unsupported value for interface {interface_id}: "
        f"{type(value).__name__}"
    )


class ControllerServer(ABC):
    """Base class for a single NPC Maker controller session.

    The server constructs a fresh subclass instance for every session, passing
    the session's phenome to __init__. Subclasses must implement __init__ and
    get_outputs(). The other methods (reset, advance, and set_inputs) are
    optional and no-op by default.
    """

    @abstractmethod
    def __init__(self, phenome: bytes, *args, **kwargs):
        """
        Construct controller state from genetic material (the phenome).

        This also receives the *args and **kwargs that were given to the
        `ControllerServer.main()` class-method.
        """
        raise NotImplementedError

    def reset(self) -> None:
        """Restore the controller to its initial state, if applicable."""
        pass

    def advance(self, dt: float) -> None:
        """Advance the controller's internal state by dt seconds, if needed."""
        pass

    def set_inputs(self, inputs: dict[int, IoValueType]) -> None:
        """Receive sensory inputs keyed by interface ID.

        The default implementation ignores inputs. Override this method when
        the controller needs to use environment-provided values.
        """
        pass

    @abstractmethod
    def get_outputs(self, ids: list[int]) -> Mapping[int, IoValueType]:
        """Return values for every requested motor interface ID.

        Implementations must return a mapping containing every ID in ``ids``;
        values may be numbers, strings, or bytes.
        """
        raise NotImplementedError

    @classmethod
    def main(cls, listen: str, *args, **kwargs) -> None:
        """Run this controller implementation as a gRPC server.

        The controller class is instantiated once per session with the
        InitializeRequest phenome followed by *args and **kwargs. The listen
        argument is a gRPC address such as "127.0.0.1:50051". This method
        blocks until the server is stopped.

        Additional arguments (args and kwargs) are passed through to the
        controller class's `__init__()` method.
        """
        if not isinstance(listen, str) or not listen:
            raise ValueError("listen must be a non-empty host:port address")

        # The service can process multiple independent session streams at once.
        executor = futures.ThreadPoolExecutor()
        server = grpc.server(executor, options=[
            ("grpc.max_send_message_length", MAX_MESSAGE_SIZE),
            ("grpc.max_receive_message_length", MAX_MESSAGE_SIZE),
        ])
        controller_pb2_grpc.add_ControllerServicer_to_server(
            _ControllerService(cls, args, kwargs),
            server,
        )

        if server.add_insecure_port(listen) == 0:
            executor.shutdown(wait=True)
            raise RuntimeError(f"could not bind controller server to {listen!r}")

        try:
            server.start()
            server.wait_for_termination()
        except KeyboardInterrupt:
            pass
        finally:
            server.stop(0).wait()
            executor.shutdown(wait=True)


class _SessionError(Exception):
    """Internal exception used to carry a gRPC status out of dispatch."""


class _ControllerService(controller_pb2_grpc.ControllerServicer):
    """Adapt a user-facing ControllerServer class to the generated gRPC service."""

    def __init__(self, controller_type, args, kwargs):
        """Keep the subclass and constructor arguments for each new stream."""
        self._controller_type = controller_type
        self._args = args
        self._kwargs = kwargs

    @staticmethod
    def _abort(context, code, details):
        # Defer context.abort() until the exception handler so its exception
        # cannot be caught and mistakenly remapped by the generic handler.
        raise _SessionError((code, details))

    def Session(self, requests, context):
        """Dispatch one ordered request stream to one controller instance.

        The initialize command is required first. Only output requests produce
        replies; all command or controller failures terminate the stream with
        an appropriate gRPC status.
        """
        controller = None

        for request in requests:
            try:
                command = request.WhichOneof("command")
                if controller is None:
                    if command != "initialize":
                        self._abort(
                            context,
                            grpc.StatusCode.INVALID_ARGUMENT,
                            "the first command must initialize the controller",
                        )
                    # Keep session state isolated while reusing the server process.
                    controller = self._controller_type(
                        request.initialize.phenome,
                        *self._args,
                        **self._kwargs,
                    )
                    continue

                elif command == "initialize":
                    self._abort(
                        context,
                        grpc.StatusCode.INVALID_ARGUMENT,
                        "controller is already initialized",
                    )

                if command == "reset":
                    controller.reset()

                elif command == "advance":
                    dt = request.advance.dt
                    if dt < 0:
                        raise ValueError("advance dt must be non-negative")
                    if not isfinite(dt):
                        raise ValueError("advance dt must be finite")
                    controller.advance(dt)

                elif command == "set_inputs":
                    inputs = {}
                    for item in request.set_inputs.inputs:
                        if item.id in inputs:
                            raise ValueError(f"duplicate input interface ID: {item.id}")
                        inputs[item.id] = _python_value(item)
                    controller.set_inputs(inputs)

                elif command == "get_outputs":
                    ids = list(request.get_outputs.ids)
                    if any(not _valid_id(interface_id) for interface_id in ids):
                        raise ValueError("invalid output interface ID")
                    if len(set(ids)) != len(ids):
                        raise ValueError("duplicate output interface ID")
                    outputs = controller.get_outputs(ids)
                    if not isinstance(outputs, Mapping):
                        raise ValueError("get_outputs() must return a mapping")

                    missing = [interface_id for interface_id in ids
                               if interface_id not in outputs]
                    if missing:
                        raise ValueError(
                            f"get_outputs() did not return requested IDs: {missing}"
                        )

                    # Preserve request order in the response even if the
                    # controller's mapping uses a different iteration order.
                    values = [
                        _protobuf_value(interface_id, outputs[interface_id])
                        for interface_id in ids
                    ]
                    yield controller_pb2.ControllerResponse(
                        request_id=request.request_id,
                        outputs=values,
                    )

                elif command is None:
                    self._abort(
                        context,
                        grpc.StatusCode.INVALID_ARGUMENT,
                        "request contains no command",
                    )

                else:
                    self._abort(
                        context,
                        grpc.StatusCode.INVALID_ARGUMENT,
                        f"unknown command: {command}",
                    )
            except _SessionError as error:
                code, details = error.args[0]
                context.abort(code, details)
            except ValueError as error:
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(error))
            except NotImplementedError as error:
                context.abort(grpc.StatusCode.UNIMPLEMENTED, str(error))
            except Exception:
                context.abort(
                    grpc.StatusCode.INTERNAL,
                    "controller session failed",
                )
