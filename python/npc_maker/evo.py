"""
Evolution Interface - tools for making and using evolutionary algorithms,
which decide which individuals to mate together.
"""

from .indiv import Individual
from .utils import eprint, writeline, _API, _Instance
from pathlib import Path
import json

__all__ = (
    "API",
    "eprint",
    "Evolution",
)

class API(_API):
    """
    Abstract base class for implementing evolution programs
    """
    def spawn(self) -> '[Individual]':
        """
        Abstract Method

        Pick some number of parents to be mated together

        Returns a list of Individuals or Paths to ".indiv" files
        """
        raise TypeError("abstract method called")

    def death(self, individual: 'Individual'):
        """
        Abstract Method

        Inform the evolutionary algorithm the given individual died and left
        the environment.
        """
        raise TypeError("abstract method called")

    def _dispatch(self, name, args):
        if name == "spawn":
            assert len(args) == 0
            parents = self.spawn()
            # Clean up the user's return value
            def indiv_to_path(retval):
                if isinstance(reval, Individual):
                    reval.save()
                    parents[index] = reval.get_path()
                else:
                    parents[index] = Path(reval)
            parents = list(map(indiv_to_path, parents))
            # 
            output = json.dumps(parents)
            assert '\n' not in output
            writeline(output)
        elif name == "death":
            assert len(args) == 1
            individual = Individual.load(args[0])
            self.death(individual)
        else:
            self.custom(name, args)

class Evolution(_Instance):
    """
    """
    def spawn(self) -> '[Individual]':
        """
        """
        1/0

    def death(self, individual):
        """
        """
        1/0
