from pathlib import Path
import errno
import shlex
import subprocess
import sys

def eprint(*args, **kwargs):
    """
    Print to stderr

    The NPC Maker uses stdin & stdout for communication using standardized
    message protocols. Unformatted diagnostic and error messages should be
    written to stderr using this function.
    """
    print(*args, **kwargs, file=sys.stderr, flush=True)

def clean_command(command, resolve=True) -> [str]:
    """
    Check user input executable command strings
    """
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
    program = Path(command[0])
    if resolve:
        program = program.expanduser().resolve()
    command[0] = program
    for index in range(1, len(command)):
        arg = command[index]
        if not isinstance(arg, bytes) and not isinstance(arg, str):
            command[index] = str(arg)
    return command

_stdin       = None
_buffer      = b""

def _init_stdin():
    global _stdin
    if _stdin is None:
        fd = sys.stdin.fileno()
        _stdin = open(fd,  mode='rb', buffering=0)
        # sys.stdin.close()

def readline():
    """
    Read one line from the standard input channel

    Do not mix calls to "readline()" with the built-in "input()" function!
    """
    global _stdin, _buffer
    _init_stdin()
    read_size = 1000
    if b"\n" not in _buffer:
        while True:
            chunk = _stdin.read(read_size)
            # Yield execution if waiting for data.
            if chunk is None:
                time.sleep(0)
                continue
            # Check for EOF.
            if len(chunk) == 0:
                raise EOFError("stdin closed")
            # Incorporate the chunk into our internal buffer.
            _buffer += chunk
            if b"\n" in chunk:
                break
    line, _buffer = _buffer.split(b"\n", maxsplit=1)
    line = line.decode("utf-8")
    return line

def readbytes(num_bytes):
    """
    Read an exact number of bytes from the standard input channel

    Do not mix calls to "readbytes()" with the built-in "input()" function!
    """
    global _stdin, _buffer
    _init_stdin()
    while len(_buffer) < num_bytes:
        chunk = _stdin.read(num_bytes - len(_buffer))
        # Yield execution if waiting for data.
        if chunk is None:
            time.sleep(0)
            continue
        # Check for EOF.
        if len(chunk) == 0:
            raise EOFError("stdin closed")
        _buffer += chunk
    data    = _buffer[:num_bytes]
    _buffer = _buffer[num_bytes:]
    return data

def writeline(line):
    """
    Write text to the standard output channel, terminated by a new-line and flushed
    """
    line = str(line)
    data = line.encode('utf-8')
    data += b'\n'
    writebytes(data)

def writebytes(data):
    """
    Write a binary array to the standard output channel, and flush it
    """
    # If the stdout channel is simply closed, then quietly exit by closing stdin.
    # For other more abnormal conditions raise the error to the user.
    assert isinstance(data, bytes)
    try:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
    except BrokenPipeError:
        close_stdio()
    except ValueError:
        if sys.stdout.closed:
            close_stdio()
        else:
            raise

def close_stdio():
    """
    Close the standard input and output channels

    This signals to the calling program that this program has quit 
    """
    if not sys.stdout.closed:
        sys.stdout.close()
    if _stdin is not None and not _stdin.closed:
        _stdin.close()

class _API:
    """
    Abstract base class for implementing API programs
    """
    def main(self):
        """
        Run the API program

        This never returns!

        Example Usage:
        >>> if __name__ == "__main__":
        >>>     api = MyAPI()
        >>>     api.main()
        """
        while True:
            try:
                command_str = readline()
            except EOFError:
                break
            command_str = command_str.strip()
            if not command_str:
                continue
            command_list = json.loads(command_str)
            assert isinstance(command_list, list)
            assert len(command_list) > 0
            command_name = command_list[0]
            command_args = command_list[1:]
            assert isinstance(command_name, str)
            self._dispatch(command_name, command_list)
        self.quit()

    def _dispatch(self, name: str, args: list):
        raise TypeError("abstract method called")

    def custom(self, name: str, args: list) -> object:
        """
        Abstract Method, Optional

        Receive a custom message. Custom messages are transmitted as
        single-line JSON Arrays, where the first value specifies the
        message-type, the remaining values are the message's fields.

        Returns an arbitrary value, which will be encoded into a single-line
        JSON object for transmission
        """
        raise TypeError(f"unsupported operation \"{name}\"")

    def quit(self):
        """
        Abstract Method, Optional

        This method is called just before the computer process exits.
        """
        pass

class _Instance:
    """
    Abstract base class for creating and interacting with API programs,
    which this runs in a subprocess

    Destroying this object closes the subprocess's stdin & stdout
    """
    def __init__(self, command: [str], stderr=sys.stderr):
        """
        Argument command is the command line invocation for the API program.
        This accepts either a shell-command string, or a list or strings in
        which case the first value is the program and the remaining strings
        are its command line arguments.

        Argument stderr is the file descriptor to use for the subprocess's
        stderr channel. By default, the API program will inherit this
        process's stderr channel.
        """
        self.command    = clean_command(command)
        self._worker    = subprocess.Popen(self.command,
            stdin       = subprocess.PIPE,
            stdout      = subprocess.PIPE,
            stderr      = stderr)

    def is_alive(self):
        """
        Check if the API subprocess is still running or if it has exited
        """
        return self._worker.returncode is None

    def get_command(self):
        """
        Get the "command" argument
        """
        return " ".join(str(arg) for arg in self.command)

    def same_command(self, command):
        """
        Check if this API program is running the given command
        """
        return self.command == _clean_ctrl_command(command)

    def get_stderr(self):
        """
        Get the standard error channel from the subprocess
        """
        return self._worker.stderr

    def __repr__(self):
        mod = type(self).__module__
        cls = type(self).__name__
        return "<{}.{}: {}>".format(mod, cls, repr(self.get_command()))

    def custom(self, name, arguments) -> object:
        """
        Send a custom message to the genetic algorithm

        Argument name is any string not already in use by the protocol.
                 The name identifies which command / operation to perform.

        Argument arguments is a list of python objects, which are
                 converted to a single line of JSON for transmission.

        Returns an object received from the API program
        """
        name = str(name)
        arguments = list(arguments)
        command = [name] + arguments
        command = json.dumps(command)
        assert '\n' not in command
        self._worker.stdin.write(command.encode("utf-8"))
        response = readline()
        return json.loads(response)

    def __del__(self):
        if hasattr(self, "_worker"):
            for pipe in (self._worker.stdin, self._worker.stdout):
                if not pipe.closed:
                    try:
                        pipe.close()
                    except BrokenPipeError:
                        pass
                    except IOError as error:
                        if error.errno == errno.EPIPE:
                            pass
