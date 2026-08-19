# The NPC Maker

The NPC Maker is a toolkit for building and interacting with simulated
environments populated by AI agents. It facilitates rapid development by
providing software interfaces that separate the components of an
artificial-life experiment. The NPC Maker also includes a collection of
ready-to-use tools and environments.

The interfaces are documented in these chapters:
* [Simulated Environments](/docs/environments.md)
* [Control Systems](/docs/controllers.md)
* [Individual Files](/docs/individuals.md)
* [Genetic Algorithms](/docs/genetics.md)
* [Evolutionary Algorithms](/docs/evolution.md)

The NPC Maker API is implemented in both python and rust. Components
(environments, controllers, genetic and evolutionary algorithms) are isolated
in separate processes so they can be implemented in different languages.

## Python API

* Installation: `python -m pip install --user npc-maker`
* Distribution: [PyPI](https://pypi.org/project/npc-maker/)
* Documentation: `pydoc npc_maker`

## Rust API

* Installation: `cargo add npc_maker`
* Distribution: [crates.io](https://crates.io/crates/npc_maker)
* Documentation: [docs.rs](https://docs.rs/npc_maker/latest/npc_maker)
