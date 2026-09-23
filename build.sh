#!/usr/bin/env bash
set -e # exit on error
set -x # echo all commands

# Clean house before every build
rm -rf  build/  dist/  npc_maker.egg-info/
# rm -rf  target/

# Build the rust programs
cargo build --release

# Copy all programs into the python release
cp -p target/release/npc-evo        python/npc_maker/programs/
cp -p target/release/npc-maker      python/npc_maker/programs/
cp -p programs/npc-maker.py         python/npc_maker/programs/npc_maker.py
cp -p programs/npc-player.py        python/npc_maker/programs/npc_player.py

# Build the python distributable
python -m build --wheel
python -m twine check dist/npc_maker-*.whl

echo "BUILD COMPLETE"
