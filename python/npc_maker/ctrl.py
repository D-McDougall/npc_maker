"""
Controller Interface, for making and using control systems.
"""

from .utils import eprint, clean_command, readline, readbytes, writeline, writebytes
from pathlib import Path
import errno
import subprocess
import sys
import time

__all__ = (
    "API",
    "Controller",
    "eprint",
)

# TODO: Make a new version of Controller.get_outputs that is split into
# request/receive phases so that users can get outputs from many controllers
# all at once.

# TODO: Add a timeout for reading from the controller's stdin.

class Controller:
    """
    An instance of a controller

    This class provides methods for using controllers.

    Each controller instance is executed in a subprocesses.

    This object's destruction triggers the controller to terminate.
    """
    def __init__(self, environment, population, command, stderr=sys.stderr):
        """
        Argument environment is the path of the environment specification file.

        Argument population is a name and a key into the environment spec's "populations" table.

        Argument command is the command line invocation for the controller program.
                 It may either be a string, or a list or strings in which case the first
                 value is the program and the remaining strings are its command line arguments.

        Argument stderr is the file descriptor to use for the subprocess's stderr channel.
                 By default, the controller will inherit this process's stderr channel.
        """
        if isinstance(environment, dict):
            environment = environment["spec"]
        self.environment    = Path(environment)
        self.population     = str(population)
        self.command        = clean_command(command)
        self._ctrl          = subprocess.Popen(self.command,
            stdin           = subprocess.PIPE,
            stdout          = subprocess.PIPE,
            stderr          = stderr)
        # 
        self._ctrl.stdin.write("E{}\n".format(self.environment).encode("utf-8"))
        self._ctrl.stdin.write("P{}\n".format(self.population).encode("utf-8"))

    def is_alive(self):
        """
        Check if the controller subprocess is still running or if it has exited.
        """
        return self._ctrl.returncode is None

    def get_environment(self):
        """
        Get the "environment" argument.
        """
        return self.environment

    def get_population(self):
        """
        Get the "population" argument.
        """
        return self.population

    def get_command(self):
        """
        Get the "command" argument.
        """
        return " ".join(str(arg) for arg in self.command)

    def same_command(self, command):
        """
        Check if this controller is running the given command.
        """
        return self.command == clean_command(command)

    def __repr__(self):
        return "<npc_maker.ctrl.Controller: {}>".format(repr(self.get_command()))

    def genome(self, value):
        """
        Initialize the control system with a new genome.
        This discards the currently loaded model.

        Argument value is a byte array
        """
        if isinstance(value, str):
            value = bytes(value, encoding="utf-8")
        assert isinstance(value, bytes)
        self._ctrl.stdin.write("G{}\n".format(len(value)).encode("utf-8"))
        self._ctrl.stdin.write(value)

    def reset(self):
        """
        Reset the control system to its initial state.
        """
        self._ctrl.stdin.write(b"R\n")

    def advance(self, dt):
        """
        Advance the control system's internal state.

        Argument dt is in units of seconds.
        """
        dt = float(dt)
        self._ctrl.stdin.write("A{}\n".format(dt).encode("utf-8"))

    def set_input(self, gin, value):
        """
        Write a single value to a GIN in the controller.
        """
        value = str(value)
        gin   = int(gin)
        assert '\n' not in value
        assert gin >= 0
        self._ctrl.stdin.write("I{}\n{}\n".format(gin, value).encode("utf-8"))

    def set_binary(self, gin, binary):
        """
        Write an array of bytes to a GIN in the controller.
        """
        # binary = bytes(binary)
        gin = int(gin)
        assert isinstance(binary, bytes)
        assert gin >= 0
        self._ctrl.stdin.write("B{}\n{}\n".format(gin, len(binary)).encode("utf-8"))
        self._ctrl.stdin.write(binary)

    def get_outputs(self, gin_list):
        """
        Retrieve a list of outputs, as identified by their GIN.

        This method blocks on IO.
        """
        return_list = True
        if hasattr(gin_list, "__iter__"):
            gin_list    = list(gin_list)
        else:
            gin_list    = [gin_list]
            return_list = False
        # Request the outputs.
        for gin in gin_list:
            gin = int(gin)
            assert gin >= 0
            self._ctrl.stdin.write("O{}\n".format(gin).encode("utf-8"))
        self._ctrl.stdin.flush()
        # Receive the outputs.
        outputs = {}
        while len(outputs) < len(gin_list):
            message = self._ctrl.stdout.readline().decode("utf-8").lstrip()
            if not message:
                continue
            msg_type = message[0]
            msg_body = message[1:]
            assert msg_type.upper() == 'O'
            gin = int(msg_body.strip())
            outputs[gin] = self._ctrl.stdout.readline().decode("utf-8")
        assert set(outputs) == set(gin_list)
        if return_list:
            return outputs
        else:
            return outputs.popitem()[1]

    def save(self):
        """
        Request the current state of the controller.
        """
        path = Path(path)
        assert '\n' not in str(path)
        self._ctrl.stdin.write(b"S\n")
        self._ctrl.stdin.flush()
        # TODO: Wait for the controller's response.
        raise NotImplementedError
        return save_state

    def load(self, save_state):
        """
        Load a previously saved controller.
        """
        assert isinstance(save_state, bytes)
        self._ctrl.stdin.write("L{}\n".format(len(save_state)).encode("utf-8"))
        self._ctrl.stdin.write(save_state)

    def custom(self, message_type, message_body):
        """
        Send a custom message to the controller using a new message type.
        """
        message_type = str(message_type).strip().upper()
        assert len(message_type) == 1
        assert message_type not in "EPGRAIBOSL"
        message_body = str(message_body)
        assert '\n' not in message_body
        self._ctrl.stdin.write("{}{}\n".format(message_type, message_body).encode("utf-8"))

    def __del__(self):
        if hasattr(self, "_ctrl") and not self._ctrl.stdin.closed:
            try:
                self._ctrl.stdin.close()
            except BrokenPipeError:
                pass
            except IOError as error:
                if error.errno == errno.EPIPE:
                    pass

_environment = None
_population  = None

def _parse_message():
    # Ignore leading white space and empty lines.
    while True:
        message = readline()
        message = message.lstrip()
        if message:
            break
        # 
    msg_type = message[0].upper()
    msg_body = message[1:]
    return (msg_type, msg_body)

class API:
    """
    Abstract class for implementing controllers.
    """
    def main(self):
        """
        Run a controller program.

        This function never returns!
        """
        global _environment, _population
        while True:
            try:
                msg_type, msg_body = _parse_message()
            except EOFError:
                break

            if msg_type == "I":
                gin   = int(msg_body)
                value = readline()
                self.set_input(gin, value)

            elif msg_type == "O":
                gin   = int(msg_body)
                value = str(self.get_output(gin))
                assert '\n' not in value
                reply = f"O{gin}\n{value}"
                writeline(reply)

            elif msg_type == "B":
                gin             = int(msg_body)
                num_bytes       = readline()
                binary          = readbytes(num_bytes)
                self.set_binary(gin, binary)

            elif msg_type == "A":
                dt = float(msg_body)
                self.advance(dt)

            elif msg_type == "R":
                self.reset()

            elif msg_type == "G":
                num_bytes = int(msg_body)
                binary    = readbytes(num_bytes)
                self.genome(_environment, _population, binary)

            elif msg_type == "E":
                _environment = Path(msg_body)

            elif msg_type == "P":
                _population = msg_body

            elif msg_type == "S":
                save_state = self.save()
                reply = f"S{len(save_state)}"
                writeline(reply)
                writebytes(save_state)

            elif msg_type == "L":
                num_bytes  = int(msg_body)
                save_state = readbytes(num_bytes)
                self.load(save_state)

            else:
                self.custom(msg_type, msg_body)

        self.quit()

    def genome(self, environment: 'Path', population: str, value: bytes):
        """
        Abstract Method

        Discard the current model and load a new one.

        Argument environment is the file-path of the environment specification file.

        Argument population is a key into the environment specification's "populations" table.

        Argument value is the parameters for the new controller.

        The environment and population will not change during the lifetime of
        the controller's computer process.
        """
        raise TypeError("abstract method called")

    def reset(self):
        """
        Abstract Method

        Reset the currently loaded model to it's initial state.
        """
        raise TypeError("abstract method called")

    def advance(self, dt: float):
        """
        Abstract Method

        Argument dt is the time period to advance over, measured in seconds.
        """
        raise TypeError("abstract method called")

    def set_input(self, gin: int, value: str):
        """
        Abstract Method

        Receive data from the environment into the controller.

        Argument gin references a sensory input interface.
        Argument value is a UTF-8 string.
        """
        raise TypeError("abstract method called")

    def set_binary(self, gin: int, binary: bytes):
        """
        Abstract Method

        Receive an array of bytes from the environment into the controller.

        Argument gin references a binary input interface.
        Argument bytes is a byte array.
        """
        raise TypeError("unsupported operation")

    def get_output(self, gin: int) -> str:
        """
        Abstract Method

        The environment has requested that the controller send it an output.

        Argument gin references a motor output interface.
        """
        raise TypeError("abstract method called")

    def save(self) -> bytes:
        """
        Abstract Method

        Return the current state of the controller.
        """
        raise TypeError("unsupported operation")

    def load(self, save_state: bytes):
        """
        Abstract Method

        Load a previously saved controller state.
        """
        raise TypeError("unsupported operation")

    def custom(self, message_type: str, message_body: str):
        """
        Abstract Method

        Receive a custom message from the controller using a new message type.

        Argument message_type is a single capital letter, which is not already
        in use by the protocol.

        Argument message_body is a UTF-8 string.
        """
        raise TypeError(f"unsupported operation (message type \"{message_type}\")")

    def quit(self):
        """
        Abstract Method, Optional

        This method is called just before the controller process exits.
        """
        pass
