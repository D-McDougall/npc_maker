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

def _clean_command(command):
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

def _readline():
    global _stdin, _buffer
    read_size = 1000
    if _stdin is None:
        _stdin = open(sys.stdin.fileno(),  mode='rb', buffering=0)
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

def _readbytes(num_bytes):
    global _stdin, _buffer
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
