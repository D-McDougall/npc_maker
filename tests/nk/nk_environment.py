#!/usr/bin/env python3
"""
NK-model fitness landscape environment.

The environment evaluates real-valued phenomes on a seeded NK landscape. Each
locus (gene) has a random fitness contribution table for itself and K other
loci. The table is extended to [0, 1] inputs by multilinear interpolation.
Final fitness is the mean of the N contributions. The environment repeatedly
spawns, scores, and kills individuals.
"""

import argparse
import json
import math
import random

import grpc

from npc_maker import environment_pb2, environment_pb2_grpc


class NKLandscape:
    """
    A reproducible continuous-valued extension of an NK landscape.
    """

    def __init__(self, n, k, seed):
        if n <= 0:
            raise ValueError("N must be greater than zero")
        if not 0 <= k < n:
            raise ValueError("K must be in the range [0, N)")

        self.n = n
        self.k = k
        rng = random.Random(seed)

        # Build the interaction pattern first. For every locus i, choose K
        # different loci from all the other positions. These are the genes
        # whose values, together with gene i, determine i's fitness
        # contribution. When K=0, this is an empty tuple and each locus
        # depends only on itself.
        self.neighbors = tuple(
            tuple(rng.sample([j for j in range(n) if j != i], k))
            for i in range(n)
        )

        # A locus and its K neighbors have K+1 binary corner values, so there
        # are 2**(K+1) possible corners. Give each corner an independent
        # random contribution in [0, 1]. For continuous alleles, evaluate()
        # interpolates among these corner values instead of selecting only one.
        self.tables = tuple(
            tuple(rng.random() for _ in range(1 << (k + 1)))
            for _ in range(n)
        )

    def evaluate(self, phenome):
        """Return mean fitness for N numeric alleles in the range [0, 1]."""
        if len(phenome) != self.n:
            raise ValueError(
                f"phenome has {len(phenome)} genes; expected {self.n}"
            )
        if any(not (0 <= gene <= 1) for gene in phenome):
            raise ValueError("phenome genes must be numbers in the range [0, 1]")

        # For each locus, gather its own allele followed by its neighbors.
        # These K+1 numbers determine a position inside the locus's binary
        # table. For a real-valued input, its contribution is a weighted sum
        # of all table entries (the table's corners). The weight for a corner
        # is the product of x for every bit set to 1 and (1-x) for every bit
        # set to 0. The weights sum to 1, so this is multilinear interpolation.
        total = 0.0
        for i in range(self.n):
            # Bit 0 corresponds to locus i; bits 1..K follow the stored
            # neighbor order. Thus each table index identifies one binary
            # corner of this locus's K+1 dimensional contribution function.
            inputs = (phenome[i], *(phenome[j] for j in self.neighbors[i]))
            contribution = 0.0
            for table_index, table_value in enumerate(self.tables[i]):
                weight = 1.0
                for bit, value in enumerate(inputs):
                    if table_index & (1 << bit):
                        weight *= value
                    else:
                        weight *= 1.0 - value
                contribution += weight * table_value
            total += contribution

        # NK fitness is the average of the N locus contributions. Since each
        # interpolated contribution is a weighted average of values in [0, 1],
        # the overall score is also in [0, 1]. At binary phenomes this reduces
        # to the usual NK lookup of one table entry per locus.
        return total / self.n


def make_landscape(n, k, seed):
    """Create a seeded NK landscape (convenient for callers and tests)."""
    return NKLandscape(n, k, seed)


def score(phenome, landscape):
    """Score a real-valued phenome on an :class:`NKLandscape`."""
    return landscape.evaluate(phenome)


def decode_phenome(encoded, n):
    """Decode a JSON array of real-valued genes."""
    try:
        phenome = json.loads(encoded.decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("phenome must be a JSON array of numbers in [0, 1]") from error

    if not isinstance(phenome, list):
        raise ValueError("phenome must be a JSON array of numbers in [0, 1]")
    if len(phenome) != n:
        raise ValueError(f"phenome has {len(phenome)} genes; expected {n}")
    return phenome


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen", required=True, help="Environment service host:port")
    parser.add_argument("N", type=int, help="Number of real-valued genes")
    parser.add_argument("K", type=int, help="Number of interacting genes per locus")
    parser.add_argument("seed", type=int, help="Seed used to generate the landscape")
    args = parser.parse_args()

    try:
        landscape = make_landscape(args.N, args.K, args.seed)
    except ValueError as error:
        parser.error(str(error))

    channel = grpc.insecure_channel(args.listen)
    environment = environment_pb2_grpc.EnvironmentStub(channel)

    try:
        while True:
            individual = environment.Spawn(environment_pb2.SpawnRequest())
            phenome = decode_phenome(individual.phenome, landscape.n)
            individual_score = score(phenome, landscape)

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
