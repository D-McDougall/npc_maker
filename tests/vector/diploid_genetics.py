#!/usr/bin/env python

"""
Diploid vector genetics service.

Genomes are JSON arrays of gamete vectors. A phenome is the component-
wise average of those vectors. During reproduction, each parent produces a
gamete by independently inheriting each vector component from one of that
parent's gamete vectors.
"""

import argparse
import json
import random
from concurrent import futures

import grpc

from npc_maker import genetics_pb2, genetics_pb2_grpc
from npc_maker.individual import Individual


MUTATION_RATE = 0.01


def _decode_genome(parent, dimension):
    try:
        genome = json.loads((parent.genome or b"").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("parent genome must be a JSON array of vectors") from error

    if not isinstance(genome, list) or not genome:
        raise ValueError("parent genome must be a non-empty JSON array of vectors")

    for vector in genome:
        if not isinstance(vector, list):
            raise ValueError("each parent genome component must be a JSON array")
        if len(vector) != dimension:
            raise ValueError(
                f"parent genome component has {len(vector)} dimensions; "
                f"expected {dimension}"
            )
        if any(not isinstance(value, (int, float)) for value in vector):
            raise ValueError("parent genome components must contain numbers")

    return genome


def _make_gamete(genome):
    dimension = len(genome[0])
    gamete = []
    for index in range(dimension):
        value = random.choice(genome)[index]
        if random.random() < MUTATION_RATE:
            value = random.random()
        # value += random.gauss(0, .001)
        gamete.append(value)
    return gamete


def _make_phenome(genome):
    return [
        sum(vector[index] for vector in genome) / len(genome)
        for index in range(len(genome[0]))
    ]


class DiploidGenetics(genetics_pb2_grpc.GeneticsServicer):
    def __init__(self, dimension):
        self.dimension = dimension

    def Reproduce(self, request, context):
        if request.parents:
            parents = [Individual.from_proto(proto) for proto in request.parents]
            parent_genomes = [
                _decode_genome(parent, self.dimension) for parent in parents
            ]
            genome = [_make_gamete(parent_genome) for parent_genome in parent_genomes]
            child = Individual.reproduce(parents)
        else:
            genome = [[random.random() for _ in range(self.dimension)]]
            child = Individual()

        encoded_genome = json.dumps(genome).encode("utf-8")
        encoded_phenome = json.dumps(_make_phenome(genome)).encode("utf-8")
        child.genome = encoded_genome
        child.phenome = encoded_phenome

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
        DiploidGenetics(args.dimension),
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
