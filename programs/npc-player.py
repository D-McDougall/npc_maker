"""
Evolutionary algorithms and supporting tools.
"""

from npc_maker.indiv import Individual
from npc_maker.evo import API, eprint
from pathlib import Path
import json
import math
import os
import os.path
import tempfile
import threading

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

class Replayer(API):
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
        return Individual.load(individual.get_path())

    def death(self, individual):
        pass

    def _scan(self):
        if self._scan_time == os.path.getmtime(self._path):
            return
        self._members = [Individual.load(file)
                         for file in _scan_dir(self._path)]
        self._scores = [individual.get_custom_score(self._score)
                        for individual in self._members]
        self._buffer = []
        self._scan_time = os.path.getmtime(self._path)
