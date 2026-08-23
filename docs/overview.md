# Project Overview #

The NPC Maker is a modular framework for artificial-life experiments.
Each component is isolated in its own computer process with a well defined
interface for interacting with the larger system. Components communicate
over their standard input, output, and error channels. Messages are encoded
in UTF-8 unless otherwise stated. Structured data is transmitted in JSON.
This design is easy to implement and debug.

The NPC Maker API is implemented in both python and rust. Components
implemented in different languages communicate via the NPC Maker interfaces.

## System Organization ##

![System Organization](images/system_organization.svg)

Artificial-life experiments are split into 5 component types:
* **Router Programs** initialize and communicate between other components.
* **Simulated Environments** are self-contained worlds populated by AI agents.
* **Control Systems** are the brains of the agents.
* **Evolutionary Algorithms** decide which agents to reproduce.
* **Genetic Algorithms** reproduce the parameters for control systems.

Each of these component executes in its own computer process.
Some components create and manage other components,
and they may contain multiple instances of the contained component.
In the diagram above: arrows indicate parent-child relationships,
which are also one-to-many relationships.

## Interface Specifications ##

The NPC Maker interfaces are documented in the following chapters:
* [Simulated Environments](/docs/environments.md)
* [Control Systems](/docs/controllers.md)
* [Individual Files](/docs/individuals.md)
* [Genetic Algorithms](/docs/genetics.md)
* [Evolutionary Algorithms](/docs/evolution.md)

### Standard Error Channel ###

The standard error channel is reserved for unformatted diagnostic and error
messages. Functions `eprint()` (python) and `eprintln!()` (rust) are provided
for convenience. By default processes inherit standard error from their
parent process, which should in turn forward its standard error to the user
or a log file as appropriate.

In the event that any of the three standard I/O channels closes or emits an
error, then all parties should assume the other party has died and act
accordingly. To signal program termination without deadlocking: close both
standard input and output channels.

## Directory Structure ##

* `/docs/` Interface Specifications
* `/python/` Python language API for the NPC Maker interfaces
* `/rust/` Rust language API for the NPC Maker interfaces
* `/examples/env/` Example environments
* `/examples/ctrl/` Example controllers
* `/examples/evo/` Example evolutionary algorithms
* `/examples/gen/` Example genetic algorithms
