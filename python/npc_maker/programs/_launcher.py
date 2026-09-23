from pathlib import Path
import os
import subprocess
import sys

def _run_bundled_binary(file_name):
    if os.name == "nt":
        file_name += ".exe"
    file_path = Path(__file__).parent.joinpath(file_name)
    process = subprocess.run([file_path] + sys.argv[1:])
    sys.exit(process.returncode)

def npc_evo():
    _run_bundled_binary("npc-evo")

def npc_maker():
    _run_bundled_binary("npc-maker")
