#!/usr/bin/env python3
"""Run the vector optimization experiment."""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dimension",
        type=int,
        help="Number of dimensions in the target vector",
    )
    parser.add_argument(
        "seed",
        type=int,
        help="Seed used to generate the target vector",
    )
    args = parser.parse_args()

    if args.dimension <= 0:
        parser.error("dimension must be greater than zero")

    root = Path(__file__).resolve().parents[2]
    environment = root / "tests" / "vector" / "env.py"
    genetics = root / "tests" / "vector" / "vector_genetics.py"

    config = {
        "name": "vector test",
        "description": "Minimal vector optimization experiment",
        "environment": [
            sys.executable,
            str(environment),
            str(args.dimension),
            str(args.seed),
        ],
        "organisms": [
            {
                "body_type": "vector",
                "genetics": [
                    sys.executable,
                    str(genetics),
                    str(args.dimension),
                ],
                # Evolution is intentionally omitted. The NPC server will
                # request founder individuals from the genetics service.
            }
        ],
    }

    with tempfile.TemporaryDirectory(prefix="npc-vector-") as directory:
        directory = Path(directory)
        config_file = directory / "experiment.json"
        config_file.write_text(
            json.dumps(config, indent=2),
            encoding="utf-8",
        )

        return subprocess.run(
            [
                "npc-server.py",
                str(config_file),
                str(directory / "server-data"),
            ]
        ).returncode


if __name__ == "__main__":
    sys.exit(main())
