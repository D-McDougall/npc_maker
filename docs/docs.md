# Protocol Documentation
<a name="top"></a>

## Table of Contents

- [controller.proto](#controller-proto)
    - [AdvanceRequest](#controller-AdvanceRequest)
    - [ControllerRequest](#controller-ControllerRequest)
    - [ControllerResponse](#controller-ControllerResponse)
    - [GetOutputsRequest](#controller-GetOutputsRequest)
    - [InitializeRequest](#controller-InitializeRequest)
    - [IoValue](#controller-IoValue)
    - [ResetRequest](#controller-ResetRequest)
    - [SetInputsRequest](#controller-SetInputsRequest)
  
    - [Controller](#controller-Controller)
  
- [diagnostics.proto](#diagnostics-proto)
    - [Count](#diagnostics-Count)
    - [Organism](#diagnostics-Organism)
    - [Score](#diagnostics-Score)
  
    - [Diagnostics](#diagnostics-Diagnostics)
  
- [environment.proto](#environment-proto)
    - [DeathRequest](#environment-DeathRequest)
    - [DeathResponse](#environment-DeathResponse)
    - [EpigenomeRequest](#environment-EpigenomeRequest)
    - [EpigenomeResponse](#environment-EpigenomeResponse)
    - [KeyValue](#environment-KeyValue)
    - [MateRequest](#environment-MateRequest)
    - [ScoreRequest](#environment-ScoreRequest)
    - [ScoreResponse](#environment-ScoreResponse)
    - [SpawnRequest](#environment-SpawnRequest)
    - [TelemetryRequest](#environment-TelemetryRequest)
    - [TelemetryResponse](#environment-TelemetryResponse)
  
    - [Environment](#environment-Environment)
  
- [evolution.proto](#evolution-proto)
    - [DeathRequest](#evolution-DeathRequest)
    - [DeathResponse](#evolution-DeathResponse)
    - [SpawnRequest](#evolution-SpawnRequest)
    - [SpawnResponse](#evolution-SpawnResponse)
  
    - [Evolution](#evolution-Evolution)
  
- [experiment.proto](#experiment-proto)
    - [Experiment](#experiment-Experiment)
    - [Organism](#experiment-Organism)
  
- [genetics.proto](#genetics-proto)
    - [ReproduceRequest](#genetics-ReproduceRequest)
    - [ReproduceResponse](#genetics-ReproduceResponse)
  
    - [Genetics](#genetics-Genetics)
  
- [individual.proto](#individual-proto)
    - [Individual](#individual-Individual)
    - [Metadata](#individual-Metadata)
    - [Metadata.TelemetryEntry](#individual-Metadata-TelemetryEntry)
  
- [Scalar Value Types](#scalar-value-types)



<a name="controller-proto"></a>
<p align="right"><a href="#top">Top</a></p>

## controller.proto



<a name="controller-AdvanceRequest"></a>

### AdvanceRequest
Advance the controller&#39;s internal state by `dt` seconds.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| dt | [double](#double) |  | Time interval, in seconds. |






<a name="controller-ControllerRequest"></a>

### ControllerRequest
A command sent by the environment to the controller.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| request_id | [uint64](#uint64) |  | request_id begins at 0 and auto-increments after every request. |
| initialize | [InitializeRequest](#controller-InitializeRequest) |  |  |
| reset | [ResetRequest](#controller-ResetRequest) |  |  |
| advance | [AdvanceRequest](#controller-AdvanceRequest) |  |  |
| set_inputs | [SetInputsRequest](#controller-SetInputsRequest) |  |  |
| get_outputs | [GetOutputsRequest](#controller-GetOutputsRequest) |  |  |






<a name="controller-ControllerResponse"></a>

### ControllerResponse
Controller response with motor outputs.

This is only sent in response to GetOutputsRequest messages.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| request_id | [uint64](#uint64) |  |  |
| outputs | [IoValue](#controller-IoValue) | repeated |  |






<a name="controller-GetOutputsRequest"></a>

### GetOutputsRequest
Retrieve data from motor output interfaces.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| ids | [uint64](#uint64) | repeated | Motor output interface IDs to retrieve. |






<a name="controller-InitializeRequest"></a>

### InitializeRequest
Initialize a new controller.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| phenome | [bytes](#bytes) |  | Genetic material for controller. |






<a name="controller-IoValue"></a>

### IoValue
Container for sensory input / motor output data.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| id | [uint64](#uint64) |  | Input/output interface ID.

Sensor and motor interfaces are enumerated, separately, starting at zero. |
| number | [double](#double) |  | 64 bit floating-point number. |
| text | [string](#string) |  | UTF-8 string. |
| blob | [bytes](#bytes) |  | Arbitrary binary data. |






<a name="controller-ResetRequest"></a>

### ResetRequest
Reset the controller to its initial state.






<a name="controller-SetInputsRequest"></a>

### SetInputsRequest
Deliver data from the environment to sensory input interfaces.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| inputs | [IoValue](#controller-IoValue) | repeated |  |





 

 

 


<a name="controller-Controller"></a>

### Controller
The Controller service provides control systems to its environment.

Each controller instance is represented by one bidirectional streaming session.
The environment sends commands and receives responses over the same stream.
Commands are processed sequentially, in the order received. The environment may
send additional commands while earlier commands are still outstanding.
Responses are correlated with requests by request_id.

A session-level failure terminates the session and kills the controller
instance. A command-level error is returned as a response and does not,
by itself, terminate the session.

| Method Name | Request Type | Response Type | Description |
| ----------- | ------------ | ------------- | ------------|
| Session | [ControllerRequest](#controller-ControllerRequest) stream | [ControllerResponse](#controller-ControllerResponse) stream |  |

 



<a name="diagnostics-proto"></a>
<p align="right"><a href="#top">Top</a></p>

## diagnostics.proto



<a name="diagnostics-Count"></a>

### Count
gRPC call count.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| count | [uint64](#uint64) |  |  |






<a name="diagnostics-Organism"></a>

### Organism
Organism identifier.

All diagnostics are tracked per organism type.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| body_type | [string](#string) |  |  |






<a name="diagnostics-Score"></a>

### Score
Maximum score value received


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| score | [double](#double) |  |  |





 

 

 


<a name="diagnostics-Diagnostics"></a>

### Diagnostics
Diagnostic interface for npc-server

| Method Name | Request Type | Response Type | Description |
| ----------- | ------------ | ------------- | ------------|
| LivingCount | [Organism](#diagnostics-Organism) | [Count](#diagnostics-Count) | Number of individuals in the environment. |
| SpawnCount | [Organism](#diagnostics-Organism) | [Count](#diagnostics-Count) | gRPC call counter for Spawn requests. |
| MateCount | [Organism](#diagnostics-Organism) | [Count](#diagnostics-Count) | gRPC call counter for Mate requests. |
| ScoreCount | [Organism](#diagnostics-Organism) | [Count](#diagnostics-Count) | gRPC call counter for Score requests. |
| TelemetryCount | [Organism](#diagnostics-Organism) | [Count](#diagnostics-Count) | gRPC call counter for Telementry requests. |
| DeathCount | [Organism](#diagnostics-Organism) | [Count](#diagnostics-Count) | gRPC call counter for Death requests. |
| MaximumScore | [Organism](#diagnostics-Organism) | [Score](#diagnostics-Score) | Maximum score over all historical records for an organism type. |

 



<a name="environment-proto"></a>
<p align="right"><a href="#top">Top</a></p>

## environment.proto



<a name="environment-DeathRequest"></a>

### DeathRequest
Notifies the npc-server and evolutionary algorithm that an individual has exited
the environment.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| name | [string](#string) |  | Name of the deceased Individual.

Optional if the environment contains only one individual. |






<a name="environment-DeathResponse"></a>

### DeathResponse







<a name="environment-EpigenomeRequest"></a>

### EpigenomeRequest



| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| name | [string](#string) |  |  |
| data | [bytes](#bytes) |  |  |






<a name="environment-EpigenomeResponse"></a>

### EpigenomeResponse







<a name="environment-KeyValue"></a>

### KeyValue



| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| key | [string](#string) |  |  |
| value | [string](#string) |  |  |






<a name="environment-MateRequest"></a>

### MateRequest



| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| parents | [string](#string) | repeated | Argument parents is a list of individual&#39;s names. |






<a name="environment-ScoreRequest"></a>

### ScoreRequest
Update the reproductive fitness of a living individual.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| name | [string](#string) |  | Individual&#39;s name. The individual must be alive and in this instance of the environment, meaning that its final score must be reported _before_ the death is called on the individual.

Optional if the environment contains only one individual. |
| score | [double](#double) |  |  |






<a name="environment-ScoreResponse"></a>

### ScoreResponse







<a name="environment-SpawnRequest"></a>

### SpawnRequest



| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| body_type | [string](#string) |  | Corresponds to an organism name in the experiment specification.

Optional if the environment contains only one body type. |






<a name="environment-TelemetryRequest"></a>

### TelemetryRequest
Set or update the environmential telemetry for an individual.

Every indvidual has an associative key-value store for the metadata it
accumulates over the course of its lifetime.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| name | [string](#string) |  | Individual&#39;s name. The individual must be alive and in this instance of the environment.

Optional if the environment contains only one individual. |
| data | [KeyValue](#environment-KeyValue) | repeated |  |






<a name="environment-TelemetryResponse"></a>

### TelemetryResponse






 

 

 


<a name="environment-Environment"></a>

### Environment
An environment program is self-contained simulated world. The `npc-server`
program connects Environment programs to Evolution and Genetics services via
the Environment service.

| Method Name | Request Type | Response Type | Description |
| ----------- | ------------ | ------------- | ------------|
| Spawn | [SpawnRequest](#environment-SpawnRequest) | [.individual.Individual](#individual-Individual) | Request a new individual from the evolutionary algorithm |
| Mate | [MateRequest](#environment-MateRequest) | [.individual.Individual](#individual-Individual) | Request a new individual by mating individuals together. This requires at least one parent. This accepts more than two parents. All parents must be alive, in this environment, and having the same body_type. |
| Score | [ScoreRequest](#environment-ScoreRequest) | [ScoreResponse](#environment-ScoreResponse) | Report the reproductive fitness of a living individual. This overwrites any previously reported value. |
| Telemetry | [TelemetryRequest](#environment-TelemetryRequest) | [TelemetryResponse](#environment-TelemetryResponse) | The environment associates some extra information with a living individual. The info is kept alongside the individual in perpetuity. |
| Epigenome | [EpigenomeRequest](#environment-EpigenomeRequest) | [EpigenomeResponse](#environment-EpigenomeResponse) |  |
| Death | [DeathRequest](#environment-DeathRequest) | [DeathResponse](#environment-DeathResponse) | Report the death of an individual. |

 



<a name="evolution-proto"></a>
<p align="right"><a href="#top">Top</a></p>

## evolution.proto



<a name="evolution-DeathRequest"></a>

### DeathRequest



| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| individual | [individual.Individual](#individual-Individual) |  |  |






<a name="evolution-DeathResponse"></a>

### DeathResponse







<a name="evolution-SpawnRequest"></a>

### SpawnRequest







<a name="evolution-SpawnResponse"></a>

### SpawnResponse



| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| parents | [individual.Individual](#individual-Individual) | repeated |  |





 

 

 


<a name="evolution-Evolution"></a>

### Evolution
The Evolution service manages a population.

An evolution service receives individuals after they die and is responsible for
deciding which of those individuals can reproduce. It may implement any
evolutionary algorithm, including a conventional genetic algorithm, artificial
selection, speciation, replay of previously successful individuals, or a
combination of these.

The selected parent Individuals are passed to the Genetics service, which
creates the child. If the genetic service is missing, then the first parent
will be cloned into the environment.

# Lifecycle

1. The npc-server calls `Spawn()` when the environment requests a new individual.

2. The Evolution service returns zero or more parent Individuals. If the
Evolution service is missing then zero parents are implicitly returned.

3. If one or more parents are returned, the npc-server passes them to the
Genetics service to create the child. If zero parents are returned, the
Genetics service uses the initial genetic material instead.

4. While the individual is alive, the environment updates the npc-server&#39;s copy
of the Individual with its current score, telemetry, and epigenome.

5. When the individual dies, the npc-server calls Death() with its final
Individual record.

| Method Name | Request Type | Response Type | Description |
| ----------- | ------------ | ------------- | ------------|
| Spawn | [SpawnRequest](#evolution-SpawnRequest) | [SpawnResponse](#evolution-SpawnResponse) | Selects the parent Individuals to create a new child individual.

The request contains no parameters because parent selection is controlled entirely by the Evolution service. The service may use its population, historical fitness, species, lineage, randomness, or any other information available to it when making the selection.

The response may contain any number of parents.

A response containing zero parents means that the genetics service will create a founder using the initial genetic material. |
| Death | [DeathRequest](#evolution-DeathRequest) | [DeathResponse](#evolution-DeathResponse) | Notifies the Evolution service that an Individual has died.

The request contains the npc-server&#39;s final copy of the Individual. The record includes information accumulated during the individual&#39;s life, including its final score, telemetry, and epigenome, as well as its immutable genome, phenome, and lineage metadata.

The Evolution service may retain the Individual for future parent selection, statistics, persistence, or replay. |

 



<a name="experiment-proto"></a>
<p align="right"><a href="#top">Top</a></p>

## experiment.proto



<a name="experiment-Experiment"></a>

### Experiment
Format for JSON experiment files (*.exp).

The experiment message defines the semantics of a complete artificial-life
experiment.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| name | [string](#string) |  |  |
| description | [string](#string) |  |  |
| environment | [string](#string) | repeated | Command line invocation for the environment program |
| evolution | [string](#string) | repeated | Default evolution service (command line invocation) |
| genetics | [string](#string) | repeated | Default genetics service (command line invocation) |
| controller | [string](#string) | repeated | Default controller service (command line invocation) |
| organisms | [Organism](#experiment-Organism) | repeated |  |






<a name="experiment-Organism"></a>

### Organism
Organism messages attach a evolutionary algorithm, genetic algorithm, and
control system to each body type.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| body_type | [string](#string) |  |  |
| description | [string](#string) | optional |  |
| evolution | [string](#string) | repeated | Command line invocation for this organism&#39;s Evolution service.

If missing then all spawn requests will create founder individuals, by sending zero parents to the genetic service.

Each instance of the Evolution service is assigned a subdirectory in the persistence_directory, which it uses as its initial working directory. |
| genetics | [string](#string) | repeated | Command line invocation for this organism&#39;s Genetics service.

If missing then the npc-server will use the first parent&#39;s genetic material, as returned by the evolution service.

Each instance of the Genetics service is assigned a subdirectory in the persistence_directory, which it uses as its initial working directory. |
| controller | [string](#string) | repeated | Command line invocation for this organism&#39;s Controller service. |





 

 

 

 



<a name="genetics-proto"></a>
<p align="right"><a href="#top">Top</a></p>

## genetics.proto



<a name="genetics-ReproduceRequest"></a>

### ReproduceRequest
List parent Individuals

Each parent must have a genome


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| parents | [individual.Individual](#individual-Individual) | repeated |  |






<a name="genetics-ReproduceResponse"></a>

### ReproduceResponse



| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| child | [individual.Individual](#individual-Individual) |  |  |





 

 

 


<a name="genetics-Genetics"></a>

### Genetics
The purpose of the genetic service is to handle all genetic material.

Genomes are treated as opaque binary objects outside of genetic algorithms.

The _genome_ refers to a complete set of parameters for creating an AI
agent&#39;s control system. Each individual has exactly one immutable genome.

Genomes are converted into &#34;**phenomes**&#34; before transmission to controllers.
This decouples the genetic representation from the control system implementation.

| Method Name | Request Type | Response Type | Description |
| ----------- | ------------ | ------------- | ------------|
| Reproduce | [ReproduceRequest](#genetics-ReproduceRequest) | [ReproduceResponse](#genetics-ReproduceResponse) |  |

 



<a name="individual-proto"></a>
<p align="right"><a href="#top">Top</a></p>

## individual.proto



<a name="individual-Individual"></a>

### Individual
Individuals are the entities that evolve

# File Format

The file format for an individual consists of a directory named after the
individual&#39;s name. The directory contains four files: metadata.json, which
contains the individual&#39;s metadata serialized using the protobuf JSON mapping,
and genome, epigenome, and phenome, which contain the corresponding data as raw
binary.

# Lifecycle

There are several pathways to creating individuals, depending on how the
environment requests them, and whether a genetic algorithm is specified.

## Spawn Sequence

1) The environment requests a new individual from the router via
`environment.Environment::Spawn()`.

2) The router requests parents from the evolution service via
`evolution.Evolution::Spawn()`.

3) The router forwards the parents to the genetic service via
`genetics.Genetics::Reproduce()`. The genetic service creates a new Individual
and returns it to the router.

4) The router sends the Individual to the environment. The router also keeps a
copy of the individual locally.

## Mate Sequence

1) The environment requests to mate some individuals via
`environment.Environment::Mate()`. Parents are specified by name, and the
router will have copies of the individuals on hand while they are alive in the
environment.

2) The router forwards the given parents to the genetic service via
`genetics.Genetics::Reproduce()`. The genetic service creates a new Individual
and returns it to the router.

3) The router sends the Individual to the environment. The router also keeps a
copy of the individual locally.

## Replay Sequence

This sequence resurrects dead Individuals, for example to recreate the best
performing individuals from a leaderboard. See program `npc-player` for more
information about using this sequence.

1) The environment requests a new Individual via either the spawn or mate
sequence.

2) The router requests an Individual from the evolution service via
`evolution.Evolution::Spawn()`. The first parent is used, the remaining parents
are discarded. At least one parent must be returned.

3) The router sends the Individual to the environment. The router also keeps a
copy of the individual locally.

## Life Sequence

1) The environment requests a new Individual via either the spawn or mate
sequence. The router may choose to ignore mate requests and return a spawned or
replayed individual instead.

2) The environment synchronizes their copy of the Individual with the router via
`environment.Environment::Telemetry()`
`environment.Environment::Epigenome()`
`environment.Environment::Score()`

3) The environment declares the Individual dead via
`environment.Environment::Death()`.

4) The router sends its copy of the Individual to the evolution service via
`evolution.Evolution::Death()`.

## Field Ownership

| Field | Set By | When |
| ----- | ------ | ---- |
| `metadata.name` | Genetics | At creation |
| `metadata.score` |  |  |


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| metadata | [Metadata](#individual-Metadata) |  | The metadata contains all human-readable / non-genetic information about the individual.

This field is required. |
| genome | [bytes](#bytes) | optional |  |
| epigenome | [bytes](#bytes) | optional | The epigenome is created by the controller.

The purpose of the epigenome is to allow self-modifying controllers to persist their modifications over reproductive cycles. |
| phenome | [bytes](#bytes) | optional | The phenome is sent to the controller.

The purpose of the phenome is to simplify the controller&#39;s design, by allowing the genetic module to reformat the genome before transmission. |






<a name="individual-Metadata"></a>

### Metadata
Metadata for an Individual

This contains the individual&#39;s human readable data.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| name | [string](#string) |  | UUID of this individual

Typically, this will be a 128 bit random number as 32 uppercase hex digits (UUID-4), but technically it can be any string that is universally unique among all individuals.

Name must be a valid file system directory name. |
| environment | [string](#string) | optional | Name of the environment that this individual lives in |
| body_type | [string](#string) | optional | Name of the body type used by this individual. |
| controller | [string](#string) | repeated | Command-line invocation of the controller program |
| score | [double](#double) | optional | Reproductive fitness of this individual, as assessed by the environment.

Higher is better.

Unset values are translated to -∞. |
| telemetry | [Metadata.TelemetryEntry](#individual-Metadata-TelemetryEntry) | repeated | Environmental information |
| species | [string](#string) | optional | UUID for artificial speciation |
| parents | [string](#string) | repeated | Names of parents |
| children | [uint64](#uint64) | optional | Number of children |
| generation | [uint64](#uint64) | optional | Number of generations that came before this individual.

This is the lineage depth, which is defined highest generation among its parents plus one, with 0 for founders. |
| ascension | [uint64](#uint64) | optional | Number of individuals who died before this one.

This is 0-based and counted separately for each body type.

The Evolution service assigns this. |
| birth_date | [google.protobuf.Timestamp](#google-protobuf-Timestamp) | optional | UTC time at which this individual was born.

This is assigned by the router program, immediately before sending the individual to the environment. |
| death_date | [google.protobuf.Timestamp](#google-protobuf-Timestamp) | optional | UTC time at which this individual died.

This is assigned by the router program, immediately after receiving the corresponding death message. |
| extra | [google.protobuf.Struct](#google-protobuf-Struct) |  | User-defined fields are allowed in the `extra` dictionary. |






<a name="individual-Metadata-TelemetryEntry"></a>

### Metadata.TelemetryEntry



| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| key | [string](#string) |  |  |
| value | [string](#string) |  |  |





 

 

 

 



## Scalar Value Types

| .proto Type | Notes | C++ | Java | Python | Go | C# | PHP | Ruby |
| ----------- | ----- | --- | ---- | ------ | -- | -- | --- | ---- |
| <a name="double" /> double |  | double | double | float | float64 | double | float | Float |
| <a name="float" /> float |  | float | float | float | float32 | float | float | Float |
| <a name="int32" /> int32 | Uses variable-length encoding. Inefficient for encoding negative numbers – if your field is likely to have negative values, use sint32 instead. | int32 | int | int | int32 | int | integer | Bignum or Fixnum (as required) |
| <a name="int64" /> int64 | Uses variable-length encoding. Inefficient for encoding negative numbers – if your field is likely to have negative values, use sint64 instead. | int64 | long | int/long | int64 | long | integer/string | Bignum |
| <a name="uint32" /> uint32 | Uses variable-length encoding. | uint32 | int | int/long | uint32 | uint | integer | Bignum or Fixnum (as required) |
| <a name="uint64" /> uint64 | Uses variable-length encoding. | uint64 | long | int/long | uint64 | ulong | integer/string | Bignum or Fixnum (as required) |
| <a name="sint32" /> sint32 | Uses variable-length encoding. Signed int value. These more efficiently encode negative numbers than regular int32s. | int32 | int | int | int32 | int | integer | Bignum or Fixnum (as required) |
| <a name="sint64" /> sint64 | Uses variable-length encoding. Signed int value. These more efficiently encode negative numbers than regular int64s. | int64 | long | int/long | int64 | long | integer/string | Bignum |
| <a name="fixed32" /> fixed32 | Always four bytes. More efficient than uint32 if values are often greater than 2^28. | uint32 | int | int | uint32 | uint | integer | Bignum or Fixnum (as required) |
| <a name="fixed64" /> fixed64 | Always eight bytes. More efficient than uint64 if values are often greater than 2^56. | uint64 | long | int/long | uint64 | ulong | integer/string | Bignum |
| <a name="sfixed32" /> sfixed32 | Always four bytes. | int32 | int | int | int32 | int | integer | Bignum or Fixnum (as required) |
| <a name="sfixed64" /> sfixed64 | Always eight bytes. | int64 | long | int/long | int64 | long | integer/string | Bignum |
| <a name="bool" /> bool |  | bool | boolean | boolean | bool | bool | boolean | TrueClass/FalseClass |
| <a name="string" /> string | A string must always contain UTF-8 encoded or 7-bit ASCII text. | string | String | str/unicode | string | string | string | String (UTF-8) |
| <a name="bytes" /> bytes | May contain any arbitrary sequence of bytes. | string | ByteString | str | []byte | ByteString | string | String (ASCII-8BIT) |

