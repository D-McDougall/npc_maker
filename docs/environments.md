# The Environment Interface #

This chapter describes the interface between evolution programs and environment programs.
The word "**environment**" refers to a self contained simulated world and
everything in it, including all of the living bodies and their control systems. 
The NPC Maker defines a standard interface for interacting with arbitrary environments.

Environments always execute in a different computer process than the main
program of the NPC Maker framework, which is referred to as
the "**evolution**" program. This separation has many advantages, chiefly that
users can create and control environments using the programming language of
their choice.

Environments have two parts: a static description and an executable program.
The static description contains all of the information needed to configure and
run the environment. The executable program does the actual work of setting up
and running the environment.


## Environment Specification ##

The environment specification totally describes a single distinct and self
contained environment. It is a JSON file encoded in UTF-8. It should use
the ".env" file extension although this is not required. The file contains a
single JSON object. The following table shows all of the expected attributes of
the object. 

| Attribute | JSON Type | Default Value | Description |
| :-------- | :-------: | :------------ | :---------- |
| `"name"`   | String | Required | Name of the environment, should be universally unique |
| `"path"`   | String | Required | Filesystem path of the environment's executable program, relative to this file |
| `"spec"`   | String | Automatic | Filesystem path of the environment specification (this file) |
| `"body_types"` | Array of BodySpecs | Required | Specification for each type of organism |
| `"settings"` | Array of Settings | `[]` | Settings menu items for customizing the environment |
| `"description"` | String | `""` | User facing documentation message |
| Unspecified | Any |  | Environments may include extra information |

Extra attributes are simply ignored and so you can store miscellaneous data in
this file. This file is given to the environment program as a command line
argument, which allows one environment program to be reconfigured for multiple
different scenarios.

The "**body_types**" attribute is an array of body specification objects, which
each describe the interface between this environment and a type of organism.
Environments may contain multiple body types. The following table shows all of
the expected attributes of body specification objects. Extra attributes are
simply ignored, and authors are encouraged to include extra information about
body types here.

| Attribute | JSON Type | Default Value | Description |
| :-------- | :-------: | :------------ | :---------- |
| `"name"` | String | Required | Name of the body_type, must be unique within the environment |
| `"description"` | String | `""` | User facing documentation message |
| `"sensors"` | Array of Interfaces | Required | Sensory inputs to this agent's body |
| `"motors"` | Array of Interfaces | Required | Motor outputs from this agent's body |
| Unspecified | Any |  | Environments may include extra information about this body_type |

The "**sensors**" and "**motors**" arrays describe the connections between an
agent's body in the environment and its control system. Both of these
attributes are arrays of interface objects. Each interface object has two
unique identifiers: a name and an ID number. The ID number identifies the
interface for the controller and within the genome; and the name identifies the
interface to the user and within the environment. The following table shows all
of the expected attributes of interface objects. Again, extra attributes are
simply ignored.

| Attribute | JSON Type | Default Value | Description |
| :-------- | :-------: | :------------ | :---------- |
| `"id"` | Number | Required | Controller facing name for this port, must be unique within its array |
| `"name"` | String | Required | User facing name for this port, must be unique within its array |
| `"description"` | String | `""` | User facing documentation message |
| Unspecified | Any |  | Environments may include extra information about this interface |

The environment specification's "**settings**" attribute describes the command
line arguments of the environment program. The user must finalize their
settings before starting the environment program. The following table shows all
of the expected attributes of settings objects, and extra attributes are *not*
allowed.

| Attribute | JSON Type | Default Value | Description |
| :-------- | :-------: | :------------ | :---------- |
| `"name"`        | String | Required | Name of this settings menu item, must be unique within the environment |
| `"description"` | String | `""`     | User facing documentation message |
| `"type"` | String | Required | Data type of this settings item |
| `"default"` |  | Required | Value to use if this setting is missing |
| `"minimum"` | Number | Required for Real and Integer types | Lower bound on the range of allowable values, inclusive |
| `"maximum"` | Number | Required for Real and Integer types | Upper bound on the range of allowable values, inclusive |
| `"values"`  | Array of Strings | Required for Enumeration type | Names of all of the variants of the enumeration |

<div style="columns: 2">

The setting's "**type**" attribute must be one of the following strings or abbreviated aliases:

| Data Type       | Abbreviation |
| :--------       | :----------- |
| `"Real"`        | `"float"`    |
| `"Integer"`     | `"int"`      |
| `"Boolean"`     | `"bool"`     |
| `"Enumeration"` | `"enum"`     |
| `"String"`      | `"str"`      |

</div>


### Schematic Diagram of the Environment Specification ###

![Schematic Diagram](images/environment_specification.svg)


## Environment Program ##

Environments are implemented as stand-alone programs.  
They are called with the following command line arguments:

0) The name of the program being executed.  
   This is a standard argument for all computer programs.  

1) The filesystem path of the environment specification.

2) Either the word "graphical" or the word "headless" to indicate whether or not
the environment should show graphical output to the user. This is useful for
diagnostics and demonstrations.

3) The remaining arguments are the user's settings, as `name` `value` pairs.
These are described in the "settings" attribute of the environment
specification.
   * The settings may be in any order. 
   * Missing settings are filled in with their default values. 
   * Unexpected settings may be rejected. 


## Environment Protocol ##

The evolution program communicates with the environment over the environment's
`stdin`, `stdout` and `stderr` channels. When `stdin` closes the environment
should exit.


### Standard Input Channel ###

The evolution program sends new individuals to the environment. The environment
must request new individuals; new individuals will not be sent unsolicited.

Individuals are transmitted in two parts. First metadata is encoded in UTF-8
JSON and written as a single line. Then the genome is written as a binary blob,
whose length is stored in the metadata. The metadata contains the following
information about the new individual:

| Attribute | JSON Type | Description |
| :-------- | :-------: | :---------- |
| `"name"`        | String | Each individual is assigned a UUID for future reference |
| `"body_type"`   | String | Name of the body_type that this individual is born into |
| `"parents"`     | List of Strings | The UUIDs of the parents. May be empty, especially if created by a "New" request |
| `"controller"`  | List of Strings | Command line invocation of the controller program |
| `"genome"`      | Number | Number of bytes in the genome |


### Standard Output Channel ###

The environment sends commands and data to the evolution program. Each
message occupies exactly one line, and is encoded in the UTF-8 JSON format.
Words in ALLCAPS are placeholders for runtime data.  

| Message Type | Message Format | Description |
| :----------- | :------------- | :---------- |
| Spawn | `{"Spawn":"BODY_TYPE"}\n` | Request a new individual from the evolutionary algorithm |
| Mate  | `{"Mate":["UUID","UUID"]}\n` | Request a new individual by mating individuals together. This requires at least one parent. This accepts more than two parents. All parents must be alive, in this environment, and having the same body_type |
| Score | `{"Score":"VALUE","name":"UUID"}\n` | Report the score or reproductive fitness of a living individual |
| Telemetry | `{"Telemetry":{"KEY":"VALUE"},"name":"UUID"}\n` | The environment associates some extra information with a living individual. The info is kept alongside the individual in perpetuity |
| Death | `{"Death":"UUID"}\n` | Report the death of an individual |


### Standard Error Channel ###

The `stderr` channel is reserved for communicating errors and diagnostic
information from the environment program to the evolution program. The
`stderr` channel has no specific message format or protocol. By default
environments inherit their `stderr` channel from their evolution program.

