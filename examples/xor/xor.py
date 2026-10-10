#!/usr/bin/env python3
"""
Exclusive-Or environment.
"""

import argparse
import queue
import socket
import subprocess
import time

import grpc

from npc_maker import controller_pb2, controller_pb2_grpc
from npc_maker import environment_pb2, environment_pb2_grpc


tstop = 100
dt = 0.1

def evaluate(controller, verbose=False):
    """
    Return a score in the range [0, 16] by evaluating all four XOR input pairs.
    """
    distance = 0.0
    for input_1 in (0, 1):
        for input_2 in (0, 1):
            controller.reset()
            previous = None
            answer = 0.0
            for _ in range(round(tstop / dt)):
                controller.set_inputs((input_1, input_2))
                controller.advance(dt)
                answer = float(controller.get_output())
                if answer == previous:
                    break
                previous = answer
            correct = float(input_1 != input_2)
            answer = max(0.0, min(1.0, answer))
            distance += abs(answer - correct)
            if verbose:
                print(f"{input_1} xor {input_2} = {answer}", flush=True)

    score = (4.0 - distance) ** 2
    if verbose:
        print(f"score {score}", flush=True)
    return score


class ControllerSession:
    """Synchronous request/response helper for one controller stream."""

    def __init__(self, stub, phenome):
        self.requests = queue.Queue()
        self.request_id = 0

        def request_stream():
            while True:
                request = self.requests.get()
                if request is None:
                    return
                yield request

        self.call = stub.Session(request_stream())
        self._send("initialize", controller_pb2.InitializeRequest(phenome=phenome))

    def _send(self, command, value):
        request = controller_pb2.ControllerRequest(
            request_id=self.request_id, **{command: value})
        self.request_id += 1
        self.requests.put(request)
        return request.request_id

    def reset(self):
        self._send("reset", controller_pb2.ResetRequest())

    def set_inputs(self, values):
        inputs = [controller_pb2.IoValue(id=i, number=value)
                  for i, value in enumerate(values)]
        self._send("set_inputs", controller_pb2.SetInputsRequest(inputs=inputs))

    def advance(self, interval):
        self._send("advance", controller_pb2.AdvanceRequest(dt=interval))

    def get_output(self, output_id=0):
        request_id = self._send(
            "get_outputs",
            controller_pb2.GetOutputsRequest(ids=[output_id]))
        response = next(self.call)
        if response.request_id != request_id:
            raise RuntimeError("controller returned an out-of-order response")
        for output in response.outputs:
            if output.id == output_id:
                if output.WhichOneof("value") != "number":
                    raise TypeError("XOR controller output must be numeric")
                return output.number
        raise RuntimeError(f"controller did not return output {output_id}")

    def close(self):
        self.requests.put(None)
        self.call.cancel()


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _start_controller(command, phenome):
    address = f"127.0.0.1:{_free_port()}"
    process = subprocess.Popen([*command, "--listen", address])
    channel = grpc.insecure_channel(address)
    ready = grpc.channel_ready_future(channel)
    deadline = time.monotonic() + 30
    try:
        if process.poll() is not None:
            raise RuntimeError(
                f"controller exited during startup (status {process.returncode})")
        try:
            ready.result(timeout=0.25)
            return process, channel, ControllerSession(
                controller_pb2_grpc.ControllerStub(channel), phenome)
        except grpc.FutureTimeoutError:
            if time.monotonic() >= deadline:
                raise RuntimeError("timed out waiting for XOR controller")
    except BaseException:
        channel.close()
        process.terminate()
        process.wait()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen", required=True, help="npc-server HOST:PORT")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    channel = grpc.insecure_channel(args.listen)
    environment = environment_pb2_grpc.EnvironmentStub(channel)
    try:
        while True:
            individual = environment.Spawn(environment_pb2.SpawnRequest())
            process, controller_channel, controller = _start_controller(
                individual.metadata.controller, individual.phenome)
            try:
                score = evaluate(controller, args.verbose)
            finally:
                controller.close()
                controller_channel.close()
                process.terminate()
                process.wait()

            environment.Score(environment_pb2.ScoreRequest(
                name=individual.metadata.name, score=score))
            environment.Death(environment_pb2.DeathRequest(
                name=individual.metadata.name))
    except grpc.RpcError as error:
        if error.code() != grpc.StatusCode.UNAVAILABLE:
            raise
    finally:
        channel.close()


if __name__ == "__main__":
    main()
