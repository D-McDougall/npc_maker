# The NPC Maker #

The NPC Maker is a toolkit for building and interacting with simulated
environments populated by AI agents. It facilitates rapid and collaborative
development by providing software interfaces that decouple the components of
an artificial-life experiment and allow independently developed components to
work together. The NPC Maker also includes a collection of ready-to-use tools
and environments.

## System Organization ##

![System Organization](docs/diagrams/system_organization.svg)

The NPC Maker is structured around remote procedure calls (gRPC) defined using
the Protobuf interface description language.

The NPC Maker is split into five separate micro-service programs:

* **Environments** are self-contained worlds populated by AI organisms.
* **Controllers** are the brains of the organisms.
* **Evolutionary Algorithms** decide which organisms to reproduce.
* **Genetic Algorithms** decide how organisms reproduce their parameters.
* **Server Programs** route communications between the other services.

## [Documentation 🔗](docs/docs.md)

## Python API ##

* Installation: `python -m pip install --user npc-maker`
* Distribution: [PyPI](https://pypi.org/project/npc-maker/)
* Documentation: `pydoc npc_maker`

## Rust API ##

* Installation: `cargo add npc_maker`
* Distribution: [crates.io](https://crates.io/crates/npc_maker)
* Documentation: [docs.rs](https://docs.rs/npc_maker/latest/npc_maker)
