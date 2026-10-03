#!/bin/sh
# Ensure a Rust toolchain >= the workspace's minimum supported Rust version (MSRV) is
# available, installing one if necessary. Tries, in order:
#   1. a cargo that is already on PATH, if it is new enough
#   2. rustup (any platform)
#   3. apt's versioned packages rustc-X.Y / cargo-X.Y (Debian/Ubuntu; sudo if not root)
#
# Usage: scripts/ensure-rust.sh [MSRV]
#   MSRV defaults to `rust-version` from the top-level Cargo.toml.
#
# Note: a child process cannot change its caller's PATH. If the toolchain is installed by
# apt it lives in /usr/lib/rust-X.Y/bin, which the Makefile also adds to its own PATH.
set -eu
cd "$(dirname "$0")/.."

msrv=${1:-}
if [ -z "$msrv" ]; then
    msrv=$(sed -n 's/^[[:space:]]*rust-version[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' Cargo.toml)
fi
if [ -z "$msrv" ]; then
    echo "error: could not determine the minimum Rust version (rust-version in Cargo.toml)" >&2
    exit 1
fi

# Prefer apt's versioned toolchain over any older system-wide one, and pin rustup's
# cargo/rustc proxies to the MSRV toolchain (ignored by non-rustup toolchains).
PATH="/usr/lib/rust-$msrv/bin:$PATH"
RUSTUP_TOOLCHAIN=$msrv
export PATH RUSTUP_TOOLCHAIN

# Succeeds if a cargo on PATH exists and is >= $msrv.
rust_ok() {
    command -v cargo >/dev/null 2>&1 || return 1
    have=$(cargo --version 2>/dev/null | cut -d' ' -f2) || return 1
    [ -n "$have" ] || return 1
    [ "$(printf '%s\n%s\n' "$msrv" "$have" | sort -V | head -n1)" = "$msrv" ]
}

if rust_ok; then
    exit 0
fi

echo "Rust >= $msrv not found, installing it..."
if command -v rustup >/dev/null 2>&1; then
    rustup toolchain install "$msrv" --profile minimal
elif command -v apt-get >/dev/null 2>&1; then
    if [ "$(id -u)" = 0 ]; then sudo=; else sudo=sudo; fi
    $sudo apt-get update || true
    $sudo apt-get install -y "rustc-$msrv" "cargo-$msrv" || {
        echo "error: apt has no rustc-$msrv package on this system; install rustup from https://rustup.rs" >&2
        exit 1
    }
else
    echo "error: need Rust >= $msrv; install rustup from https://rustup.rs" >&2
    exit 1
fi

# The shell caches the location of commands it has already run (e.g. an older
# /usr/bin/cargo); forget that so the re-check sees the freshly installed one.
hash -r
if ! rust_ok; then
    echo "error: still no usable Rust >= $msrv after install" >&2
    exit 1
fi
