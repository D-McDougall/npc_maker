#!/usr/bin/env python3

"""
Polyploid binary genetics service for the NK environment.

Genomes are JSON arrays of homologous binary vectors. Each parent contributes
one gamete, formed by independently choosing a homolog at each gene and
applying bit-flip mutation. Phenomes are the component-wise mean of the
homologous vectors. Founders receive one random binary vector.
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
    """Decode and validate a parent's homologous binary vectors."""
    try:
        genome = json.loads((parent.genome or b"").decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(
            "parent genome must be a JSON array of binary vectors"
        ) from error

    if not isinstance(genome, list) or not genome:
        raise ValueError("parent genome must be a non-empty JSON array of vectors")
    for vector in genome:
        if not isinstance(vector, list):
            raise ValueError("each parent genome component must be a JSON array")
        if len(vector) != n:
            raise ValueError(
                f"parent genome component has {len(vector)} genes; expected {n}"
            )
        if any(type(gene) is not int or gene not in (0, 1) for gene in vector):
            raise ValueError("parent genome genes must be integers 0 or 1")
    return genome


def _make_gamete(genome):
    """Choose one homolog at each gene and independently mutate each bit."""
    gamete = []
    for index in range(len(genome[0])):
        gene = random.choice(genome)[index]
        if random.random() < MUTATION_RATE:
            gamete.append(1 - gene)
        else:
            gamete.append(gene)
    return gamete


def _make_phenome(genome):
    """Return the per-gene mean across homologous vectors."""
    return [
        sum(vector[index] for vector in genome) / len(genome)
        for index in range(len(genome[0]))
    ]


class PolyploidGenetics(genetics_pb2_grpc.GeneticsServicer):
    def __init__(self, n):
        self.n = n

    def Reproduce(self, request, context):
        if request.parents:
            parents = [Individual.from_proto(proto) for proto in request.parents]
            parent_genomes = [
                _decode_genome(parent, self.n) for parent in parents
            ]
            genome = [
                _make_gamete(parent_genome) for parent_genome in parent_genomes
            ]
            child = Individual.reproduce(parents)
        else:
            genome = [[random.randint(0, 1) for _ in range(self.n)]]
            child = Individual()

        child.genome = json.dumps(genome).encode("utf-8")
        child.phenome = json.dumps(_make_phenome(genome)).encode("utf-8")
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
        PolyploidGenetics(args.N),
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
