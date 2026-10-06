"""
Test environment for npc-server integration tests.

Connects to the Evolution service supplied on the command line and repeatedly
spawns and kills individuals.
"""

import argparse
import time

import grpc

from npc_maker import evolution_pb2, evolution_pb2_grpc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address", help="Evolution service host:port")
    args = parser.parse_args()

    channel = grpc.insecure_channel(args.address)
    evolution = evolution_pb2_grpc.EvolutionStub(channel)

    try:
        while True:
            response = evolution.Spawn(evolution_pb2.SpawnRequest())
            if len(response.parents) != 1:
                raise RuntimeError(
                    f"expected one parent, got {len(response.parents)}"
                )

            individual = response.parents[0]
            evolution.Death(
                evolution_pb2.DeathRequest(individual=individual)
            )
            time.sleep(0.01)
    finally:
        channel.close()


if __name__ == "__main__":
    main()
