#!/usr/bin/env python

"""
Monoploid binary genetics service for the NK environment.

Genomes and phenomes are JSON arrays of 0/1 values. Offspring inherit one
parent's genome with independent bit-flip mutations; founders receive a random
binary genome.
"""

import argparse
import json
import random
from concurrent import futures

import grpc

from npc_maker import genetics_pb2, genetics_pb2_grpc
from npc_maker.individual import Individual


MUTATION_RATE = 0.01


def _decode_genome(parent, n):
    """Decode and validate a parent's binary genome."""
    try:
        genome = json.loads((parent.genome or b"").decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("parent genome must be a JSON array of 0/1 values") from error

    if not isinstance(genome, list):
        raise ValueError("parent genome must be a JSON array of 0/1 values")
    if len(genome) != n:
        raise ValueError(f"parent genome has {len(genome)} genes; expected {n}")
    if any(type(gene) is not int or gene not in (0, 1) for gene in genome):
        raise ValueError("parent genome genes must be integers 0 or 1")
    return genome


def _mutate(genome):
    """Return a copy with each bit independently inverted at MUTATION_RATE."""
    return [
        1 - gene if random.random() < MUTATION_RATE else gene
        for gene in genome
    ]


class MonoploidBinaryGenetics(genetics_pb2_grpc.GeneticsServicer):
    def __init__(self, n):
        self.n = n

    def Reproduce(self, request, context):
        if request.parents:
            # A monoploid child has one parent; any additional supplied parents
            # are intentionally ignored.
            parent = Individual.from_proto(request.parents[0])
            genome = _mutate(_decode_genome(parent, self.n))
            child = Individual.reproduce([parent])
        else:
            genome = [random.randint(0, 1) for _ in range(self.n)]
            child = Individual()

        encoded = json.dumps(genome).encode("utf-8")
        child.genome = encoded
        child.phenome = encoded
        return genetics_pb2.ReproduceResponse(child=child.to_proto())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen", required=True, help="Listen address host:port")
    parser.add_argument("N", type=int, help="Number of genes in the genome")
    args = parser.parse_args()

    if args.N <= 0:
        parser.error("N must be greater than zero")

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    genetics_pb2_grpc.add_GeneticsServicer_to_server(
        MonoploidBinaryGenetics(args.N),
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
