#!/usr/bin/env python3
"""Create and plot one random founder for the ARN XOR example."""

import subprocess
import sys
import tempfile
from pathlib import Path

from npc_maker.genetics import GeneticsClient
from npc_maker.individual import Individual


def main():
    repo = Path(__file__).resolve().parents[2]
    genetics = repo / "target" / "release" / "arn_genetics"
    controller = repo / "target" / "release" / "arn_controller"
    if not genetics.is_file() or not controller.is_file():
        raise SystemExit("Build ARN programs first: cargo build --release -p arn_controller -p arn_genetics")

    with GeneticsClient([str(genetics), "--inputs", "2", "--outputs", "1",
                         *sys.argv[1:]]) as genetics_client:
        individual = genetics_client.reproduce([])
        individual.body_type = "xor"
        individual.controller = [str(controller)]
        with tempfile.TemporaryDirectory(prefix="npc-arn-xor-plot-") as directory:
            path = individual.save(Path(directory) / "individuals")
            subprocess.run([sys.executable, str(repo / "examples" / "xor" / "plot.py"), str(path)],
                           check=True)


if __name__ == "__main__":
    main()
