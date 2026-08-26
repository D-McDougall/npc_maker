"""
Genetic Interface - tools for making and using genetic algorithms, which
analyze and manipulate genetic material
"""

from .indiv import Individual
from .utils import eprint, readline, readbytes, _API, _Instance
from pathlib import Path

__all__ = (
    "API",
    "eprint",
    "Genetic",
)

class API(_API):
    """
    Abstract class for implementing genetic algorithms
    """
    def asex(self, parent):
        """
        Abstract Method

        Asexually reproduce a genome

        Argument parent is an Individual
        """
        raise TypeError("abstract method called")

    def sex(self, *parents):
        """
        Abstract Method

        Sexually reproduce the given genomes

        Argument parents is a var-args list of Individuals
        """
        raise TypeError("abstract method called")

    def _dispatch(self, name, args):
        if name == "asex":
            assert len(args) == 1
            parent = Individual.load(args[0])
            self.asex(parent)
        elif name == "sex":
            assert len(args) >= 2
            parents = [Individual.load(path) for path in args]
            self.sex(*parents)
        else:
            self.custom(name, args)

class Genetic(_Instance):
    """
    An instance of a genetic algorithm

    This class provides methods for starting and using genetic programs.
    Each genetic program instance is executed in its own subprocess.
    This object's destruction causes the subprocess to terminate.
    """
    def asex(self, parent) -> (bytes, bytes):
        """
        Asexually reproduce the given individual

        Returns a pair of byte arrays (genome, phenome)
        """
        assert isinstance(parent, Individual)
        path = parent.get_path()
        if not path:
            path = parent.save()
        command = "[\"asex\", {}]\n".format(path)
        self._worker.stdin.write(command.encode("utf-8"))
        self._worker.stdin.flush()
        return self._read_response()

    def sex(self, *parents) -> (bytes, bytes):
        """
        Sexually reproduce the given individuals

        Returns a pair of byte arrays (genome, phenome)
        """
        paths = []
        for parent in parents:
            assert isinstance(parent, Individual)
            path = parent.get_path()
            if not path:
                path = parent.save()
            paths.append(path)
        command = ["sex"] + paths
        command = json.dumps(command)
        self._worker.stdin.write(command.encode("utf-8"))
        self._worker.stdin.flush()
        return self._read_response()

    def _read_response(self):
        response = readline()
        response = json.loads(response)
        genome_len  = int(response["genome"])
        phenome_len = int(response["phenome"])
        genome  = readbytes(genome_len)
        phenome = readbytes(phenome_len)
        return (genome, phenome)
