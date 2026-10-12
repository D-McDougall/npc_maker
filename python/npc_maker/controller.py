"""
Base API for implementing NPC Maker controllers.

Subclasses construct a controller session from its phenome. The gRPC
adapter (`npc_maker.controller.Controller` base class) owns the streaming
protocol, converts typed Python I/O values to and from protobuf messages, and
creates one controller instance for each session.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from concurrent import futures
from numbers import Real

import grpc

from . import controller_pb2, controller_pb2_grpc
from . import _MAX_MESSAGE_SIZE

__all__ = ("Controller",)

IoValueType = float | str | bytes
IoValues = Mapping[int, IoValueType]


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


class Controller(ABC):
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
        `Controller.main()` class-method.
        """
        raise NotImplementedError

    def reset(self) -> None:
        """Restore the controller to its initial state, if applicable."""
        pass

    def advance(self, dt: float) -> None:
        """Advance the controller's internal state by dt seconds, if needed."""
        pass

    def set_inputs(self, inputs: dict[int, IoValueType]) -> None:
        """Receive sensory inputs indexed by interface ID."""
        pass

    @abstractmethod
    def get_outputs(self, ids: list[int]) -> Mapping[int, IoValueType]:
        """Return output values for every requested motor interface ID."""
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

        executor = futures.ThreadPoolExecutor()
        server = grpc.server(executor, options=[
            ("grpc.max_send_message_length", _MAX_MESSAGE_SIZE),
            ("grpc.max_receive_message_length", _MAX_MESSAGE_SIZE),
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
    """Adapt a user-facing Controller class to the generated gRPC service."""

    def __init__(self, controller_type, args, kwargs):
        self._controller_type = controller_type
        self._args = args
        self._kwargs = kwargs

    @staticmethod
    def _abort(context, code, details):
        # Defer context.abort() until the exception handler so its exception
        # cannot be caught and mistakenly remapped by the generic handler.
        raise _SessionError((code, details))

    def Session(self, requests, context):
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
