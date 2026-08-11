"""
Evolutionary algorithms and supporting tools.
"""

# TODO: Reckon API differences between python and rust.
#   * Genome API: clone & mate vs asex & sex.
#   * Population: subclasses vs type enumeration.
#   * Population: python and rust use different file structures, rust version is better.
#   * Evolution: folded into Population class, rename Population to Evolution.
#   * Python population ignores individuals with invalid scores, rust sets score to -inf.

from pathlib import Path
import copy
import io
import json
import math
import os
import os.path
import pickle
import random
import shlex
import tempfile
import threading
import uuid

__all__ = (
    "Genome",
    "Epigenome",
    "Individual",
    "Population",
    "Generation",
    "Continuous",
    "Overflowing",
    "Evolution",
    "Replayer",
    "Neat",
)

def _copy_file(src_file, dst_dir):
    """
    Returns the destination file path.
    """
    src_file = Path(src_file)
    dst_dir = Path(dst_dir)
    assert src_file.is_file()
    assert dst_dir.is_dir()
    dst_file = dst_dir.joinpath(src_file.name)
    # 
    with open(src_file, 'rb') as src:
        data = src.read()
    # Write to temp file and atomic move into place.
    fd, tmp_path = tempfile.mkstemp()
    file = os.fdopen(fd, "wb")
    file.write(data)
    file.flush()
    file.close()
    Path(tmp_path).rename(dst_file)
    return dst_file

def _scan_dir(path):
    """
    Find saved individuals in the given directory.
    """
    path = Path(path)
    for file in path.iterdir():
        if file.suffix.lower() == ".indiv":
            yield file

class Genome:
    """
    Abstract class for implementing genetic algorithms.
    """
    def phenome(self) -> bytes:
        """
        Prepare the genome for sending it to the control system.
        """
        raise TypeError("abstract method called")

    def clone(self) -> 'Genome':
        """
        Asexually reproduce this genome.
        """
        return copy.deepcopy(self)

    def mate(self, other) -> 'Genome':
        """
        Sexually reproduce these two genomes.
        """
        raise TypeError("abstract method called")

    def distance(self, other) -> float:
        """
        Calculate the genetic distance.
        This is used for artificial speciation.
        """
        raise TypeError("abstract method called")

    def save(self) -> bytes:
        """
        Serialize the genome into a binary object for long-term storage.
        """
        return pickle.dumps(self)

    @classmethod
    def load(cls, save_data) -> 'Genome':
        """
        Recreate a genome from a saved object.
        """
        return pickle.loads(save_data)

class Epigenome(Genome):
    """
    Abstract class for implementing genetic algorithms with epigenetic modifications.
    """
    def phenome(self, epigenome) -> bytes:
        raise TypeError("abstract method called")

    def mate(self, epigenome, other, other_epigenome) -> 'Genome':
        raise TypeError("abstract method called")

class Individual:
    """
    Container for a distinct life-form and all of its associated data.
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

class Population:
    """
    Base class for groups of individuals. Stored together in a directory.

    This class manage individuals in a single population without replacement.
    Individuals are added but never removed. The population grows without bounds.
    """
    def __init__(self, genome_cls, path, population_size=0, leaderboard=0, hall_of_fame=0, score="score"):
        """
        Argument genome_cls should be either a subclass of Genome or a suitable
                 factory function to produce Genomes from byte string.

        Argument path is the directory to record data to. This class will
                 incorporate any existing data in the directory to resume after
                 a program shutdown.
                 If omitted this creates a temporary directory.

        Argument population_size is required for the leaderboard and hall_of_fame.

        Argument leaderboard is the number top performing of individuals to save.
                 If zero or None (the default) then the leaderboard is disabled.
                 Individuals are saved into the directory: path/leaderboard

        Argument hall_of_fame is the number of individuals in each generation /
                 cohort of the hall of fame. The best individual from each cohort
                 will be saved into the hall of fame.
                 If zero or None (the default) then the hall of fame is disabled.
                 Individuals are saved into the directory: path/hall_of_fame

        Argument score is an optional custom scoring function,
                 see method: Individual.get_custom_score
        """
        self._genome_cls = genome_cls
        self._path = self._clean_path(path)
        self._lock = threading.RLock()
        self._load_metadata()
        self._load_members()
        # Setup data recording.
        self._population_size = round(population_size) if population_size is not None else 0
        self._leaderboard     = round(leaderboard) if leaderboard is not None else 0
        self._hall_of_fame    = round(hall_of_fame) if hall_of_fame is not None else 0
        self._score           = score
        assert self._population_size >= 0
        assert self._leaderboard >= 0
        assert self._hall_of_fame >= 0
        if (self._leaderboard or self._hall_of_fame) and not self._population_size:
            raise ValueError("missing argument population_size")
        if self._leaderboard: self._load_leaderboard()
        if self._hall_of_fame: self._load_hall_of_fame()
        if self._population_size: self._init_generation()

    def _clean_path(self, path) -> 'Path':
        """
        Clean the path argument, ensure that it points to a directory.
        """
        if not path:
            self._tempdir   = tempfile.TemporaryDirectory() # Keep alive for the lifetime of this object.
            path            = self._tempdir.name
        path = Path(path)
        if not path.exists():
            path.mkdir()
        assert path.is_dir()
        return path

    def get_path(self):
        """
        Returns the path argument or temporary directory.
        """
        return self._path

    def get_leaderboard_path(self):
        """
        Returns a path or None if the leaderboard is disabled.
        """
        if self._leaderboard:
            return self._path.joinpath("leaderboard")
        else:
            return None

    def get_hall_of_fame_path(self):
        """
        Returns a path or None if the hall of fame is disabled.
        """
        if self._hall_of_fame:
            return self._path.joinpath("hall_of_fame")
        else:
            return None

    def _get_generation_path(self):
        """
        Get the staging directory for the next generation.
        """
        assert self._population_size
        return self._path.joinpath("generation")

    def _get_metadata_path(self):
        return self._path.joinpath("population.json")

    def _load_metadata(self) -> dict:
        metadata_path = self._get_metadata_path()
        if metadata_path.exists():
            with open(metadata_path, 'rt') as file:
                metadata = json.load(file)
        else:
            metadata = {}
        # Unpack the metadata into this structure.
        self._ascension = round(metadata.setdefault("ascension", 0))
        self._generation = round(metadata.setdefault("generation", 0))
        self._generation_size = round(metadata.setdefault("generation_size", 0))
        return metadata

    def _save_metadata(self, metadata={}):
        # Update the metadata.
        with self._lock:
            metadata["ascension"] = self._ascension
            metadata["generation"] = self._generation
            metadata["generation_size"] = self._generation_size
            # 
            with open(self._get_metadata_path(), 'wt') as file:
                json.dump(file, metadata)

    def _load_members(self):
        self._members = []
        for file in _scan_dir(self.get_path()):
            self._members.append(Individual.load(self._genome_cls, file))
        self._members.sort(key=lambda individual: individual.get_ascension())

    def _load_leaderboard(self):
        self._leaderboard_data = []
        leaderboard_dir = self.get_leaderboard_path()
        if not leaderboard_dir.exists():
            leaderboard_dir.mkdir()
        for file in _scan_dir(leaderboard_dir):
            self._leaderboard_data.append(Individual.load(self._genome_cls, file))
        self._sort_by_score(self._leaderboard_data)

    def _sort_by_score(self, data):
        """
        Sort individuals by score descending, with youth as the tie-breaker.
        """
        sort_key = lambda x: (x.get_custom_score(self._score), -x.get_ascension())
        data.sort(reverse=True, key=sort_key)

    def _load_hall_of_fame(self):
        self._hall_of_fame_data = []
        hall_of_fame_dir = self.get_hall_of_fame_path()
        if not hall_of_fame_dir.exists():
            hall_of_fame_dir.mkdir()
        for file in _scan_dir(hall_of_fame_dir):
            self._hall_of_fame_data.append(Individual.load(self._genome_cls, file))
        # Sort the individuals chronologically.
        self._hall_of_fame_data.sort(key=lambda x: x.get_ascension())

    def _init_generation(self):
        generation_dir = self._get_generation_path()
        if not generation_dir.exists():
            generation_dir.mkdir()

    def get_members(self) -> ['Individual']:
        """
        Returns the current members of the population.
        """
        with self._lock:
            return list(self._members)

    def get_leaderboard(self):
        """
        Returns a list of individuals, sorted descending by score,
        so that leaderboard[0] is the best individual.
        """
        if self._leaderboard:
            with self._lock:
                return list(self._leaderboard_data)
        else:
            return None

    def get_hall_of_fame(self):
        """
        Returns a list of individuals. These are the best scoring individuals
        from each generation, sorted chronologically by ascension,
        so that hall_of_fame[0] is the oldest individual and hall_of_fame[-1] is
        the youngest.
        """
        if self._hall_of_fame:
            with self._lock:
                return list(self._hall_of_fame_data)
        else:
            return None

    def get_best(self):
        """
        Returns the best individual ever.

        Only available if the leaderboard is enabled.
        Returns None if the leaderboard is empty.
        """
        with self._lock:
            if not self._leaderboard:
                raise ValueError("leaderboard is disabled")
            elif not self._leaderboard_data:
                return None
            else:
                return self._leaderboard_data[0]

    def get_ascension(self) -> int:
        """
        Returns the total number of individuals added to the population.
        """
        return self._ascension

    def get_generation(self) -> int:
        """
        Returns the number of generations that have completely passed.
        """
        return self._generation

    def _get_generation_members(self):
        return [Individual.load(self._genome_cls, file)
                for file in _scan_dir(self._get_generation_path())]

    def _prepare_individual(self, individual) -> 'Individual':
        """
        Clear the individual to enter this population, may return None.
        """
        if individual is None:
            return
        # 
        if isinstance(individual, str) or isinstance(individual, Path):
            individual = Individual.load(self._genome_cls, individual)
        else:
            assert isinstance(individual, Individual)
            assert individual._genome_cls is self._genome_cls
        # 
        individual.ascension = self._ascension
        self._ascension += 1
        if self._population_size:
            self._generation_size += 1
        # Ignore individuals who die without a valid score.
        score = individual.get_custom_score(self._score)
        if score is None or math.isnan(score) or score == -math.inf:
            return
        return individual

    def add(self, individual):
        """
        Insert a new individual into this population.

        This method may be called by multiple parallel threads of execution.
        """
        with self._lock:
            individual = self._prepare_individual(individual)
            if not individual:
                return
            # 
            individual.save(self._path)
            self._members.append(individual)
            # 
            if self._population_size:
                _copy_file(individual.path, self._get_generation_path())
                if self._generation_size >= self._population_size:
                    self._rollover()

    def _rollover(self):
        if self._leaderboard: self._rollover_leaderboard()
        if self._hall_of_fame: self._rollover_hall_of_fame()
        if self._population_size: self._rollover_generation()

    def _rollover_leaderboard(self):
        leaderboard_path = self.get_leaderboard_path()
        in_leaderboard = lambda path: path and path.is_relative_to(leaderboard_path)
        # Add the new generation to the leaderboard.
        self._leaderboard_data.extend(self._get_generation_members())
        self._sort_by_score(self._leaderboard_data)
        # Discard low performing individuals.
        while len(self._leaderboard_data) > self._leaderboard:
            individual = self._leaderboard_data.pop()
            if in_leaderboard(individual.path):
                individual.path.unlink()
        # Ensure all remaining individuals are saved to the leaderboard directory.
        for individual in self._leaderboard_data:
            if not in_leaderboard(individual.path):
                individual.path = _copy_file(individual.path, leaderboard_path)

    def _rollover_hall_of_fame(self):
        generation = self._get_generation_members()
        self._sort_by_score(generation)
        winners = generation[:self._hall_of_fame]
        winners.sort(key=lambda individual: individual.get_ascension())
        # 
        hall_of_fame_path = self.get_hall_of_fame_path()
        for individual in winners:
            individual.path = _copy_file(individual.path, hall_of_fame_path)
            self._hall_of_fame_data.append(individual)

    def _rollover_generation(self):
        self._generation += 1
        self._generation_size = 0
        for file in _scan_dir(self._get_generation_path()):
            file.unlink()

class Generation(Population):
    """
    Manages individuals in large batches, with an instantaneous rollover from
    one generation to the next.
    """
    def __init__(self, *args, **kwargs):
        Population.__init__(self, *args, **kwargs)
        assert self._population_size > 0, "missing argument population_size"

    def add(self, individual):
        with self._lock:
            individual = self._prepare_individual(individual)
            if not individual:
                return
            # 
            individual.save(self._get_generation_path())
            if self._generation_size >= self._population_size:
                self._rollover()

    def _rollover_generation(self):
        self._generation += 1
        self._generation_size = 0
        # Delete the current generation.
        for file in _scan_dir(self.get_path()):
            file.unlink()
        # Move the next generation into its place.
        for file in _scan_dir(self._get_generation_path()):
            file.rename(self.get_path() / file.name)
        # Update the members
        self._load_members()

class Continuous(Population):
    """
    Manages individuals in a circular queue, replacing the oldest member once full.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert self._population_size > 0, "missing argument population_size"

    def add(self, individual):
        with self._lock:
            while len(self._members) >= self._population_size:
                remove = self._members.pop(0)
                remove.path.unlink()
            super().add(individual)

class Overflowing(Population):
    """
    Replaces individuals at random once the population is full.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert self._population_size > 0, "missing argument population_size"

    def add(self, individual):
        with self._lock:
            while len(self._members) >= self._population_size:
                remove =  self._members.pop(random.randrange(len(self._members)))
                remove.path.unlink()
            super().add(individual)

class Evolution:
    """
    Abstract class for implementing evolutionary algorithms.

    Both the spawn and death methods should be thread-safe.
    """
    def spawn(self):
        """
        Returns a new individual to be born into the environment.
        """
        raise TypeError("abstract method called")

    def death(self, individual):
        """
        Notification of an individual's death.
        """
        raise TypeError("abstract method called")

class Replayer(Evolution):
    """
    Replay saved individuals
    """
    def __init__(self, genome_cls, path, select="Random", score="score"):
        """
        Argument path is the directory containing the saved individuals.
                 Individuals must have the file extension ".json"

        Argument select is a mate selection algorithm.

        Argument score is an optional custom scoring function.
        """
        self._genome_cls    = genome_cls
        self._path          = Path(path)
        self._lock          = threading.RLock()
        self._select        = select
        self._score         = score
        self._scan_time     = -1
        self._members       = []
        self._scores        = [] # Runs parallel to the members list.
        self._buffer        = [] # Queue of selected individuals wait to be born.

    def get_members(self):
        """
        Returns a list of individuals.
        """
        with self._lock:
            self._scan()
            return list(self._members)

    def spawn(self):
        with self._lock:
            self._scan()
            if not self._buffer:
                buffer_size = len(self._members)
                indices = self._select.select(buffer_size, self._scores)
                self._buffer.extend(self._members[i] for i in indices)
            individual = self._buffer.pop()
        # Reload into a new instance for the environment to modify.
        return Individual.load(self._genome_cls, individual.get_path())

    def death(self, individual):
        pass

    def _scan(self):
        if self._scan_time == os.path.getmtime(self._path):
            return
        self._members = [Individual.load(self._genome_cls, file)
                         for file in _scan_dir(self._path)]
        self._scores = [individual.get_custom_score(self._score)
                        for individual in self._members]
        self._buffer = []
        self._scan_time = os.path.getmtime(self._path)

class Neat(Evolution, Generation):
    """
    """
    def __init__(self, seed,
            population_size,
            species_distribution,
            mate_selection,
            score="score",
            path=None,
            leaderboard=0,
            hall_of_fame=0,):
        """
        Argument seed is the initial individual to begin evolution from.
        """
        # Clean and save the arguments.
        assert isinstance(seed, Individual)
        assert seed.get_controller()
        Generation.__init__(self, seed._genome_cls, path, population_size, leaderboard, hall_of_fame, score)
        self.species_distribution   = species_distribution
        self.mate_selection         = mate_selection
        self.score         = score
        # Setup our internal data structures.
        self._sort_species()
        # The zeroth generation only contains the seed, and is immediately
        # processed so the user never sees generation zero.
        if not self._members:
            if seed.score is None:
                seed.score = 0.0
            self.add(seed)
            self._rollover()

    def _sort_species(self):
        self._parents   = [] # Pairs of individuals, buffer of potential mates.
        self._species   = {} # Species UUID -> (avg-score, members-list).
        # Sort the individuals by species.
        for individual in self._members:
            self._species.setdefault(individual.get_species(), []).append(individual)
        # Calculate each species' average score.
        for uuid, members in self._species.items():
            score = sum(individual.get_custom_score(self._score) for individual in members) / len(members)
            self._species[uuid] = (score, members)

    def _rollover(self):
        super()._rollover()
        self._sort_species()

    def _sample(self):
        """
        Refill the _parents buffer.
        """
        # Distribute the offspring to species according to their average score.
        scores = [score for (score, members) in self._species.values()]
        selected = self.species_distribution.select(self._population_size, scores)
        # Count how many offspring were allocated to each species.
        histogram = [0 for _ in range(len(self._species))]
        for x in selected:
            histogram[x] += 1
        # Sample parents from each species.
        for (num_offspring, (_, members)) in zip(histogram, self._species.values()):
            scores = [individual.get_custom_score(self._score) for individual in members]
            for pair in self.mate_selection.pairs(num_offspring, scores):
                self._parents.append([members[index] for index in pair])
        # 
        random.shuffle(self._parents)

    def spawn(self):
        with self._lock:
            if not self._parents:
                self._sample()
            mother, father = self._parents.pop()
        if mother.get_custom_score(self._score) < father.get_custom_score(self._score):
            mother, father = father, mother
        return mother.mate(father)

    def death(self, individual):
        self.add(individual)
