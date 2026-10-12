#!/usr/bin/env python3
"""Run the XOR environment with the ARN controller.

Build the ARN programs first with
``cargo build --release -p arn_controller -p arn_genetics``.
Then run this script from the repository root (or invoke it by path). The
experiment runs until interrupted with Ctrl-C.
"""

import argparse
import json
import tempfile
import time
from pathlib import Path

from npc_maker.diagnostics import Diagnostics


BODY_TYPE = "xor"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--duration", type=float, default=0,
                        help="stop after this many seconds (default: run until Ctrl-C)")
    parser.add_argument("--temperature", type=float, default=1.0,
                        help="ARN controller temperature (default: %(default)s)")
    args = parser.parse_args()
    if args.duration < 0:
        parser.error("duration must not be negative")
    if args.temperature < 0:
        parser.error("temperature must not be negative")

    here = Path(__file__).resolve().parent
    repo = here.parents[1]
    controller = repo / "target" / "release" / "arn_controller"
    genetics = repo / "target" / "release" / "arn_genetics"
    missing = [str(program) for program in (controller, genetics)
               if not program.is_file()]
    if missing:
        parser.error("ARN programs are not built; run: cargo build --release "
                     "-p arn_controller -p arn_genetics")

    config = {
        "name": "XOR with the ARN controller",
        # "environment": [sys.executable, str(repo / "examples" / "xor" / "xor.py")],
        "environment": [str(repo / "target" / "release" / "xor")],
        "evolution": "npc-evo -p 1000 -r oldest -s ranked-exponential=100 --parents 2".split(),
        "organisms": [{
            "body_type": BODY_TYPE,
            "genetics": [str(genetics), "--inputs", "2", "--outputs", "1",
                         "--duplications", "10",
                         "--temperature", str(args.temperature)],
            "controller": [str(controller), "--temperature", str(args.temperature)],
        }],
    }

    with tempfile.TemporaryDirectory(prefix="npc-arn-xor-") as directory:
        directory = Path(directory)
        config_path = directory / "experiment.json"
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        with Diagnostics(config_path, directory / "server-data", server_program='npc-server', workers=20) as diagnostics:
            print(f"Starting npc-server on {diagnostics.address}", flush=True)
            started = time.monotonic()
            next_report = 0.0
            try:
                while (args.duration == 0 or
                       time.monotonic() - started < args.duration):
                    deaths = diagnostics.death_count(BODY_TYPE)
                    best = diagnostics.maximum_score(BODY_TYPE)
                    if time.monotonic() >= next_report:
                        print(f"{deaths} evaluations, maximum score {best:.6f}", flush=True)
                        next_report = time.monotonic() + 1.0
                    time.sleep(0.1)
            except KeyboardInterrupt:
                pass


if __name__ == "__main__":
    main()
