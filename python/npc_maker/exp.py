"""
Experiment Interface, for whole-system configuration of the NPC Maker
"""

import json
from pathlib import Path

class Experiment:
    """
    Container for experiment configuration files (.exp)
    """
    def __init__(self, path):
        """
        Load an experiment configuration file (.exp) from path
        """
        self.path = Path(path)
        with open(self.path, 'rt') as file:
            config = json.load(file)
        self.name        = config.get("name", "")
        self.description = config.get("description", "")
        self.computers   = config.get("computers", [])
        self.environment = config["environment"]
        self.organisms   = config["organisms"]
        assert isinstance(self.name, str)
        assert isinstance(self.description, str)
        assert isinstance(self.computers, list)
        assert isinstance(self.organisms, list)
        assert isinstance(self.environment, list)
        assert all(isinstance(arg, str) for arg in self.environment)
        self.computers = [Computer(data) for data in self.computers]
        self.organisms = [Organism(data) for data in self.organisms]

class Computer:
    def __init__(self, config):
        1/0

class Organism:
    def __init__(self, config):
        self.body_type = config.get("body_type", "")
        self.evolution = config.get("evolution", "")
        self.genetics = config.get("genetics", "")
