"""
Environment Interface, for making and using environments.

All global functions in this module are for implementing environment programs.
"""

from pathlib import Path
import collections
import datetime
import json
import os
import subprocess
import sys
import tempfile

__all__ = (
    "Specification",
    "Environment",
    "eprint",
    "get_args",
    "input",
    "spawn",
    "mate",
    "score",
    "telemetry",
    "death",
    "SoloAPI",
)

def _timestamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(" ", 'milliseconds')

def Specification(env_spec_path):
    """
    Load an environment specification from file.
    """
    # Clean up the filesystem path argument.
    env_spec_path = Path(env_spec_path).expanduser().resolve()
    # Read the file into memory.
    with open(env_spec_path, 'rt') as env_spec_file:
        env_spec_data = env_spec_file.read()
    # Parse the file into a JSON object.
    try:
        env_spec = json.loads(env_spec_data)
    except json.decoder.JSONDecodeError as err:
        raise ValueError(f"JSON syntax error in \"{env_spec_path}\" {err}")
    # 
    _env_spec_check_fields(env_spec, ("name", "path", "body_types",), ("spec",))
    # Automatically save the env_spec path into the env_spec.
    env_spec["spec"] = env_spec_path
    # Clean up the environment command line invocation.
    env_path = Path(env_spec["path"])
    # Environment program paths are relative to the env_spec file.
    if not env_path.is_absolute():
        env_path = env_spec_path.parent.joinpath(env_path)
    # env_path = env_path.resolve()
    env_spec["path"] = env_path
    # Allow certain undocumented abbreviations.
    _alias_fields(env_spec, [
        ("desc", "description"),
        ("descr", "description"),
        ("bodies", "body_types"),])
    # Insert default values for missing keys.
    env_spec.setdefault("settings", [])
    env_spec.setdefault("description", "")
    # Check first level data types.
    assert isinstance(env_spec["name"], str)
    assert isinstance(env_spec["body_types"], list)
    assert isinstance(env_spec["settings"], list)
    assert isinstance(env_spec["description"], str)
    # Check body_type objects.
    for body_type in env_spec["body_types"]:
        _env_spec_check_fields(body_type, ("name", "sensors", "motors",))
        _alias_fields(body_type, [
            ("desc", "description"),
            ("descr", "description"),])
        # Insert default values for missing keys.
        body_type.setdefault("description", "")
        # Check the body_type's data types.
        assert isinstance(body_type["name"], str)
        assert isinstance(body_type["sensors"], list)
        assert isinstance(body_type["motors"], list)
        assert isinstance(body_type["description"], str)
        # Check the interface objects.
        for interface in body_type["sensors"] + body_type["motors"]:
            _env_spec_check_fields(interface, ("id", "name",))
            _alias_fields(interface, [
                ("desc", "description"),
                ("descr", "description"),])
            interface.setdefault("description", "")
            assert isinstance(interface["name"], str)
            assert isinstance(interface["id"], int)
            assert isinstance(interface["description"], str)
        # Check interface names are unique.
        dupl            = lambda data: len(data) > len(set(data))
        input_names     = [interface["name"] for interface in body_type["sensors"]]
        input_ids       = [interface["id"]   for interface in body_type["sensors"]]
        output_names    = [interface["name"] for interface in body_type["motors"]]
        output_ids      = [interface["id"]   for interface in body_type["motors"]]
        if dupl(input_names):  raise ValueError("duplicate sensor name in environment specification")
        if dupl(input_ids):    raise ValueError("duplicate sensor id in environment specification")
        if dupl(output_names): raise ValueError("duplicate motor name in environment specification")
        if dupl(output_ids):   raise ValueError("duplicate motor id in environment specification")
    # Check body_type names are unique.
    body_names = [body_type["name"] for body_type in env_spec["body_types"]]
    if len(body_names) != len(set(body_names)):
        raise ValueError("duplicate body type name in environment specification")
    # Check settings objects.
    for item in env_spec["settings"]:
        _clean_settings(item)
    # Check settings names are unique.
    settings_names = [item["name"] for item in env_spec["settings"]]
    if len(settings_names) != len(set(settings_names)):
        raise ValueError("duplicate settings name in environment specification")
    # 
    return env_spec

def _env_spec_check_fields(json_object, require_fields=(), reserved_fields=()):
    # Check that it's a JSON object.
    if not isinstance(json_object, dict):
        raise ValueError(f"expected a JSON object in environment specification")
    # Check for required and forbidden keys.
    for field in require_fields:
        if field not in json_object:
            raise ValueError(f'missing field "{field}" in environment specification')
    for field in reserved_fields:
        if field in json_object:
            raise ValueError(f'reserved field "{field}" in environment specification')

def _alias_fields(json_object, aliases):
    for (abrv, attr) in aliases:
        if abrv in json_object:
            if attr in json_object:
                raise ValueError(
                    f"duplicate fields: \"{abrv}\" and \"{attr}\" in environment specification")
            json_object[attr] = json_object.pop(abrv)

def _clean_settings(item):
    """ Settings items are strictly / rigidly structured. """
    _env_spec_check_fields(item, ("name", "type", "default",))
    num_fields = 3

    _alias_fields(item, [
        ("desc", "description"),
        ("descr", "description"),])
    item["description"] = item.get("description", "")
    num_fields += 1

    # Normalize the type aliases.
    if   item["type"] == "float": item["type"] = "Real"
    elif item["type"] == "int":   item["type"] = "Integer"
    elif item["type"] == "bool":  item["type"] = "Boolean"
    elif item["type"] == "enum":  item["type"] = "Enumeration"
    elif item["type"] == "str":   item["type"] = "String"
    assert item["type"] in ("Real", "Integer", "Boolean", "Enumeration", "String")

    # Clean each type variant.
    if item["type"] == "Boolean":
        item["default"] = bool(item["default"])

    elif item["type"] in ("Real", "Integer"):
        _env_spec_check_fields(item, ("minimum", "maximum",))
        num_fields += 2
        if item["type"] == "Real":
            item["default"] = float(item["default"])
            item["minimum"] = float(item["minimum"])
            item["maximum"] = float(item["maximum"])
        elif item["type"] == "Integer":
            item["default"] = int(item["default"])
            item["minimum"] = int(item["minimum"])
            item["maximum"] = int(item["maximum"])
        assert item["minimum"] <= item["default"]
        assert item["maximum"] >= item["default"]

    elif item["type"] == "Enumeration":
        _env_spec_check_fields(item, ("values",))
        num_fields += 1
        item["default"] = str(item["default"])
        item["values"]  = [str(variant) for variant in item["values"]]
        assert len(item["values"]) == len(set(item["values"]))
        assert item["default"] in item["values"]

    elif item["type"] == "String":
        item["default"] = str(item["default"])

    if len(item) > num_fields:
        name = item["name"]
        raise ValueError(
            f"unexpected attributes on setting \"{name}\" in environment specification")

def _cast_env_settings(env_spec, settings):
    """ Cast the command line argument settings to the data type specified in the environment specification. """
    settings_list = env_spec.get("settings")
    if settings_list is None:
        return
    settings_dict = {spec["name"]: spec for spec in settings_list}
    for name, value in settings.items():
        if spec := settings_dict.get(name):
            data_type = spec.get("type")
            if data_type == "Real" or data_type == "float":
                settings[name] = float(value)
            elif data_type == "Integer" or data_type == "int":
                settings[name] = int(value)
            elif data_type == "Boolean" or data_type == "bool":
                if isinstance(value, str):
                    value = value.lower()
                    if   value == "false": value = False
                    elif value == "true":  value = True
                settings[name] = bool(value)
            elif data_type == "Enumeration" or data_type == "enum":
                settings[name] = str(value)
            elif data_type == "String" or data_type == "str":
                settings[name] = str(value)

def _help_message(env_spec):
    # Usage.
    pass

    # Title and description.
    message = env_spec["name"] + " Environment\n\n"
    desc = env_spec.get("description", "")
    if desc:
        message += desc + "\n\n"

    # Summary of body_types.
    pass

    # Summary of command line arguments.
    settings = env_spec.get("settings", [])
    if settings:
        name_field      = max(len(item["name"]) for item in settings)
        default_field   = max(len(str(item["default"])) for item in settings)
        name_field      = max(name_field,    len("Argument"))
        default_field   = max(default_field, len("Default"))
        message += f"Type | Argument | Default | Range (inclusive) | Description \n"
        message +=  "-----+----------+---------+-------------------+-------------\n"
        for item in settings:
            if   item["type"] == "Real":        line = "real | "
            elif item["type"] == "Integer":     line = "int  | "
            elif item["type"] == "Boolean":     line = "bool | "
            elif item["type"] == "Enumeration": line = "enum | "
            elif item["type"] == "String":      line = "str  | "
            line += item["name"].ljust(name_field) + " | "
            line += str(item["default"]).ljust(default_field) + " | "
            if item["type"] == "Real" or item["type"] == "Integer":
                line += str(item["minimum"]) + " - " + str(item["maximum"])
            elif item["type"] == "Enumeration":
                line += ", ".join(item["values"])
            line += " | "
            line += item["description"]
            message += line + "\n"
    return message

def eprint(*args, **kwargs):
    """
    Print to stderr

    The NPC Maker uses the environment program's stdin & stdout to communicate
    with the main program via a standardized JSON-based protocol. Unformatted
    diagnostic and error messages should be written to stderr using this function.
    """
    print(*args, **kwargs, file=sys.stderr, flush=True)

def get_args():
    """
    Read the command line arguments for an NPC Maker environment program.

    Returns a tuple of (environment-specification, graphics-mode, settings-dict)
    """
    def error(message):
        eprint(message)
        sys.exit(1)
    # Read the command line arguments.
    if len(sys.argv) < 2:
        error("missing argument: environment specification")
    program = sys.argv[0]
    # Read the environment specification file.
    try:
        env_spec = Specification(sys.argv[1])
    except Exception as err:
        error(err)
    # Print help message and exit.
    if '-h' in sys.argv or '--help' in sys.argv:
        error(_help_message(env_spec))
    # Read the graphics mode.
    if len(sys.argv) >= 3:
        mode  = sys.argv[2].strip().lower()
    else:
        mode  = 'graphical' # Default setting.
    # Check the graphics mode.
    if mode not in ['graphical', 'headless']:
        error(f"argument error: expected either \"graphical\" or \"headless\", got \"{mode}\"")
    # Read the user's settings.
    settings = sys.argv[3:]
    if len(settings) % 2 == 1:
        error("argument error: odd number of settings, expected key-value pairs")
    settings = zip(settings[::2], settings[1::2])
    # Overwrite the default values with the user's settings.
    defaults = {item['name']: item['default'] for item in env_spec.get('settings', [])}
    for item, value in settings:
        if item not in defaults:
            error(f"argument error: unexpected parameter \"{item}\"")
        defaults[item] = value
    _cast_env_settings(env_spec, defaults)
    return (env_spec, mode, defaults)

def input():
    """
    Read the next individual from the evolution program, blocking.

    New individual must be requested before calling this with the spawn() and
    mate() functions.
    """
    message = b''
    while True:
        char = sys.stdin.buffer.read1(1)
        if not char:
            raise EOFError
        if char == b'\n':
            break
        else:
            message += char
    message = json.loads(message)
    num_bytes = int(message["genome"])
    message["genome"] = sys.stdin.buffer.read(num_bytes)
    return message

def _try_print(*args, **kwargs):
    # If the stdout channel is simply closed, then quietly exit.
    # For other more abnormal conditions raise the error to the user.
    try:
        print(*args, **kwargs, file=sys.stdout, flush=True)
    except BrokenPipeError:
        sys.stdin.close()
    except ValueError:
        if sys.stdout.closed:
            sys.stdin.close()
        else:
            raise

def spawn(body_type=None):
    """
    Request a new individual from this body_type's evolution API.

    Argument body_type is optional if the environment has exactly one body_type.
    """
    if body_type is not None:
        body_type = str(body_type)
    _try_print(json.dumps({"Spawn": body_type}))

def mate(*parents):
    """
    Request to mate specific individuals together to produce a child individual.
    """
    parents = [str(p) for p in parents]
    assert len(parents) > 0
    _try_print(json.dumps({"Mate": parents}))

def score(name, score):
    """
    Report an individual's score or reproductive fitness to the evolution API.

    This should be called *before* calling "death()" on the individual.
    """
    name = str(name)
    score = str(score)
    _try_print(json.dumps({"Score": score, "name": name}))

def telemetry(name, info):
    """
    Report extra information about an individual.

    Argument info is a mapping of string key-value pairs.
    """
    name = str(name)
    info = {str(key) : str(value) for key, value in info.items()}
    _try_print(json.dumps({"Telemetry": info, "name": name}))

def death(name):
    """
    Notify the evolution API that the given individual has died.

    The individual's score or reproductive fitness should be reported
    using the "score()" function *before* calling this method.
    """
    name = str(name)
    _try_print(json.dumps({"Death": name}))

class SoloAPI:
    """
    Abstract class for implementing environments which contain exactly one
    individual at a time. The environment must have exactly one body_type.
    """
    def __init__(self, env_spec, mode, **settings):
        """
        Abstract Method, Optional

        Environments are initialized with these arguments:

        Argument env_spec is the environment specification, as a python object.
                 It is already loaded from file, parsed, and error checked.

        Argument mode is either the word "graphical" or the word "headless" to
                 indicate whether or not the environment should show graphical
                 output to the user.

        Additional keyword argument are the environment's settings, as described
        by the environment specification. All of the settings will be provided,
        using either their default values or they can be overridden via command
        line arguments as key-value pairs.
        """

    def evaluate(self, name, controller):
        """
        Abstract Method

        Evaluate the given controller in this environment.

        Argument name is the UUID string of the individual who is currently
                 occupying the environment.

        Argument controller is an instance of "npc_maker.ctrl.Controller"

        Returns the individual's score.
        """
        raise TypeError("abstract method called")

    def quit(self):
        """
        Abstract Method, Optional

        Called just before the environment exits.
        """
        pass

    @classmethod
    def main(cls):
        """
        Run the environment program.

        This function handles communications between the environment
        (this program) and the evolution program, which execute in separate
        computer processes and communicate over the environment's standard I/O
        channels.

        This never returns!

        Example Usage:
        >>> if __name__ == "__main__":
        >>>     MyEnvironment.main()
        """
        import npc_maker.ctrl
        env_spec, mode, settings = get_args()
        assert len(env_spec["body_types"]) == 1
        self = cls(env_spec, mode, **settings)
        body_type = env_spec["body_types"][0]["name"]
        controller = None
        # 
        while True:
            spawn(body_type)
            try:
                individual = input()
            except EOFError:
                break
            name       = individual["name"]
            command    = individual["controller"]
            # Start a new controller process.
            if controller is None or not controller.same_command(command):
                controller = npc_maker.ctrl.Controller(env_spec, body_type, command)
            assert controller.is_alive()
            controller.genome(individual["genome"])
            score(name, self.evaluate(name, controller))
            death(name)
        self.quit()

class Environment:
    """
    This class encapsulates an instance of an environment and provides methods
    for using environments.

    Each environment instance execute in its own subprocess
    and communicates with the caller over its standard I/O channels.
    """
    def __init__(self, env_spec, mode='graphical', settings={}, stderr=sys.stderr):
        """
        Start running an environment program.

        Argument env_spec is the filesystem path of the environment specification.

        Argument mode is either the word "graphical" or the word "headless" to
                 indicate whether or not the environment should show graphical
                 output to the user.

        Argument settings is a dict of command line arguments for the environment process.
                 These must match what is listed in the environment specification.

        Argument stderr is the file descriptor to use for the subprocess's stderr channel.
                 By default, the controller will inherit this process's stderr channel.
        """
        self._outstanding = {}
        self._tempdir = tempfile.TemporaryDirectory()
        # Clean the arguments.
        self._env_spec = Specification(env_spec)
        self._mode = str(mode).strip().lower()
        assert self._mode in ('graphical', 'headless')
        settings = {str(key) : str(value) for key, value in settings.items()}
        # Fill in default settings values and check for extra arguments.
        settings_spec = self._env_spec["settings"]
        self._settings = {item["name"] : item["default"] for item in settings_spec}
        for key, value in settings.items():
            if key not in self._settings:
                raise ValueError(f"unrecognized environment setting \"{key}\"")
            self._settings[key] = value
        # Assemble the environment's optional settings.
        settings_list = []
        for key, value in self._settings.items():
            settings_list.append(str(key))
            settings_list.append(str(value))
        # 
        self._process = subprocess.Popen(
            [self._env_spec["path"], self._env_spec["spec"], self._mode] + settings_list,
            stdin  = subprocess.PIPE,
            stdout = subprocess.PIPE,
            stderr = stderr)
        os.set_blocking(self._process.stdout.fileno(), False)

    def is_alive(self):
        """
        Check if the environment subprocess is still running or if it has exited.
        """
        return self._process.poll() is None

    def __del__(self):
        if hasattr(self, "_process"): # Guard against crashes in __init__.
            self.quit()

    def get_env_spec(self):
        """
        Get the environment specification.
        This returns the loaded JSON object, *not* its filesystem path.
        """
        return self._env_spec

    def get_mode(self):
        """
        Get the output display "mode" argument.
        """
        return self._mode

    def get_settings(self):
        """
        Get the "settings" argument.
        """
        return dict(self._settings)

    def get_outstanding(self):
        """
        Get all individuals who are currently alive in this environment.
        Returns a dictionary indexed by individuals names.
        """
        return dict(self._outstanding)

    def quit(self):
        """
        Tell the environment program to exit.
        """
        try:
            self._process.stdin.close()
        except BrokenPipeError:
            pass

    def _get_body_type(self, body_type):
        """
        Clean the body_type argument and fill in its default value.
        """
        if not body_type:
            all_body_types = self._env_spec["body_types"]
            if len(all_body_types) == 1:
                body_type = all_body_types[0]["name"]
            else:
                raise ValueError("missing body_type")
        return str(body_type)

    def _get_name(self, name):
        """
        Clean the individual name argument and fill in its default value.
        """
        if not name:
            if len(self._outstanding) == 1:
                name = next(self._outstanding)
            else:
                raise ValueError("missing name")
        return str(name)

    def birth(self, individual):
        """
        Send an individual to the environment.
        Does not flush.
        """
        # First package up this individual for sending it to an environment.
        body_type = individual.body_type
        if body_type is None:
            body_type = ""
        controller = individual.get_controller()
        if not controller:
            raise ValueError("missing controller")
        controller[0] = str(controller[0]) # Convert Path to String
        phenome = individual.get_phenome()
        metadata = {
            "name": self.name,
            "body_type": body_type,
            "parents": self.parents,
            "controller": controller,
            "genome": len(phenome),
        }
        self._process.stdin.write(json.dumps(metadata).encode("utf-8"))
        self._process.stdin.write(b"\n")
        self._process.stdin.write(phenome)
        self._outstanding[individual.name] = individual
        individual.birth_date = _timestamp()
        individual.save(self._tempdir.name)
        individual._genome = None

    def poll(self):
        """
        Check for messages from the environment program.

        This function is non-blocking and should be called periodically.

        Returns "Spawn" and "Death" messages.
        """
        # Check for messages.
        message = self._process.stdout.readline().strip()
        if not message:
            # Flush all queued responses on the way out the door.
            self._process.stdin.flush()
            return

        # Decode the message.
        message = json.loads(message)

        # Fill in missing fields.
        if "Spawn" in message:
            message["Spawn"] = self._get_body_type(message["Spawn"])
        elif "Score" in message or "Telemetry" in message:
            message["name"] = self._get_name(message["name"])
        elif "Death" in message:
            message["Death"] = self._get_name(message["Death"])

        # Process the message if able.
        if "Score" in message:
            score       = message["Score"]
            name        = message["name"]
            individual  = self._outstanding[name]
            individual.score = score
            return # consume the message

        elif "Telemetry" in message:
            info        = message["Telemetry"]
            name        = message["name"]
            individual  = self._outstanding[name]
            individual.telemetry.update(info)
            return # consume the message

        elif "Death" in message:
            name        = message["Death"]
            individual  = self._outstanding.pop(name)
            individual.death_date = _timestamp()
            message["Death"] = individual

        return message

    def evolve(self, body_types):
        """
        Argument body_types is a dict of evolution API instances, indexed by body_type name.

        Returns either None or an Individual if one was just born or died.
        """
        message = self.poll()
        if not message:
            return

        if "Spawn" in message:
            pop_name   = message["Spawn"]
            individual = body_types[pop_name].spawn()
            if not individual.get_body_type():
                individual.body_type = pop_name
            self.birth(individual)
            return individual

        elif "Mate" in message:
            parents = [self._outstanding[parent] for parent in message["Mate"]]
            if   len(parents) == 1: individual = parents[0].clone()
            elif len(parents) == 2: individual = parents[0].mate(parents[1])
            self.birth(individual)
            return individual

        elif "Death" in message:
            individual = message["Death"]
            pop_name   = self._get_body_type(individual.get_body_type())
            body_types[pop_name].death(individual)
            return individual

        else:
            raise ValueError(f'unrecognized message "{message}"')
