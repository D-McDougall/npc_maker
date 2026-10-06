#!/usr/bin/env python

"""Vector optimization test environment.

The environment repeatedly spawns an individual, scores its phenome by its
RMS error from a seeded target vector, and then kills it.
"""

import argparse
import json
import math
import random

import grpc

from npc_maker import environment_pb2, environment_pb2_grpc


def make_target(dimension, seed):
    rng = random.Random(seed)
    return [rng.random() for _ in range(dimension)]


def score(phenome, target):
    if len(phenome) != len(target):
        raise ValueError(
            f"phenome has {len(phenome)} dimensions; "
            f"expected {len(target)}"
        )

    return math.sqrt(
        sum((value - expected) ** 2 for value, expected in zip(phenome, target))
        / len(target)
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address", help="Environment service host:port")
    parser.add_argument("dimension", type=int, help="Number of target dimensions")
    parser.add_argument("seed", type=int, help="Seed used to generate the target")
    args = parser.parse_args()

    if args.dimension <= 0:
        parser.error("dimension must be greater than zero")

    target = make_target(args.dimension, args.seed)

    channel = grpc.insecure_channel(args.address)
    environment = environment_pb2_grpc.EnvironmentStub(channel)

    try:
        while True:
            individual = environment.Spawn(environment_pb2.SpawnRequest())

            phenome = json.loads(individual.phenome.decode("utf-8"))
            if not isinstance(phenome, list):
                raise ValueError("phenome JSON must be an array")

            individual_score = score(phenome, target)

            environment.Score(
                environment_pb2.ScoreRequest(
                    name=individual.metadata.name,
                    score=individual_score,
                )
            )
            environment.Death(
                environment_pb2.DeathRequest(name=individual.metadata.name)
            )
    finally:
        channel.close()


if __name__ == "__main__":
    main()
