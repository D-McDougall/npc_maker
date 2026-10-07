"""
Test environment for npc-server integration tests.

Connects to the Environment service supplied on the command line and performs a
fixed number of random spawn, mate, score, telemetry, and death operations.

The environment also acts as a client of the Diagnostics service (which is
served on the same address) and keeps its own model of what the diagnostics
should report. After every operation it checks the server's diagnostics against
that model. The outcome is written to the file given by --result, as JSON with
an "ok" flag, so that the test can tell whether the checks passed.
"""

import argparse
import json
import math
import os
import random
import traceback

import grpc

from npc_maker import diagnostics_pb2, diagnostics_pb2_grpc
from npc_maker import environment_pb2, environment_pb2_grpc

BODY_TYPE = "test"  # Must match the organism in test_server.py


class Model:
    """
    Expected diagnostics for the only organism, as seen from the environment.
    """
    def __init__(self):
        self.counts = {
            "Spawn": 0, "Mate": 0, "Score": 0, "Telemetry": 0, "Death": 0}
        self.living = 0
        self.max_score = -math.inf


def check(diagnostics, model):
    """
    Compare the server's diagnostics to the model. Raises AssertionError.
    """
    # The body type may be omitted, since there is only one organism.
    for body_type in (BODY_TYPE, ""):
        organism = diagnostics_pb2.Organism(body_type=body_type)

        for call in model.counts:
            rpc = getattr(diagnostics, f"{call}Count")
            actual = rpc(organism).count
            assert actual == model.counts[call], (
                f"{call}Count(body_type={body_type!r}): "
                f"expected {model.counts[call]}, got {actual}")

        actual = diagnostics.LivingCount(organism).count
        assert actual == model.living, (
            f"LivingCount(body_type={body_type!r}): "
            f"expected {model.living}, got {actual}")

        actual = diagnostics.MaximumScore(organism).score
        assert actual == model.max_score, (
            f"MaximumScore(body_type={body_type!r}): "
            f"expected {model.max_score}, got {actual}")


def check_unknown_body_type(diagnostics):
    """
    Every diagnostic must reject a body type which is not in the experiment.
    """
    organism = diagnostics_pb2.Organism(body_type="no-such-body-type")
    for rpc in (diagnostics.LivingCount, diagnostics.SpawnCount,
                diagnostics.MateCount, diagnostics.ScoreCount,
                diagnostics.TelemetryCount, diagnostics.DeathCount,
                diagnostics.MaximumScore):
        try:
            rpc(organism)
        except grpc.RpcError as error:
            assert error.code() == grpc.StatusCode.INVALID_ARGUMENT, (
                f"unknown body type: expected INVALID_ARGUMENT, got {error}")
        else:
            raise AssertionError("unknown body type was accepted")


def run(address, operations):
    channel = grpc.insecure_channel(address)
    environment = environment_pb2_grpc.EnvironmentStub(channel)
    diagnostics = diagnostics_pb2_grpc.DiagnosticsStub(channel)
    model = Model()
    living = {}

    def spawn():
        model.counts["Spawn"] += 1
        individual = environment.Spawn(environment_pb2.SpawnRequest())
        living[individual.metadata.name] = individual
        model.living += 1

    def mate():
        model.counts["Mate"] += 1
        parents = [
            random.choice(list(living.keys()))
            for _ in range(random.randint(1, 3))
        ]
        individual = environment.Mate(environment_pb2.MateRequest(parents=parents))
        living[individual.metadata.name] = individual
        model.living += 1

    def score(value=None):
        model.counts["Score"] += 1
        individual = random.choice(list(living.values()))
        if value is None:
            value = float(random.randint(-10, 10))  # Includes negative scores
        environment.Score(
            environment_pb2.ScoreRequest(name=individual.metadata.name, score=value))
        if value > model.max_score:
            model.max_score = value

    def telemetry():
        model.counts["Telemetry"] += 1
        individual = random.choice(list(living.values()))
        environment.Telemetry(
            environment_pb2.TelemetryRequest(
                name=individual.metadata.name,
                data=[
                    environment_pb2.KeyValue(
                        key=random.choice("ABC"),
                        value=random.choice("123"),
                    )
                ],
            )
        )

    def death():
        model.counts["Death"] += 1
        individual = random.choice(list(living.values()))
        environment.Death(
            environment_pb2.DeathRequest(name=individual.metadata.name))
        del living[individual.metadata.name]
        model.living -= 1

    operation_choices = [spawn, mate, score, telemetry, death]

    try:
        # Everything starts at zero, and there are no scores yet.
        check(diagnostics, model)
        check_unknown_body_type(diagnostics)

        # The first score is negative, to check that the maximum is not
        # clamped by some initial value. Later scores are random, and are
        # very likely to exceed this one, so it must be checked explicitly.
        spawn()
        check(diagnostics, model)
        score(-5.0)
        check(diagnostics, model)
        assert model.max_score == -5.0

        # A NaN score is counted, but must not disturb the maximum.
        score(float("nan"))
        check(diagnostics, model)
        assert model.max_score == -5.0

        for _ in range(operations):
            # There is no valid operation other than spawn when the environment
            # is empty. Once an individual exists, choose uniformly from all
            # five operations.
            operation = spawn if not living else random.choice(operation_choices)
            operation()
            check(diagnostics, model)

        return {
            "ok": True,
            "operations": operations,
            "counts": model.counts,
            "living": model.living,
            "max_score": model.max_score,
        }
    finally:
        channel.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen", required=True,
                        help="Environment service host:port (passed by npc-server)")
    parser.add_argument("--result", help="write the JSON outcome to this file")
    parser.add_argument("--operations", type=int, default=1000,
                        help="number of random operations to perform")
    args = parser.parse_args()

    try:
        result = run(args.listen, args.operations)
    except Exception:
        result = {"ok": False, "error": traceback.format_exc()}

    if args.result:
        # Write atomically so the test never reads a partial file.
        temporary = args.result + ".tmp"
        with open(temporary, "wt", encoding="utf-8") as file:
            json.dump(result, file)
        os.replace(temporary, args.result)

    if not result["ok"]:
        print(result["error"], flush=True)
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
