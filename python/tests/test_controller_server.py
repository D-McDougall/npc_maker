import grpc
import pytest

from npc_maker import controller_pb2
from npc_maker.controller import ControllerServer, _ControllerService


class AbortError(Exception):
    def __init__(self, code, details):
        super().__init__(details)
        self.code = code
        self.details = details


class Context:
    def abort(self, code, details):
        raise AbortError(code, details)


class ExampleController(ControllerServer):
    def __init__(self, phenome):
        self.phenome = phenome
        self.inputs = {}
        self.elapsed = 0.0

    def advance(self, dt):
        self.elapsed += dt

    def set_inputs(self, inputs):
        self.inputs.update(inputs)

    def get_outputs(self, ids):
        outputs = {}
        for interface_id in ids:
            value = self.inputs.get(interface_id, 0.0)
            outputs[interface_id] = (
                value + self.elapsed if isinstance(value, float) else value
            )
        return outputs


def service(controller_type=ExampleController, *args, **kwargs):
    return _ControllerService(controller_type, args, kwargs)


def test_session_constructs_controller_and_converts_typed_io():
    requests = [
        controller_pb2.ControllerRequest(
            request_id=0, initialize=controller_pb2.InitializeRequest(
                phenome=b"genes"
            )
        ),
        controller_pb2.ControllerRequest(
            request_id=1,
            set_inputs=controller_pb2.SetInputsRequest(inputs=[
                controller_pb2.IoValue(id=0, number=2.5),
                controller_pb2.IoValue(id=1, text="hello"),
                controller_pb2.IoValue(id=2, blob=b"data"),
            ]),
        ),
        controller_pb2.ControllerRequest(
            request_id=2, advance=controller_pb2.AdvanceRequest(dt=0.5)
        ),
        controller_pb2.ControllerRequest(
            request_id=3,
            get_outputs=controller_pb2.GetOutputsRequest(ids=[0, 1, 2]),
        ),
    ]

    responses = list(service().Session(iter(requests), Context()))

    assert len(responses) == 1
    response = responses[0]
    assert response.request_id == 3
    assert [(item.id, item.WhichOneof("value")) for item in response.outputs] == [
        (0, "number"), (1, "text"), (2, "blob")
    ]
    assert [item.number for item in response.outputs[:1]] == [3.0]
    assert response.outputs[1].text == "hello"
    assert response.outputs[2].blob == b"data"


def test_session_requires_initialization_first():
    request = controller_pb2.ControllerRequest(
        request_id=0, reset=controller_pb2.ResetRequest()
    )

    with pytest.raises(AbortError) as error:
        list(service().Session(iter([request]), Context()))

    assert error.value.code == grpc.StatusCode.INVALID_ARGUMENT


def test_session_rejects_repeated_initialization():
    initialize = controller_pb2.ControllerRequest(
        initialize=controller_pb2.InitializeRequest(phenome=b"")
    )

    with pytest.raises(AbortError) as error:
        list(service().Session(iter([initialize, initialize]), Context()))

    assert error.value.code == grpc.StatusCode.INVALID_ARGUMENT


def test_session_maps_controller_value_error_to_invalid_argument():
    class InvalidController(ExampleController):
        def get_outputs(self, ids):
            raise ValueError("cannot produce output")

    requests = [
        controller_pb2.ControllerRequest(
            initialize=controller_pb2.InitializeRequest()
        ),
        controller_pb2.ControllerRequest(
            get_outputs=controller_pb2.GetOutputsRequest(ids=[0])
        ),
    ]

    with pytest.raises(AbortError) as error:
        list(service(InvalidController).Session(iter(requests), Context()))

    assert error.value.code == grpc.StatusCode.INVALID_ARGUMENT
    assert error.value.details == "cannot produce output"


def test_session_maps_unexpected_controller_error_to_internal():
    class BrokenController(ExampleController):
        def get_outputs(self, ids):
            raise RuntimeError("private details")

    requests = [
        controller_pb2.ControllerRequest(
            initialize=controller_pb2.InitializeRequest()
        ),
        controller_pb2.ControllerRequest(
            get_outputs=controller_pb2.GetOutputsRequest(ids=[0])
        ),
    ]

    with pytest.raises(AbortError) as error:
        list(service(BrokenController).Session(iter(requests), Context()))

    assert error.value.code == grpc.StatusCode.INTERNAL
    assert error.value.details == "controller session failed"


def test_session_rejects_missing_outputs():
    class IncompleteController(ExampleController):
        def get_outputs(self, ids):
            return {}

    requests = [
        controller_pb2.ControllerRequest(
            initialize=controller_pb2.InitializeRequest()
        ),
        controller_pb2.ControllerRequest(
            get_outputs=controller_pb2.GetOutputsRequest(ids=[0])
        ),
    ]

    with pytest.raises(AbortError) as error:
        list(service(IncompleteController).Session(iter(requests), Context()))

    assert error.value.code == grpc.StatusCode.INVALID_ARGUMENT
    assert "did not return requested IDs" in error.value.details


def test_each_session_gets_a_fresh_controller_instance():
    service_instance = service()

    first = [
        controller_pb2.ControllerRequest(
            initialize=controller_pb2.InitializeRequest(phenome=b"first")
        ),
        controller_pb2.ControllerRequest(
            set_inputs=controller_pb2.SetInputsRequest(
                inputs=[controller_pb2.IoValue(id=0, number=9)]
            )
        ),
        controller_pb2.ControllerRequest(
            get_outputs=controller_pb2.GetOutputsRequest(ids=[0])
        ),
    ]
    second = [
        controller_pb2.ControllerRequest(
            initialize=controller_pb2.InitializeRequest(phenome=b"second")
        ),
        controller_pb2.ControllerRequest(
            get_outputs=controller_pb2.GetOutputsRequest(ids=[0])
        ),
    ]

    first_response = list(service_instance.Session(iter(first), Context()))[0]
    second_response = list(service_instance.Session(iter(second), Context()))[0]

    assert first_response.outputs[0].number == 9.0
    assert second_response.outputs[0].number == 0.0
