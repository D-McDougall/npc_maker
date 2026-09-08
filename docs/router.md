# Router Program #

The router program orchestrates all other components of the NPC Maker.

## Responsibilities ##

1) The router program is the first program to execute, and performs all
system-wide initialization tasks.

2) The router instantiates environments, evolutionary algorithms, and genetic
algorithms.

3) The router program keeps a record of every living individual. The
environment API implementation updates these records as the environment sends
information.

3) This program routes messages between environments and evolutionary algorithms:
    * Send "spawn" and "death" messages from environments to evolutionary algorithms.
    * Collect 


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
| `"computers"`   |  |  |  |
| `"environment"` | List of Strings | Required |  |
| `"lifeforms"`   | List of Lifeforms |  |  |
| Unspecified     | Any |  | This object may include extra attributes |


### Lifeform Objects ###

| Attribute | JSON Type | Default Value | Description |
| :-------- | :-------: | :------------ | :---------- |
| `"body_type"` |  |  |  |
| `"controller"` |  |  |  |
| `"evolution"` |  |  |  |
| `"genetics"` |  |  |  |




