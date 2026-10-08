from pathlib import Path
import os
import sys

def _run_bundled_binary(file_name):
    if os.name == "nt":
        file_name += ".exe"
    file_path = Path(__file__).parent.joinpath(file_name)
    os.execv(file_path, [str(file_path), *sys.argv[1:]])

def npc_evo():
    _run_bundled_binary("npc-evo")

def npc_server():
    _run_bundled_binary("npc-server")
