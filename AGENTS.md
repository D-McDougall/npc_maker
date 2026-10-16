# Development Guide

## Repository map

- `proto/` defines the public Protobuf/gRPC contracts shared by every component.
- `rust/` is the `npc_maker` Rust library. Its build script generates Rust
  bindings from `proto/` using a vendored `protoc`.
- `programs/npc-evo/` and `programs/npc-server/` are Rust command-line
  services included in the distributable Python package.
- `programs/npc-player/py` and `programs/npc-server/npc-server.py` are Python
  command-line services included in the distributable Python package.
- `python/npc_maker/` is the Python API and process-launching wrappers.
- `python/tests/` contains the main Python test suite.
  These tests also exercise the rust command-line programs.
- `examples/` contains runnable integrations and example-specific tests;
  `examples/nk/` includes tests that can be long-running.
- `docs/` contains generated protocol documentation and architecture diagrams.

## Setup and common commands

- Use Python 3.12 or newer and Rust 1.91 or newer.
- Run `make venv` to create `venv/` and install Python/runtime development
  dependencies.
- Run `make python` after changing files in `proto/` to regenerate the Python
  bindings. These generated `*_pb2.py` and `*_pb2_grpc.py` files are ignored;
  do not hand-edit them.
- Run `cargo build --workspace` for a fast Rust debug build, or `make rust` for
  the release binaries used when building the Python distribution.
- Run `make package` to regenerate Python bindings, build release binaries,
  copy the command-line programs into the package, and validate the wheel.
- Run the full verification path with `make test`. It packages and installs the
  project, then runs `cargo test --workspace`, `pytest python`, and the NK and
  ARN example tests. For focused work, use `cargo test -p <crate>` or
  `PATH="/home/ai/venv/bin:$PATH" venv/bin/pytest python/tests/test_<area>.py`.
- Run `cargo fmt` before submitting Rust changes. Formatting
  follows `rustfmt.toml` (120-column maximum). There is no configured Python
  formatter or linter; follow the surrounding style.

## Change guidelines

- Treat `proto/` as the compatibility boundary. Keep field numbers stable,
  avoid making changes where possible, update both language implementations,
  regenerate the Python bindings, and refresh `docs/docs.md` with `make docs`
  when protocol documentation changes.
- Keep Python public APIs documented with docstrings and type annotations where
  the neighboring code uses them. Add or update pytest coverage alongside
  behavioral changes.
  * Python documentation is written in plain english, not markdown.
- Keep Rust public APIs documented and add unit/integration coverage with
  relevant changes. Avoid adding a system `protoc` prerequisite: `rust/build.rs`
  intentionally uses `protoc-bin-vendored`.
- Preserve the service boundary: environments, controllers, evolution, and
  genetics communicate through the gRPC contracts rather than direct
  cross-component dependencies.
- Package-facing changes may need both `pyproject.toml` and the Makefile
  packaging flow reviewed. The published Python package bundles the Rust
  `npc-evo` and `npc-server` binaries plus the Python player/server launchers.

## Generated and local artifacts

- Do not commit `venv/`, `target/`, `build/`, `dist/`, egg metadata, generated
  Python protobuf bindings, or bundled program copies under
  `python/npc_maker/programs/`.
- `Cargo.lock` is intentionally ignored for this library-oriented workspace.
- Do not use `make clean` casually: it removes generated bindings, build
  artifacts, package output, and the entire Cargo target directory.

## Before opening a change

1. Work in a feature branch.
2. Run the narrow tests for the area changed; run `make test` for cross-language,
   protocol, packaging, or release-impacting changes.
3. Run Rust formatting checks for Rust edits.
4. Check `git diff` and `git status`; retain and do not overwrite unrelated local
   changes.
