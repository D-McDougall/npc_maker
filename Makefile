PROTO_DIR   := proto
PROTO_FILES := $(wildcard $(PROTO_DIR)/*.proto)
PYTHON_OUT  := python/npc_maker/
PYTHON      := venv/bin/python3
PIP         := venv/bin/pip3
PYTEST      := venv/bin/pytest

.PHONY: all venv python rust-toolchain rust package install clean

all: package

venv:
	test -d venv || python3 -m venv venv # Create venv if it doesn't exist
	$(PIP) install -r requirements.txt
	$(PIP) install build twine pytest # Python development dependencies

python: venv
	# Run protobuf
	$(PYTHON) -m grpc_tools.protoc \
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

rust:
	cargo build --release

package: python rust
	# Copy programs into python release
	cp -p target/release/npc-evo        python/npc_maker/programs/
	cp -p target/release/npc-server     python/npc_maker/programs/
	# Replace dash with underscore in file name
	cp -p programs/npc-server/npc-server.py     python/npc_maker/programs/npc_server.py
	cp -p programs/npc-player.py        		python/npc_maker/programs/npc_player.py
	# Build the python distributable
	$(PYTHON) -m build --wheel
	$(PYTHON) -m twine check dist/npc_maker-*.whl

install: package
	$(PIP) install --force-reinstall dist/npc_maker-*.whl

test: install
	cargo test
	$(PYTEST) python
	$(PYTEST) tests

clean:
	rm -rf $(PYTHON_OUT)/*_pb2.py 	  	# protobuf
	rm -rf $(PYTHON_OUT)/*_pb2_grpc.py 	# protobuf
	rm -rf rust/src/generated 			# protobuf
	rm -rf build # python
	rm -rf dist  # python
	rm  -rf python/npc_maker.egg-info # python
	cargo clean # rust
