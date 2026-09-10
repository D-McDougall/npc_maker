# Router Program #

The router program orchestrates all other components of the NPC Maker.

## Requirements ##

1) The router program is the first program to execute, and performs all
system-wide initialization tasks.

2) The router instantiates all: environments, evolutionary algorithms, and genetic
algorithms.

3) The router program keeps a record of every living individual. The
environment API implementation updates these records as the environment sends
information. These messages are "Telemetry" and "Score".

4) The router program passes messages between environments, evolutionary algorithms,
and genetic algorithms. These messages are "Spawn", "Mate", and "Death".


## Sequence Diagrams ##

### Spawn Sequence ###

This sequence diagram shows the message and file transmissions that occur when
the environment creates a new individual without specifying parents.


### Mate Sequence ###

This sequence diagram shows the message and file transmissions that occur when
living individuals procreate in an environment.


### Death Sequence ###

This sequence diagram shows the message and file transmissions that occur when
an individual dies.


### Individual Life Cycle ###

This sequence diagram shows the life cycle of an individual as it is created,
simulated, and dies.


## Experiment Specification ##

To facilitate reproducible experimentation, the parameters for running the NPC
Maker are stored in "**Experiment Files**", which have the ".exp" file
extension. Experiment files are encoded in UTF-8 and contain a single JSON
Object with the following attributes. Leading and trailing whitespace is
permitted.

| Attribute | JSON Type | Default Value | Description |
| :-------- | :-------: | :------------ | :---------- |
| `"name"`        | String | Required | Name of the experiment, should be universally unique |
| `"description"` | String | `""`     | User facing documentation message |
| `"computers"`   | List of Computers | "localhost" |  |
| `"environment"` | List of Strings   | Required    |  |
| `"lifeforms"`   | List of Lifeforms | Required    |  |
| Unspecified     | Any |  | This object may include extra attributes |

### Computer Objects ###

The "**computers**" attribute is an array of Computer objects, which specify
available computational resources. Computer objects have the following
fields, and may contain additional fields.

| Attribute | JSON Type | Default Value | Description |
| :-------- | :-------: | :------------ | :---------- |
| `"host"`  | String | Required |  |
| `"port"`  | Number | Required |  |
| `"pass"`  | String |  |  |



### Life-form Objects ###

The "**lifeforms**" attribute is an array of Lifeform objects, which attach a
control system, evolutionary algorithm, and genetic algorithm to each body
type. Every body type in the environment specification must have a
corresponding entry here. Extra entries are ignored.

| Attribute | JSON Type | Default Value | Description |
| :-------- | :-------: | :------------ | :---------- |
| `"body_type"`  | String | Required | Identifies a body-type in the environment specification |
| `"controller"` | Array of Strings | Required | Command line invocation for creating controller instances |
| `"evolution"`  | Array of Strings | `[]` | Command line invocation for creating evolution program instances |
| `"genetics"`   | Array of Strings | Required | Command line invocation for creating genetic program instances |


### Schematic Diagram of Experiment Specification File

