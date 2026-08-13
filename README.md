# The NPC Maker

The NPC Maker is a framework for interacting with simulated environments that
contain AI agents. It defines software interfaces that separate environments
from their surrounding concerns, and provides APIs for using them.
The NPC Maker also provides a collection of ready-to-use tools and environments.

The interfaces are documented in these chapters:
* [Simulated Environments](/docs/environments.md)
* [Control Systems](/docs/controllers.md)
* [Individuals' Files](/docs/individuals.md)
* [Genetic Algorithms](/docs/genetics.md)
* [Evolutionary Algorithms](/docs/evolution.md)

The NPC Maker's API is implemented for both python and rust. Components
(environments, controllers, genetic and evolutionary algorithms) are isolated
in separate processes so they can be implemented in different languages.

## Python API

* `python -m pip install --user npc-maker`
* [PyPI](https://pypi.org/project/npc-maker/)

## Rust API

* `cargo add npc_maker`
* [crates.io](https://crates.io/crates/npc_maker)
* [docs.rs](https://docs.rs/crate/npc_maker/0.1.0)
