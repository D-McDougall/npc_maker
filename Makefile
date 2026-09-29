PROTO_DIR  	:= proto
PROTO_FILES := $(wildcard $(PROTO_DIR)/*.proto)
PYTHON_OUT 	:= python/npc_maker/_protobuf

.PHONY: all generate python rust clean

all: python rust package

python:
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
	@for f in $(PYTHON_OUT)/*_pb2_grpc.py; do \
		sed -i.bak -E \
			's/^import ([a-zA-Z0-9_]+)_pb2 as ([a-zA-Z0-9_]+)$$/from . import \1_pb2 as \2/' \
			"$$f"; \
		rm -f "$$f.bak"; \
	done

rust:
	cargo build --release

package:
	# Copy programs into python release
	cp -p target/release/npc-evo        python/npc_maker/programs/
	cp -p target/release/npc-maker      python/npc_maker/programs/
	cp -p programs/npc-maker.py         python/npc_maker/programs/npc_maker.py
	cp -p programs/npc-player.py        python/npc_maker/programs/npc_player.py
	# Build the python distributable
	python -m build --wheel
	python -m twine check dist/npc_maker-*.whl

clean:
	rm -rf build/ dist/ python/npc_maker.egg-info/ # Python build artifacts
	rm -rf $(PYTHON_OUT) 	  # protobuf
	rm -rf rust/src/generated # protobuf
	cargo clean
