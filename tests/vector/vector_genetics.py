#!/usr/bin/env python

"""Vector genetics service.

Implements reproduction for the vector optimization test environment. Genomes
and phenomes are JSON arrays of numbers, with the phenome copied directly from
the genome.
"""

import argparse
import json
import random
from concurrent import futures

import grpc

from npc_maker import genetics_pb2, genetics_pb2_grpc
from npc_maker.individual import Individual


MUTATION_RATE = 0.01


class VectorGenetics(genetics_pb2_grpc.GeneticsServicer):
    def __init__(self, dimension):
        self.dimension = dimension

    def Reproduce(self, request, context):
        if request.parents:
            parent = Individual.from_proto(request.parents[0])
            try:
                genome = json.loads((parent.genome or b"").decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("parent genome must be a JSON array") from error

            if not isinstance(genome, list):
                raise ValueError("parent genome must be a JSON array")
            if len(genome) != self.dimension:
                raise ValueError(
                    f"parent genome has {len(genome)} dimensions; "
                    f"expected {self.dimension}"
                )

            genome = [
                random.random() if random.random() < MUTATION_RATE else value
                for value in genome
            ]
            child = Individual.reproduce([parent])
        else:
            genome = [random.random() for _ in range(self.dimension)]
            child = Individual()

        encoded = json.dumps(genome).encode("utf-8")
        child.genome = encoded
        child.phenome = encoded

        return genetics_pb2.ReproduceResponse(child=child.to_proto())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen", required=True, help="Listen address host:port")
    parser.add_argument("dimension", type=int, help="Number of vector dimensions")
    args = parser.parse_args()

    if args.dimension <= 0:
        parser.error("dimension must be greater than zero")

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    genetics_pb2_grpc.add_GeneticsServicer_to_server(
        VectorGenetics(args.dimension),
        server,
    )
    server.add_insecure_port(args.listen)
    server.start()

    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop(0).wait()


if __name__ == "__main__":
    main()
