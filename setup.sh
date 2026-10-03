#!/bin/sh
# One-shot setup: install a suitable Rust toolchain, then build and install npc_maker.
#
# The Rust logic lives in the Makefile (target `rust-toolchain`) so there is a single
# source of truth: it reads the minimum version from Cargo.toml, then uses an existing
# toolchain if new enough, else rustup, else apt (Debian/Ubuntu, using sudo if not root).
set -eu
cd "$(dirname "$0")"

make rust-toolchain
make install

echo
echo "Done. Activate the virtual environment with:  . venv/bin/activate"
