#!/usr/bin/env python3
"""
Exclusive-Or environment.
"""

import argparse

import grpc

from npc_maker.controller import ControllerClient
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
            for _ in range(round(tstop / dt)):
                controller.set_inputs((input_1, input_2))
                controller.advance(dt)
            answer = float(controller.get_output())
            answer = max(0.0, min(1.0, answer))
            correct = float(input_1 != input_2)
            distance += abs(answer - correct)
            if verbose:
                print(f"{input_1} xor {input_2} = {answer}", flush=True)

    score = (4.0 - distance) ** 2
    if verbose:
        print(f"score {score}", flush=True)
    return score


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
            command = tuple(individual.metadata.controller)
            controller = ControllerClient(command, individual.phenome)
            try:
                score = evaluate(controller, args.verbose)
            finally:
                controller.close()

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
