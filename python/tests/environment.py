"""
Test environment for npc-server integration tests.

Connects to the Environment service supplied on the command line and repeatedly
spawns and kills individuals.
"""

import argparse
import time

import grpc

from npc_maker import environment_pb2, environment_pb2_grpc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address", help="Environment service host:port")
    args = parser.parse_args()

    channel = grpc.insecure_channel(args.address)
    environment = environment_pb2_grpc.EnvironmentStub(channel)

    try:
        while True:
            response = environment.Spawn(environment_pb2.SpawnRequest())
            individual = response
            environment.Death(
                environment_pb2.DeathRequest(name=individual.metadata.name)
            )
            time.sleep(0.01)
    finally:
        channel.close()


if __name__ == "__main__":
    main()
