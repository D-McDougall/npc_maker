#!/usr/bin/env python3
"""
Run the vector optimization experiment.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def test_vector(dimension, seed):

    environment = Path(__file__).with_name("vector_environment.py")
    genetics    = Path(__file__).with_name("vector_genetics.py")

    config = {
        "name": "vector test",
        "description": f"Vector optimization experiment ({dimension}, {seed})",
        "environment": [
            sys.executable,
            str(environment),
            str(dimension),
            str(seed),
        ],
        "organisms": [
            {
                "body_type": "vector",
                "genetics": [
                    sys.executable,
                    str(genetics),
                    str(dimension),
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

        return subprocess.run([
            "npc-server.py",
            str(config_file),
            str(directory / "server-data"),
            "--verbose",
        ]).returncode


if __name__ == "__main__":
    sys.exit(test_vector(2, 0x5EED))
