# Individuals #

An "**individual**" is a distinct life-form with its own genome.
Evolutionary algorithms operate on individuals, while genetic algorithms
operate on genomes.


## The Individual File Format ##

Individuals are stored in a standard file format. An individual consist of a
genome and a bundle of metadata. The genome is stored as a binary blob; the
metadata is stored as a JSON object. Individuals are required to have a name,
controller, and genome; everything else is optional. Unexpected JSON attributes
are allowed and accessible through the python and rust APIs. The following
table defines the standard metadata attributes:

| Attribute  | JSON Type | Description |
| :--------  | :-------: | :---------- |
| `"name"`        | String    | UUID of this individual |
| `"environment"` | String    | Name of the environment that this individual lives in |
| `"body_type"`   | String    | Name of the body_type used by this individual |
| `"controller"`  | List of Strings | Command line invocation of the controller program |
| `"score"`       | String    | Reproductive fitness of this individual, as assessed by the environment |
| `"telemetry"`   | Map of Strings to Strings | Environmental info dictionary |
| `"epigenome"`   | Map of Strings to Strings | Epigenetic info dictionary |
| `"species"`     | String    | UUID for artificial speciation |
| `"parents"`     | Number    | Number of parents |
| `"children"`    | Number    | Number of children |
| `"generation"`  | Number    | Number of generations that came before this individual |
| `"ascension"`   | Number    | Number of individuals who died before this one |
| `"birth_date"`  | String    | UTC timestamp |
| `"death_date"`  | String    | UTC timestamp |

The file format for individuals is:
1) Metadata, as a utf-8 JSON formatted string
2) NULL character, `\x00`
3) Genome, as a binary array until end of file

Individual files always named after the individual's name, and with the
file extension `.indiv`

