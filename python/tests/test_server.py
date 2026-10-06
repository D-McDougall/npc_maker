"""
Smoke test for npc-server.
"""

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from npc_maker.individual import Individual


def test_server():
    with tempfile.TemporaryDirectory() as directory:
        directory = Path(directory)
        population = directory / "population"
        population.mkdir()

        # Create a small replay population for npc-player.
        for score in range(3):
            individual = Individual()
            individual.score = score
            individual.save(population)

        environment = Path(__file__).with_name("environment.py")
        config = {
            "name": "npc-server smoke test",
            "environment": [
                sys.executable,
                str(environment),
            ],
            "organisms": [
                {
                    "body_type": "test",
                    "evolution": [
                        "npc-player",
                        str(population),
                        "random",
                    ],
                },
            ],
        }

        config_file = directory / "experiment.json"
        config_file.write_text(json.dumps(config), encoding="utf-8")

        process = subprocess.Popen(
            ["npc-server.py", str(config_file), str(directory / "server-data")],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        stdout = b""
        stderr = b""

        try:
            time.sleep(10)

            if process.poll() is not None:
                stdout, stderr = process.communicate()
                raise AssertionError(
                    "npc-server exited unexpectedly "
                    f"with status {process.returncode}:\n"
                    f"stdout:\n{stdout.decode()}\n"
                    f"stderr:\n{stderr.decode()}"
                )
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                stdout, stderr = process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()

            if stderr:
                raise AssertionError(
                    "npc-server wrote to stderr:\n"
                    f"{stderr.decode()}"
                )

if __name__ == "__main__":
    test_server()
