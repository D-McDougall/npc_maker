"""
Genetic Interface, for analyzing and manipulating genetic material
"""

from evo import Individual
from pathlib import Path
import errno
import subprocess
import sys
import time
from utils import eprint, clean_command, readline, readbytes

__all__ = (
    "API",
    "eprint",
    "GeneticAlgorithm",
)

class GeneticAlgorithm:
    """
    An instance of a genetic algorithm.

    This class provides methods for using genetic algorithms.

    Each genetic algorithm instance is executed in a subprocesses.

    This object's destruction triggers the genetic algorithm to terminate.
    """
    def __init__(self, command: [str], stderr=sys.stderr):
        """
        Argument command is the command line invocation for the genetic
        		 algorithm program. It may either be a string, or a list or
        		 strings in which case the first value is the program and the
        		 remaining strings are its command line arguments.

        Argument stderr is the file descriptor to use for the subprocess's
        		 stderr channel. By default, the genetic algorithm will
        		 inherit this process's stderr channel.
        """
        self.command 	= utils.clean_command(command)
        self._worker    = subprocess.Popen(self.command,
            stdin       = subprocess.PIPE,
            stdout      = subprocess.PIPE,
            stderr      = stderr)

    def is_alive(self):
        """
        Check if the genetic algorithm subprocess is still running or if it
        has exited.
        """
        return self._worker.returncode is None

    def get_command(self):
        """
        Get the "command" argument.
        """
        return " ".join(str(arg) for arg in self.command)

    def same_command(self, command):
        """
        Check if this genetic algorithm is running the given command.
        """
        return self.command == _clean_ctrl_command(command)

    def __repr__(self):
        return "<npc_maker.gen.GeneticAlgorithm: {}>".format(repr(self.get_command()))

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

    def custom(self, name, arguments) -> object:
        """
        Send a custom message to the genetic algorithm

        Argument name is any string not already in use by the protocol.
        		 The name identifies which command / operation to perform.

	    Argument arguments is a list of python objects, which are
	    		 converted to JSON for transmission.

		Returns an object received from the genetic algorithm
        """
        name = str(name)
        assert name not in ["asex", "sex"]
        arguments = list(arguments)
        command = [name] + arguments
        command = json.dumps(command)
        assert '\n' not in command
        self._worker.stdin.write(command.encode("utf-8"))
        response = readline()
        return json.loads(response)

    def __del__(self):
        if hasattr(self, "_worker") and not self._worker.stdin.closed:
            try:
                self._worker.stdin.close()
            except BrokenPipeError:
                pass
            except IOError as error:
                if error.errno == errno.EPIPE:
                    pass

class API:
    """
    Abstract class for implementing genetic algorithms
    """
    def main(self):
        """
        Run a genetic algorithm program

        This function never returns!
        """
        while True:
            try:
                command_str = input()
            except EOFError:
                break
            command_list = json.loads(command_str.strip())
            assert isinstance(command_list, list)
            assert len(command_list) > 0
            command_name = command_list[0]
            command_args = command_list[1:]
            if command_name == "asex":
            	assert len(command_args) == 1
            	parent = Individual.load(bytes, command_args[0])
            	self.asex(parent)
            elif command_name == "sex":
            	assert len(command_args) >= 2
            	parents = [Individual.load(bytes, path) for path in command_args]
            	self.sex(*parents)
            else:
	            self.custom(command_list)
        self.quit()

    def asex(self, parent):
        """
        Abstract Method

        Asexually reproduce a genome

        Argument parent is an Individual.
        """
        raise TypeError("abstract method called")

    def sex(self, *parents):
        """
        Abstract Method

        Sexually reproduce the given genomes

        Argument parents are Individuals.
        """
        raise TypeError("abstract method called")

    def custom(self, message: list) -> object:
        """
        Abstract Method

        Receive a custom message from the evolutionary algorithm.
        Custom messages are transmitted as single-line JSON objects.

        Returns an arbitrary value, which will be encoded into a single-line
        JSON object for transmission.
        """
        raise TypeError(f"unsupported operation \"{message[0]}\"")

    def quit(self):
        """
        Abstract Method, Optional

        This method is called just before the genetic algorithm's process exits.
        """
        pass
