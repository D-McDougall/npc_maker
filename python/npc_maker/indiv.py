"""
Data structure to represent an individual life-form
"""

from pathlib import Path
from .utils import clean_command
import io
import json
import math
import os
import tempfile
import uuid

__all__ = (
    "Individual",
)

def _check_genome(genome):
    assert type(genome) is bytes
    assert len(genome) > 0

# All individuals have these fields, with default value constructors.
_standard_fields = {
    "name": None,
    "environment": None,
    "body_type": None,
    "controller": None,
    "score": type(None),
    "telemetry": dict,
    "epigenome": dict,
    "species": lambda: str(uuid.uuid4()),
    "parents": list,
    "children": list,
    "generation": int,
    "ascension": type(None),
    "birth_date": str,
    "death_date": str,
}

class Individual:
    """
    Container for a distinct life-form and all of its associated data
    """
    def __init__(self,
                environment: str,
                body_type: str,
                controller: [str],
                genome: bytes):
        """
        Create a new individual. This is used to initialize new populations
        """
        _check_genome(genome)
        self.name           = str(uuid.uuid4())
        self.environment    = str(environment)
        self.body_type      = str(body_type)
        # Don't resolve the path because the PWD could change.
        self.controller     = clean_command(controller, resolve=False)
        self.genome         = genome
        self.score          = None
        self.telemetry      = {}
        self.epigenome      = {}
        self.species        = str(uuid.uuid4())
        self.parents        = []
        self.children       = []
        self.birth_date     = ""
        self.death_date     = ""
        self.generation     = 0
        self.ascension      = None
        self.extra          = {}
        self.path           = None

    def get_name(self) -> str:
        """
        Get this individual's name, which is a UUID string
        """
        return self.name

    def get_environment(self) -> str:
        """
        Get the name of environment which contains this individual
        """
        return self.environment

    def get_body_type(self) -> str:
        """
        Get the name of this individual's body_type
        """
        return self.body_type

    def get_controller(self) -> list:
        """
        Get the command line invocation for the controller program
        """
        return list(self.controller)

    def get_genome(self) -> bytes:
        """
        Get this individual's genetic data,
        which is an immutable byte array
        """
        if self.genome is None:
            with open(self.path, 'rb') as file:
                data = file.read()
            metadata, self.genome = data.split(b'\x00', maxsplit=1)
        return self.genome

    def get_score(self) -> str:
        """
        Get the most recently assigned score,
        or None if it has not been assigned yet
        """
        return self.score

    def get_custom_score(self, score_function="score") -> float:
        """
        Apply a custom scoring function to this individual

        Several classes accept an optional custom score function,
        and they delegate to this method.

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
        # 
        if score is None:
            score = -math.inf
        # 
        return float(score)

    def get_telemetry(self) -> dict:
        """
        Get the environmental info dictionary

        Returns a reference to the individual's internal "telemetry" dictionary;
        modifications are permanent.
        """
        return self.telemetry

    def get_epigenome(self) -> dict:
        """
        Get the epigenetic info dictionary

        Returns a reference to the individual's internal "epigenome" dictionary;
        modifications are permanent.
        """
        return self.epigenome

    def get_species(self) -> str:
        """
        Get the species UUID

        Mating may be restricted to individuals of the same species.
        """
        return self.species

    def get_parents(self) -> [str]:
        """
        Get the names of this individual's parents
        """
        return list(self.parents)

    def get_children(self) -> [str]:
        """
        Get the names of this individual's children
        """
        return list(self.children)

    def get_birth_date(self) -> str:
        """
        The time of birth, as a UTC timestamp,
        or an empty string if this individual has not yet been born
        """
        return self.birth_date

    def get_death_date(self) -> str:
        """
        The time of death, as a UTC timestamp,
        or an empty string if this individual has not yet died
        """
        return self.death_date

    def get_generation(self) -> int:
        """
        How many cohorts of the population size passed before this individual was born?
        """
        return self.generation

    def get_ascension(self) -> int:
        """
        How many individuals died before this individual?
        Returns None if this individual has not yet died.
        """
        return self.ascension

    def get_extra(self) -> dict:
        """
        Get all custom / unofficial fields that are saved with the individual

        Returns a reference to this individual's internal data.
        Changes made to the returned value will persist with the individual.
        """
        return self.extra

    def get_path(self) -> Path:
        """
        Returns the file path this individual was loaded from or saved to.
        Returns None if this individual has not touched the file system.
        """
        return self.path

    def asex(self, child_genome: bytes) -> "Individual":
        """
        Asexually reproduce an individual
        """
        _check_genome(child_genome)
        cls = type(self)
        child = cls(child_genome,
                environment = self.environment,
                body_type   = self.body_type,
                controller  = self.controller,
                epigenome   = self.epigenome,
                species     = self.species,
                generation  = self.generation + 1,
                parents     = [self.name])
        self.children.append(child.name)
        return child

    @classmethod
    def sex(cls, parents: ["Individual"], child_genome: bytes) -> "Individual":
        """
        Sexually reproduce the given individuals
        """
        parents = list(parents)
        # Technically the spec requires 2 parents, 1 parent should not crash it
        assert len(parents) >= 1
        assert all(isinstance(p, cls) for p in parents)
        _check_genome(child_genome)
        self = parents[0]
        child = cls(child_genome,
                environment = self.environment,
                body_type   = self.body_type,
                species     = self.species,
                controller  = self.controller,
                generation  = max(p.generation for p in parents) + 1,
                parents     = list(p.name for p in parents))
        # Update the parent's children.
        for p in parents:
            p.children.append(child.name)
        return child

    def save(self, path=None) -> Path:
        """
        Serialize this individual to JSON and write it to a file

        Argument path is the directory to save in. Optional, if missing will
        either overwrite the previous save file or save to temporary directory.
        The filename will be the individual's name with the ".indiv" file extension.

        Returns the file path of the saved individual.
        """
        if not path:
            if self.path:
                path = self.path.parent
            else:
                path = tempfile.gettempdir()
        path = Path(path)
        # Make the directory in case this is the first individual to be saved to it.
        if not path.exists():
            path.mkdir()
        assert path.is_dir()
        path = path.joinpath(self.name + ".indiv")
        # Load genome from file before modifying the file system.
        genome = self.get_genome()
        # Unofficial fields, in case of conflict these take lower precedence.
        data = dict(self.extra)
        # Official fields, as described by the specification.
        for attribute in _standard_fields:
            value = getattr(self, attribute, None)
            if value:
                data[attribute] = value
        # Convert paths to strings for JSON serialization.
        if self.controller:
            data["controller"]    = list(data["controller"])
            data["controller"][0] = str(data["controller"][0])
        # 
        data = json.dumps(data)
        # Save to a temporary file, sync, and atomic move into place.
        fd, tmp_path = tempfile.mkstemp()
        file = os.fdopen(fd, "wb")
        file.write(data.encode("utf-8"))
        file.write(b'\x00')
        file.write(genome)
        file.flush()
        file.close()
        Path(tmp_path).rename(path)
        self.path = path
        return path

    @classmethod
    def load(cls, path) -> 'Individual':
        """
        Load a previously saved individual

        Returns None if the given path does not end with ".indiv"
        """
        path = Path(path)
        if path.suffix.lower() != ".indiv":
            return
        text = b''
        with open(path, 'rb') as file:
            while True:
                chunk = file.read(io.DEFAULT_BUFFER_SIZE)
                split = chunk.split(b'\x00', maxsplit=1)
                text += split[0]
                if len(split) > 1:
                    break
        metadata = json.loads(text)
        self = cls.__new__(cls, **metadata)
        for attribute, default_value in _standard_fields.items():
            if attribute in metadata:
                value = metadata.pop(attribute)
            elif attribute == "name":
                value = path.stem
            elif default_value is not None:
                value = default_value()
            else:
                continue
            setattr(self, attribute, value)
        self.extra = metadata
        self.path = path
        self.genome = None
        # Convert controller path back to Path objects.
        if getattr(self, "controller", False):
            self.controller[0] = Path(self.controller[0])
        return self
