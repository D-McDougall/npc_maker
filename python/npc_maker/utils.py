from pathlib import Path
import shlex
import sys

def eprint(*args, **kwargs):
    """
    Print to stderr

    The NPC Maker uses stdin & stdout for communication using standardized
    message protocols. Unformatted diagnostic and error messages should be
    written to stderr using this function.
    """
    print(*args, **kwargs, file=sys.stderr, flush=True)

def clean_command(command):
    """
    Check user input
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
    program = Path(command[0]).expanduser().resolve()
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

def close_stdio():
    """
    Close the standard input and output channels

    This signals to the calling program that this program has quit 
    """
    if not sys.stdout.closed:
        sys.stdout.close()
    if _stdin is not None and not _stdin.closed:
        _stdin.close()
