"""
Evolutionary algorithms and supporting tools.
"""

# TODO: Reckon API differences between python and rust.
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
