PROTO_DIR  	:= proto
PROTO_FILES := $(wildcard $(PROTO_DIR)/*.proto)
PYTHON_OUT 	:= python/npc_maker/_protobuf

# Minimum supported Rust version. Cargo.toml is the single source of truth.
RUST_MSRV := $(shell sed -n 's/^[[:space:]]*rust-version[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' Cargo.toml)

# Debian/Ubuntu install versioned toolchains here, which is not on PATH by default.
# (scripts/ensure-rust.sh uses the same location when it installs via apt.)
RUST_APT_BIN := /usr/lib/rust-$(RUST_MSRV)/bin

# Pin rustup's cargo/rustc proxies to the MSRV toolchain. Ignored by non-rustup toolchains.
export RUSTUP_TOOLCHAIN := $(RUST_MSRV)

# Activate the virtual environment, and prefer the apt-installed Rust over any older system one.
export PATH := venv/bin:$(RUST_APT_BIN):$(PATH)

.PHONY: all venv python rust-toolchain rust package install clean

all: python rust package

venv:
	test -d venv || python3 -m venv venv # Create venv if it doesn't exist
	pip install -r requirements.txt
	pip install build twine

python: venv
	# Setup python module for protobuf generated file
	mkdir -p $(PYTHON_OUT)
	touch $(PYTHON_OUT)/__init__.py
	echo "*" > $(PYTHON_OUT)/.gitignore
	# Run protobuf
	python -m grpc_tools.protoc \
		-I$(PROTO_DIR) \
		--python_out=$(PYTHON_OUT) \
		--grpc_python_out=$(PYTHON_OUT) \
		$(PROTO_FILES)
	# Fixup generated files: make absolute import statement into relative
	@for f in $(PYTHON_OUT)/*_pb2.py $(PYTHON_OUT)/*_pb2_grpc.py; do \
		sed -i.bak -E \
			's/^import ([a-zA-Z0-9_]+)_pb2 as ([a-zA-Z0-9_]+)$$/from . import \1_pb2 as \2/' \
			"$$f"; \
		rm -f "$$f.bak"; \
	done

# Ensure a Rust toolchain >= RUST_MSRV is available (installing one if needed).
rust-toolchain:
	./scripts/ensure-rust.sh $(RUST_MSRV)

rust: rust-toolchain
	cargo build --release

package: venv python rust
	# Copy programs into python release
	cp -p target/release/npc-evo        python/npc_maker/programs/
	cp -p target/release/npc-server     python/npc_maker/programs/
	# Replace dash with underscore in file name
	cp -p programs/npc-server/npc-server.py     python/npc_maker/programs/npc_server.py
	cp -p programs/npc-player.py        		python/npc_maker/programs/npc_player.py
	# Build the python distributable
	python -m build --wheel
	python -m twine check dist/npc_maker-*.whl

install: venv package
	pip install --force-reinstall dist/npc_maker-*.whl

clean:
	rm -rf $(PYTHON_OUT) 	  # protobuf
	rm -rf rust/src/generated # protobuf
	rm -rf build # python
	rm -rf dist  # python
	rm  -rf python/npc_maker.egg-info # python
	cargo clean # rust
