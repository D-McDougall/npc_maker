"""
Data structure to represent an Individual life-form
"""

from pathlib import Path
import copy
import io
import json
import math
import os
import shlex
import tempfile
import uuid

class Individual:
    """
    Container for a distinct life-form and all of its associated data
    """
    def __init__(self, genome, *,
                name=None,
                environment=None,
                body_type=None,
                controller=None,
                score=None,
                telemetry={},
                epigenome={},
                species=None,
                parents=[],
                children=[],
                birth_date=None,
                death_date=None,
                generation=0,
                ascension=None,
                path=None,
                **extra):
        self.name           = str(name)         if name is not None else str(uuid.uuid4())
        self.environment    = str(environment)  if environment is not None else None
        self.body_type      = str(body_type)    if body_type is not None else None
        self.controller     = self._clean_ctrl_command(controller)
        self._genome        = genome
        self._genome_cls    = type(genome)
        self.score          = str(score)        if score is not None else None
        self.telemetry      = dict(telemetry)
        self.epigenome      = dict(epigenome)
        self.species        = str(species)      if species is not None else str(uuid.uuid4())
        self.parents        = [str(name) for name in parents]
        self.children       = [str(name) for name in children]
        self.birth_date     = str(birth_date)   if birth_date is not None else None
        self.death_date     = str(death_date)   if death_date is not None else None
        self.generation     = int(generation)
        self.ascension      = int(ascension)    if ascension is not None else None
        self.extra          = extra
        self.path           = Path(path)        if path is not None else None
        assert genome is not None or self.path is not None, "missing genome"

    @staticmethod
    def _clean_ctrl_command(command):
        if command is None:
            return None
        elif isinstance(command, Path):
            command = [command]
        elif isinstance(command, str):
            command = shlex.split(command)
        else:
            command = list(command)
        if not command:
            return None
        # Don't resolve the path yet in case the PWD changes.
        program = Path(command[0]) # .expanduser().resolve()
        command[0] = program
        for index in range(1, len(command)):
            arg = command[index]
            if not isinstance(arg, bytes) and not isinstance(arg, str):
                command[index] = str(arg)
        return command

    def get_name(self) -> str:
        """
        Get this individual's name, which is a UUID string.
        """
        return self.name

    def get_environment(self) -> str:
        """
        Get the name of environment which contains this individual.
        """
        return self.environment

    def get_body_type(self) -> str:
        """
        Get the name of this individual's body_type.
        """
        return self.body_type

    def get_controller(self) -> list:
        """
        Get the command line invocation for the controller program.
        """
        return copy.copy(self.controller)

    def get_genome(self) -> Genome:
        """
        Get this individual's genetic data.
        Genome's are considered immutable.
        """
        if self._genome is None:
            self._load_genome()
        return self._genome

    def get_score(self) -> str:
        """
        Get the most recently assigned score,
        or None if it has not been assigned yet.
        """
        return self.score

    def get_custom_score(self, score_function="score") -> float:
        """
        Apply a custom scoring function to this individual.

        Several classes in this module accept an optional custom score function,
        and they delegate to this method.

        Argument score_function must be one of the following:
            * A callable function: f(individual) -> float,
            * The word "score",
            * The word "ascension",
            * A key in the individual's telemetry dictionary. The corresponding
              value will be converted in to a float.
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
            score = math.nan
        # 
        return float(score)

    def get_telemetry(self) -> dict:
        """
        Get the environmental info dictionary.

        Returns a reference to the individual's internal "telemetry" dictionary,
        modifications are permanent.
        """
        return self.telemetry

    def get_epigenome(self) -> dict:
        """
        Get the epigenetic info dictionary.

        Returns a reference to the individual's internal "epigenome" dictionary,
        modifications are permanent.
        """
        return self.epigenome

    def get_species(self) -> str:
        """
        Get the species UUID.

        Mating may be restricted to individuals of the same species.
        """
        return self.species

    def get_parents(self) -> [str]:
        """
        Get the names of this individual's parents.
        """
        return list(self.parents)

    def get_children(self) -> [str]:
        """
        Get the names of this individual's children.
        """
        return list(self.children)

    def get_birth_date(self) -> str:
        """
        The time of birth, as a UTC timestamp,
        or None if this individual has not yet been born.
        """
        return self.birth_date

    def get_death_date(self) -> str:
        """
        The time of death, as a UTC timestamp,
        or None if this individual has not yet died.
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
        Get all custom / unofficial fields that are saved with the individual.

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

    def get_phenome(self):
        """
        Format the genome into a binary blob for the control system.
        """
        genome = self.get_genome()
        if isinstance(genome, Epigenome):
            parameters = genome.phenome(self.epigenome)
        elif isinstance(genome, Genome):
            parameters = genome.phenome()
        else:
            parameters = genome
        # Check data type.
        if isinstance(parameters, str):
            parameters = parameters.encode("utf-8")
        assert isinstance(parameters, bytes)
        return parameters

    def clone(self):
        """
        Create an identical copy of this genome.
        """
        # Clone the genetic material.
        genome = self.get_genome()
        if isinstance(genome, Genome):
            clone_genome = genome.clone()
        else:
            clone_genome = copy.deepcopy(genome)
        # Make a new individual with the copied genetics.
        clone = Individual(clone_genome,
                epigenome   = self.epigenome,
                environment = self.environment,
                body_type   = self.body_type,
                species     = self.species,
                controller  = self.controller,
                generation  = self.generation + 1,
                parents     = [self.name])
        self.children.append(clone.name)
        return clone

    def mate(self, other, speciation_distance=None):
        """
        Sexually reproduce these two individuals.
        """
        # Mate the genetic material.
        self_genome = self.get_genome()
        other_genome = other.get_genome()
        if isinstance(self_genome, Epigenome):
            child_genome = self_genome.mate(self.epigenome, other_genome, other.epigenome)
        elif isinstance(self_genome, Genome):
            child_genome = self_genome.mate(other_genome)
        else:
            raise TypeError(f"expected npc_maker.evo.Genome, found {type(self_genome)}")
        # Determine which species the child belongs to.
        if speciation_distance is None:
            species = self.species
        else:
            speciation_distance = float(speciation_distance)
            assert speciation_distance > 0
            species = None
            for parent in (self, other):
                if parent._genome.distance(child_genome) < speciation_distance:
                    species = parent.species
                    break
        # 
        child = Individual(child_genome,
                environment = self.environment,
                body_type   = self.body_type,
                species     = species,
                controller  = self.controller,
                generation  = max(self.generation, other.generation) + 1,
                parents     = [self.name, other.name])
        # Update the parent's child count.
        self.children.append(child.name)
        if self != other:
            other.children.append(child.name)
        return child

    def save(self, path=None) -> Path:
        """
        Serialize this individual to JSON and write it to a file.

        Argument path is the directory to save in.

        Returns the file path of the saved individual.
        """
        if not path:
            if self.path:
                path = self.path.parent
            else:
                path = tempfile.gettempdir()
        path = Path(path)
        if not path.exists():
            path.mkdir()
        assert path.is_dir()
        path = path.joinpath(self.name + ".indiv")
        # 
        genome = self.get_genome()
        if isinstance(genome, Genome):
            genome = genome.save()
        assert isinstance(genome, bytes)
        # Unofficial fields, in case of conflict these take lower precedence.
        data = dict(self.extra)
        # Required fields.
        data["telemetry"]   = self.telemetry
        data["epigenome"]   = self.epigenome
        data["parents"]     = self.parents
        data["children"]    = self.children
        data["species"]     = self.species
        data["generation"]  = self.generation
        # Optional fields.
        if self.name is not None:        data["name"]        = self.name
        if self.ascension is not None:   data["ascension"]   = self.ascension
        if self.environment is not None: data["environment"] = self.environment
        if self.body_type is not None:   data["body_type"]   = self.body_type
        if self.controller is not None:  data["controller"]  = self.controller
        if self.score is not None:       data["score"]       = self.score
        if self.birth_date is not None:  data["birth_date"]  = self.birth_date
        if self.death_date is not None:  data["death_date"]  = self.death_date
        # Convert paths to strings for JSON serialization.
        if self.controller is not None:
            data["controller"]    = list(data["controller"])
            data["controller"][0] = str(data["controller"][0])
        # 
        data = json.dumps(data)
        # Save to a hidden file, sync, and atomic move into place.
        fd, tmp_path = tempfile.mkstemp()
        file = os.fdopen(fd, "wb")
        file.write(data.encode("utf-8"))
        file.write(b'\x00')
        file.write(genome)
        file.flush()
        file.close()
        Path(tmp_path).rename(path)
        # 
        self.path = path
        return path

    @classmethod
    def load(cls, genome_cls, path) -> 'Individual':
        """
        Load a previously saved individual.

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
        metadata["path"] = path
        self = cls(None, **metadata)
        self._genome_cls = genome_cls
        return self

    def _load_genome(self):
        with open(self.path, 'rb') as file:
            data = file.read()
        text, binary = data.split(b'\x00', maxsplit=1)
        if hasattr(self._genome_cls, "load"):
            self._genome = self._genome_cls.load(binary)
        else:
            self._genome = self._genome_cls(binary)
