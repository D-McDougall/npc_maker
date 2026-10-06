"""
Test environment for npc-server integration tests.

Connects to the Environment service supplied on the command line and repeatedly
spawns and kills individuals.
"""

import argparse
import random
import string

import grpc

from npc_maker import environment_pb2, environment_pb2_grpc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address", help="Environment service host:port")
    args = parser.parse_args()

    channel = grpc.insecure_channel(args.address)
    environment = environment_pb2_grpc.EnvironmentStub(channel)

    living = {}

    def random_string(length=8):
        return "".join(
            random.choices(string.ascii_letters + string.digits, k=length)
        )

    def spawn():
        individual = environment.Spawn(environment_pb2.SpawnRequest())
        living[individual.metadata.name] = individual

    def mate():
        parent = random.choice(list(living.values()))
        compatible = [
            individual
            for individual in living.values()
            if individual.metadata.body_type == parent.metadata.body_type
            and individual.metadata.name != parent.metadata.name
        ]
        parents = [parent.metadata.name]
        if compatible and random.choice([True, False]):
            parents.append(random.choice(compatible).metadata.name)

        individual = environment.Mate(
            environment_pb2.MateRequest(parents=parents)
        )
        living[individual.metadata.name] = individual

    def score():
        individual = random.choice(list(living.values()))
        environment.Score(
            environment_pb2.ScoreRequest(
                name=individual.metadata.name,
                score=random.uniform(-100.0, 100.0),
            )
        )

    def telemetry():
        individual = random.choice(list(living.values()))
        environment.Telemetry(
            environment_pb2.TelemetryRequest(
                name=individual.metadata.name,
                data=[
                    environment_pb2.KeyValue(
                        key=random_string(),
                        value=random_string(),
                    )
                ],
            )
        )

    def death():
        individual = random.choice(list(living.values()))
        environment.Death(
            environment_pb2.DeathRequest(name=individual.metadata.name)
        )
        del living[individual.metadata.name]

    operations = [spawn, mate, score, telemetry, death]

    try:
        while True:
            # There is no valid operation other than spawn when the environment
            # is empty. Once an individual exists, choose uniformly from all
            # five operations.
            operation = spawn if not living else random.choice(operations)
            operation()
    finally:
        channel.close()


if __name__ == "__main__":
    main()
