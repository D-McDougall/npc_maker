"""
Data structure and persistence for an individual life-form.

An `Individual` is a thin wrapper around the protobuf message defined in
`proto/individual.proto`. The wrapper adds convenient attribute access,
reproduction bookkeeping, and persistence to and from disk. Use `from_proto()`
and `to_proto()` to move between this class and the raw protobuf message,
for example when sending individuals over gRPC.

File format
-----------
This is the same format that is read and written by the Rust API
(`rust/src/individual.rs`). An individual is stored as a directory named after
the individual, located beneath a directory supplied to `save()`:

    <parent>/
    └── <individual.name>/
        ├── metadata.json   protobuf-JSON encoding of the `Metadata` message
        ├── genome          raw bytes
        ├── epigenome       raw bytes
        └── phenome         raw bytes

All four files are required. Absent (`None`) genomes, epigenomes, and phenomes
are written as empty files, and are read back as empty byte strings.
"""

import datetime
import json
import math
import os
import shlex
import shutil
import uuid
from pathlib import Path

from google.protobuf import json_format
from google.protobuf.timestamp_pb2 import Timestamp

try:
    from ._protobuf import individual_pb2
except ImportError as error:  # pragma: no cover
    raise ImportError(
        "the protobuf modules of the NPC Maker have not been generated, run `make python`"
    ) from error

__all__ = (
    "Individual",
)

_METADATA_FILE = "metadata.json"
_BLOB_FILES = ("genome", "epigenome", "phenome")


def _uuid4() -> str:
    """
    Generate a universally unique name, format unspecified.
    """
    return str(uuid.uuid4())


def _check_name(name: str) -> str:
    """
    Individuals are stored in directories which are named after them,
    so reject names which could refer to anything other than a child directory.

    This is necessary for internet security.
    """
    if not name or name in (".", "..") or any(char in name for char in "/\\\0"):
        raise ValueError(f"invalid individual name {name!r}")
    return name


def _command(command) -> list:
    """
    Clean a command line invocation into a list of strings.

    Argument may be None, a string (split into words using shell syntax),
    a path, or an iterable of strings and paths.
    """
    if command is None:
        return []
    if isinstance(command, str):
        return shlex.split(command)
    if isinstance(command, os.PathLike):
        return [os.fspath(command)]
    words = []
    for word in command:
        if isinstance(word, (bytes, bytearray)):
            raise TypeError(f"command arguments must be strings, found {type(word).__name__}")
        words.append(os.fspath(word) if isinstance(word, os.PathLike) else str(word))
    return words


def _optional_field(field: str, doc: str) -> property:
    """
    Property for an `optional` scalar field of the Metadata message.
    The value is None when the field is unset, and assigning None unsets it.
    """
    def getter(self):
        metadata = self._message.metadata
        return getattr(metadata, field) if metadata.HasField(field) else None

    def setter(self, value):
        if value is None:
            self._message.metadata.ClearField(field)
        else:
            setattr(self._message.metadata, field, value)

    return property(getter, setter, doc=doc)


def _timestamp_field(field: str, doc: str) -> property:
    """
    Property for an optional Timestamp field, exposed as a timezone-aware
    `datetime` in UTC. Naive datetimes are assumed to be in UTC.
    """
    def getter(self):
        metadata = self._message.metadata
        if not metadata.HasField(field):
            return None
        return getattr(metadata, field).ToDatetime(tzinfo=datetime.timezone.utc)

    def setter(self, value):
        if value is None:
            self._message.metadata.ClearField(field)
        else:
            timestamp = Timestamp()
            timestamp.FromDatetime(value)
            getattr(self._message.metadata, field).CopyFrom(timestamp)

    return property(getter, setter, doc=doc)


def _blob_field(field: str, doc: str) -> property:
    """
    Property for an optional `bytes` field of the Individual message.
    The value is None when the field is unset, and assigning None unsets it.
    """
    def getter(self):
        return getattr(self._message, field) if self._message.HasField(field) else None

    def setter(self, value):
        if value is None:
            self._message.ClearField(field)
        else:
            setattr(self._message, field, bytes(value))

    return property(getter, setter, doc=doc)


class Individual:
    """
    Container for a distinct life-form and all of its associated data.

    Fields that the protobuf specification marks as optional read as None
    until they are assigned. Assigning None clears them.
    """

    __slots__ = ("_message",)

    def __init__(self):
        """
        Create a new individual. This is used to initialize new populations.
        """
        self._message = individual_pb2.Individual()
        self.name        = _uuid4()
        self.species     = _uuid4()
        self.generation  = 0

    @classmethod
    def from_proto(cls, message) -> "Individual":
        """
        Wrap a protobuf `individual_pb2.Individual` message.

        The message is *not* copied: changes made through the returned object
        are visible in the message, and vice versa.
        """
        if not isinstance(message, individual_pb2.Individual):
            raise TypeError(f"expected an Individual protobuf message, found {type(message).__name__}")
        self = cls.__new__(cls)
        self._message = message
        return self

    def to_proto(self):
        """
        Get the underlying protobuf `individual_pb2.Individual` message,
        for example: to serialize, or to send over gRPC.

        This returns a reference, not a copy.
        """
        return self._message

    def __eq__(self, other):
        if not isinstance(other, Individual):
            raise TypeError(
                f"invalid comparison between types {type(self).__name__} and {type(other).__name__}")
        return self._message == other._message

    def __repr__(self):
        return (f"Individual(name={self.name!r}, body_type={self.body_type!r}, score={self.score!r})")

    def get_custom_score(self, score_function="score") -> float:
        """
        Apply a custom scoring function to this individual.

        Argument score_function must be one of the following:
            * A callable function: f(individual) -> float,
            * The word "score",
            * The word "ascension",
            * A key in the individual's telemetry dictionary. The corresponding
              value will be converted into a float.

        A score of None is converted into negative infinity.
        """
        if callable(score_function):
            score = score_function(self)
        elif not score_function or score_function == "score":
            score = self.score
        elif score_function == "ascension":
            score = self.ascension
        elif score_function in self.telemetry:
            score = self.telemetry[score_function]
        else:
            raise ValueError("unrecognized score function " + repr(score_function))
        if score is None:
            score = -math.inf
        return float(score)

    @classmethod
    def reproduce(cls, parents) -> "Individual":
        """
        Reproduce the given individuals.

        Argument parents is a list of Individuals. The child inherits its
        environment, body type, controller, and species from the first parent,
        and is one generation older than its oldest parent (the parent with the
        highest generation, where founders are generation zero). Parents are
        recorded in the order given, which may include repeats. Each distinct
        parent counts the child once in its `children`.

        Returns the child.

        The child's other fields are unset, in particular it does not inherit the
        parents' score, telemetry, epigenome, or extra fields. If the first parent
        has no species then neither does the child.

        The caller must set the genome, epigenome, and phenome attributes.

        Raises ValueError if there are no parents, and TypeError if any parent is
        not an Individual.
        """
        parents = list(parents)
        if not parents:
            raise ValueError("at least one parent is required")
        if not all(isinstance(parent, Individual) for parent in parents):
            raise TypeError("parents must be Individuals")
        first = parents[0]
        child = cls()
        child.environment = first.environment
        child.body_type   = first.body_type
        child.controller  = first.controller
        child.species     = first.species
        child.generation  = max(parent.generation or 0 for parent in parents) + 1
        child.parents     = [parent.name for parent in parents]
        unique_parents    = {id(parent): parent for parent in parents}
        for parent in unique_parents.values():
            parent.children = (parent.children or 0) + 1
        return child

    # Metadata fields, see proto/individual.proto for the authoritative documentation.

    @property
    def name(self) -> str:
        """
        This individual's name, which is a UUID string.
        It is also the name of the directory that the individual is saved in.
        """
        return self._message.metadata.name

    @name.setter
    def name(self, value: str):
        self._message.metadata.name = value

    environment = _optional_field("environment",
        "Name of the environment that this individual lives in")

    body_type = _optional_field("body_type",
        "Name of the body type used by this individual")

    @property
    def controller(self) -> list:
        """
        Command line invocation of the controller program, as a list of strings.

        Returns a copy, assign a new value to modify it.
        """
        return list(self._message.metadata.controller)

    @controller.setter
    def controller(self, value):
        self._message.metadata.controller[:] = _command(value)

    score = _optional_field("score",
        "Reproductive fitness of this individual, as assessed by the environment, "
        "or None if it has not been assigned yet")

    @property
    def telemetry(self):
        """
        Environmental information, a dictionary of strings to strings.

        Returns a reference to the individual's internal data; modifications
        are permanent. Values must be strings.
        """
        return self._message.metadata.telemetry

    @telemetry.setter
    def telemetry(self, value):
        self._message.metadata.telemetry.clear()
        self._message.metadata.telemetry.update(value)

    species = _optional_field("species",
        "UUID for artificial speciation. "
        "Mating may be restricted to individuals of the same species.")

    @property
    def parents(self) -> list:
        """
        Names of this individual's parents.

        Returns a copy, assign a new value to modify it.
        """
        return list(self._message.metadata.parents)

    @parents.setter
    def parents(self, value):
        self._message.metadata.parents[:] = value

    children = _optional_field("children",
        "Number of children")

    generation = _optional_field("generation",
        "Number of generations that came before this individual")

    ascension = _optional_field("ascension",
        "Number of individuals who died before this one, "
        "or None if this individual has not yet died. "
        "This is assigned by the evolution program.")

    birth_date = _timestamp_field("birth_date",
        "UTC time at which this individual was born, as a timezone-aware datetime, "
        "or None if it has not yet been born")

    death_date = _timestamp_field("death_date",
        "UTC time at which this individual died, as a timezone-aware datetime, "
        "or None if it has not yet died")

    @property
    def extra(self):
        """
        User-defined fields, a JSON-like dictionary.

        Returns a reference to the individual's internal `google.protobuf.Struct`;
        modifications are permanent. Like all JSON, numbers are stored as floats.
        """
        return self._message.metadata.extra

    genome = _blob_field("genome",
        "This individual's genetic data, an immutable byte array")

    epigenome = _blob_field("epigenome",
        "This individual's epigenetic data, a mutable byte array")

    phenome = _blob_field("phenome",
        "This individual's phenotype, the data which is sent to the controller")

    # Persistence

    def save(self, path) -> Path:
        """
        Save this individual to the file system.

        Argument path is the directory to save in, which is created if it
        does not exist (but its own parent directory must exist). This writes a
        new directory named after the individual, see the module documentation
        for the file format.

        Existing individuals are never overwritten, this raises FileExistsError.
        The individual's name must be a valid directory name, otherwise this
        raises ValueError before anything is written. If an error occurs while
        writing, then the partially written individual is removed.

        Returns the path of the directory containing the individual's files,
        which is the argument to `load()`.
        """
        name = _check_name(self.name)
        path = Path(path)
        path.mkdir(exist_ok=True)
        directory = path.joinpath(name)
        directory.mkdir()  # Do not allow overwrite
        try:
            metadata = json_format.MessageToJson(
                self._message.metadata,
                preserving_proto_field_name=True,
                indent=2,
                ensure_ascii=False)
            directory.joinpath(_METADATA_FILE).write_bytes(metadata.encode("utf-8"))
            for blob in _BLOB_FILES:
                directory.joinpath(blob).write_bytes(getattr(self, blob) or b"")
        except BaseException:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        return directory

    @classmethod
    def load(cls, path) -> "Individual":
        """
        Load an individual's metadata, genome, epigenome, and phenome.

        Argument path is the directory containing the individual's files,
        which is the directory named after the individual. This is the value
        returned by `save()`, *not* the directory which was passed to it.

        Raises FileNotFoundError if any of the four files is missing,
        and ValueError if the metadata is not valid.
        """
        directory = Path(path)
        metadata = cls._read_metadata(directory)
        message = individual_pb2.Individual(metadata=metadata)
        for blob in _BLOB_FILES:
            setattr(message, blob, directory.joinpath(blob).read_bytes())
        return cls.from_proto(message)

    @staticmethod
    def load_dir(path) -> list:
        """
        Load the metadata of every individual stored in the given directory.

        Only the metadata is read, which is much faster than loading the
        individuals. Returns a list of protobuf `individual_pb2.Metadata`
        messages. Entries which are not directories are ignored. If any
        subdirectory cannot be loaded then this raises the corresponding error.
        """
        directories = []
        with os.scandir(path) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    directories.append(Path(entry.path))
        return [Individual._read_metadata(directory) for directory in sorted(directories)]

    @staticmethod
    def delete(path):
        """
        Remove an individual's directory from the file system.

        Argument path is the directory containing the individual's files,
        like the argument to `load()`. Only the individual's four files are
        removed, and this raises an error if the directory contains anything else.
        """
        directory = Path(path)
        if not directory.joinpath(_METADATA_FILE).exists():
            raise ValueError(f"expected {_METADATA_FILE} in individual directory: {directory}")
        directory.joinpath(_METADATA_FILE).unlink()
        for blob in _BLOB_FILES:
            directory.joinpath(blob).unlink()
        directory.rmdir()

    @staticmethod
    def _read_metadata(directory: Path):
        text = directory.joinpath(_METADATA_FILE).read_bytes()
        try:
            # Decode the JSON here instead of using json_format.Parse(), because
            # Parse() accepts a top-level list as if it were an empty message.
            data = json.loads(text.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("expected a JSON object")
            return json_format.ParseDict(data, individual_pb2.Metadata())
        except (ValueError, json_format.ParseError) as error:
            raise ValueError(f"invalid {_METADATA_FILE} in {directory}: {error}") from error
