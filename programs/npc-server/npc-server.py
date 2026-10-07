#!/usr/bin/env python3
"""
Experiment server for the NPC Maker

The npc-server accepts connections from Environment programs, routes their
messages to Evolution and Genetic services, and manages their living individuals.

This is a simplified implementation for testing and debugging. It is
synchronous, single-threaded, and does not accept environment connections.
Instead it starts a single instance of the environment.
"""

import argparse
import collections
import datetime
import json
import logging
import math
import socket
import subprocess
import sys
from concurrent import futures
from pathlib import Path

import grpc
from google.protobuf import json_format

from npc_maker import diagnostics_pb2, diagnostics_pb2_grpc
from npc_maker import environment_pb2, environment_pb2_grpc
from npc_maker import experiment_pb2
from npc_maker import evolution_pb2, evolution_pb2_grpc
from npc_maker import genetics_pb2, genetics_pb2_grpc
from npc_maker.individual import Individual


class LocalProcess:
    """
    Run a local subprocess.
    """
    def __init__(self, command, cwd=None):
        command = list(command)
        if not command:
            raise ValueError("empty command")

        if cwd is not None:
            Path(cwd).mkdir(parents=True, exist_ok=True)

        self.process = subprocess.Popen(command, cwd=cwd)

    def __del__(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()


class ServiceProcess(LocalProcess):
    """
    Run a local gRPC service.
    """
    def __init__(self, command, stub_class, host, port, cwd=None):
        # Note: By convention services accept "--listen HOST:PORT".
        command = [*command, "--listen", f"{host}:{port}"]
        super().__init__(command, cwd)
        self.channel = grpc.insecure_channel(f"{host}:{port}")

        # Block until the subprocess is ready to accept connections
        try:
            grpc.channel_ready_future(self.channel).result(timeout=30)
        except grpc.FutureTimeoutError:
            self.close()
            raise RuntimeError(f"gRPC service timeout: {command}")

        self.stub = stub_class(self.channel)

    def __del__(self):
        self.channel.close()
        super().__del__()


class NpcServer(environment_pb2_grpc.EnvironmentServicer):
    """
    Implementation of the Environment service.
    """
    def __init__(self, config, save_dir):
        self.config = config
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.living = {}
        self.evolution = {}
        self.genetics = {}
        self.processes = []
        self.server = None
        self.environment = None
        self.failed = False
        self.listen = None # Listen address of this service as "host:port" string

        # Diagnostics, tracked per body type. These are only ever accessed from
        # the gRPC worker thread (the server has max_workers=1), so no locking.
        self.call_counts = collections.defaultdict(collections.Counter)
        self.max_scores = {} # Absent until the first score is reported.

        self.organisms = {
            organism.body_type: organism
            for organism in config.organisms
        }

        for body_type, organism in self.organisms.items():
            evolution = list(organism.evolution) or list(config.evolution)
            genetics = list(organism.genetics) or list(config.genetics)

            if evolution:
                port = _free_port()
                service = ServiceProcess(
                    evolution, evolution_pb2_grpc.EvolutionStub,
                    "127.0.0.1", port,
                    cwd=self.save_dir / f"{body_type}-evolution")
                self.evolution[body_type] = service.stub
                self.processes.append(service)

            if genetics:
                port = _free_port()
                service = ServiceProcess(
                    genetics, genetics_pb2_grpc.GeneticsStub,
                    "127.0.0.1", port,
                    cwd=self.save_dir / f"{body_type}-genetics")
                self.genetics[body_type] = service.stub
                self.processes.append(service)

    def _body_type(self, body_type):
        if not body_type:
            if len(self.organisms) == 1:
                return next(iter(self.organisms.values())).body_type
            else:
                raise ValueError(f'missing body type')
        try:
            return self.organisms[body_type].body_type
        except KeyError:
            raise ValueError(f'unknown body type "{body_type}"')

    def _count(self, call, body_type):
        """
        Increment a diagnostic call counter, for the given body type.
        """
        self.call_counts[body_type][call] += 1

    def _set_defaults(self, individual: Individual):
        body_type = self._body_type(individual.body_type)
        if not individual.body_type:
            individual.body_type = body_type
        organism = self.organisms[body_type]
        controller = list(organism.controller) or list(self.config.controller)
        if not individual.controller and controller:
            individual.controller = controller

    def _fatal(self, error):
        self.failed = True
        print(f"npc-server: downstream service failure: {error}", file=sys.stderr)
        if self.server is not None:
            self.server.stop(0)

    def _call(self, call, request):
        """
        Attempt a gRPC call. Handles errors by logging them and exiting.
        """
        try:
            return call(request)
        except grpc.RpcError as error:
            self._fatal(error)
            raise

    def Spawn(self, request, context):
        logging.debug("Spawn request received:\n%s", request)
        body_type = self._body_type(request.body_type)
        self._count("Spawn", body_type)
        parents = []

        if body_type in self.evolution:
            response = self._call(
                self.evolution[body_type].Spawn,
                evolution_pb2.SpawnRequest())
            parents = [Individual.from_proto(parent) for parent in response.parents]

        if body_type in self.genetics:
            response = self._call(
                self.genetics[body_type].Reproduce,
                genetics_pb2.ReproduceRequest(
                    parents=[parent.to_proto() for parent in parents]))
            child = Individual.from_proto(response.child)
        elif parents:
            # No genetic algorithm registered, clone first parent.
            child = Individual.reproduce([parents[0]])
            child.genome = parents[0].genome
        else:
            raise RuntimeError(
                f'cannot spawn body type "{body_type}": '
                "no genetics service and no parent was selected")

        self._set_defaults(child)
        child.birth_date = datetime.datetime.now()
        self._save(child)
        self.living[child.name] = child.to_proto().metadata
        return child.to_proto()

    def Mate(self, request, context):
        logging.debug("Mate request received:\n%s", request)
        if not request.parents:
            raise ValueError("at least one parent is required")

        # The body type of a mating is the body type of its first parent.
        body_type = self._body_type(self._living(request.parents[0]).body_type)
        self._count("Mate", body_type)

        # Access and load the requested parents.
        parents = []
        for name in request.parents:
            metadata = self._living(name)
            path = self._living_path(metadata.name)
            individual = Individual.load(path)
            parents.append(individual)

        # Apply the genetic algorithm.
        if body_type in self.genetics:
            response = self._call(
                self.genetics[body_type].Reproduce,
                genetics_pb2.ReproduceRequest(
                    parents=[parent.to_proto() for parent in parents]))
            child = Individual.from_proto(response.child)
        else:
            child = Individual.reproduce([parents[0]])
            child.genome = parents[0].genome
            child.epigenome = parents[0].epigenome
            child.phenome = parents[0].phenome

        self._set_defaults(child)
        child.birth_date = datetime.datetime.now()
        self._save(child)
        self.living[child.name] = child.to_proto().metadata
        return child.to_proto()

    def Score(self, request, context):
        logging.debug("Score request received:\n%s", request)
        metadata = self._living(request.name)
        body_type = self._body_type(metadata.body_type)
        self._count("Score", body_type)
        # NaN is unordered and would poison the running maximum, so skip it.
        if not math.isnan(request.score):
            high_score = self.max_scores.get(body_type, -math.inf)
            self.max_scores[body_type] = max(request.score, high_score)
        metadata.score = request.score
        self._save_metadata(metadata)
        return environment_pb2.ScoreResponse()

    def Telemetry(self, request, context):
        logging.debug("Telemetry request received:\n%s", request)
        metadata = self._living(request.name)
        self._count("Telemetry", self._body_type(metadata.body_type))
        for item in request.data:
            metadata.telemetry[item.key] = item.value
        self._save_metadata(metadata)
        return environment_pb2.TelemetryResponse()

    def Epigenome(self, request, context):
        logging.debug("Epigenome request received:\n%s", request)
        # TODO: Epigenetics will be sorted out in version 2.
        context.abort(grpc.StatusCode.UNIMPLEMENTED)
        metadata = self._living(request.name)
        for item in request.data:
            # The current environment API exposes epigenome data as key/value
            # strings, while Individual stores it as opaque bytes. Preserve the
            # request for now in metadata.extra.
            metadata.extra[f"epigenome.{item.key}"] = item.value
        self._save_metadata(metadata)
        return environment_pb2.EpigenomeResponse()

    def Death(self, request, context):
        logging.debug("Death request received:\n%s", request)
        # Load the individual and update its metadata.
        metadata = self._living(request.name)
        body_type = self._body_type(metadata.body_type)
        self._count("Death", body_type)
        path = self._living_path(metadata.name)
        individual = Individual.load(path)
        individual.death_date = datetime.datetime.now()

        # Drop the individual (infallible, entry is guarenteed to exist)
        del self.living[metadata.name]

        # Notify the evolution service.
        if body_type in self.evolution:
            self._call(
                self.evolution[body_type].Death,
                evolution_pb2.DeathRequest(individual=individual.to_proto()))

        # Clean up the deceased individual's save files.
        Individual.delete(path)

        return environment_pb2.DeathResponse()

    def _living(self, name):
        """
        Get the metadata for a living individual.
        """
        try:
            return self.living[name]
        except KeyError:
            raise ValueError(f'unknown living individual "{name}"')

    def _living_path(self, name):
        """
        Get the save directory for a living individual.
        """
        return self.save_dir / name

    def _save(self, individual: Individual):
        individual.save(self.save_dir)

    def _save_metadata(self, metadata):
        path = self._living_path(metadata.name)
        Individual.save_metadata(metadata, path)

    def start_environment(self):
        """
        Start the single environment instance configured by the experiment.
        """
        command = list(self.config.environment)
        command.extend(["--listen", self.listen])
        self.environment = LocalProcess(command)


class DiagnosticsServer(diagnostics_pb2_grpc.DiagnosticsServicer):
    """
    Implementation of the Diagnostics service.

    This is a read-only view of the NpcServer's state, and is served on the
    same port as the Environment service.
    """
    def __init__(self, npc_server):
        self.npc_server = npc_server

    def _body_type(self, request, context):
        try:
            return self.npc_server._body_type(request.body_type)
        except ValueError as error:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(error))

    def _call_count(self, call, request, context):
        body_type = self._body_type(request, context)
        return diagnostics_pb2.Count(
            count=self.npc_server.call_counts[body_type][call])

    def LivingCount(self, request, context):
        body_type = self._body_type(request, context)
        count = sum(
            1 for metadata in self.npc_server.living.values()
            if metadata.body_type == body_type)
        return diagnostics_pb2.Count(count=count)

    def SpawnCount(self, request, context):
        return self._call_count("Spawn", request, context)

    def MateCount(self, request, context):
        return self._call_count("Mate", request, context)

    def ScoreCount(self, request, context):
        return self._call_count("Score", request, context)

    def TelemetryCount(self, request, context):
        return self._call_count("Telemetry", request, context)

    def DeathCount(self, request, context):
        return self._call_count("Death", request, context)

    def MaximumScore(self, request, context):
        body_type = self._body_type(request, context)
        try:
            score = self.npc_server.max_scores[body_type]
        except KeyError:
            score = -math.inf
        return diagnostics_pb2.Score(score=score)


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def load_config(path):
    with open(path, "rt", encoding="utf-8") as file:
        data = json.load(file)
    return json_format.ParseDict(data, experiment_pb2.Experiment())


def main():
    parser = argparse.ArgumentParser(prog="npc-server.py", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="enable DEBUG logging")
    parser.add_argument("--listen", metavar="HOST:PORT",
                        help="address to serve the Environment and Diagnostics "
                             "services on (default: a free port on 127.0.0.1)")
    parser.add_argument("config", type=Path, help="experiment configuration (JSON)")
    parser.add_argument("save_dir", type=Path, help="directory for persistence")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    listen = args.listen or f"127.0.0.1:{_free_port()}"

    try:
        config = load_config(args.config)
        logging.info("Starting NPC server with configuration:\n%s",
                    json_format.MessageToJson(config, indent=2))
        program = NpcServer(config, args.save_dir)
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 5

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    environment_pb2_grpc.add_EnvironmentServicer_to_server(program, server)
    diagnostics_pb2_grpc.add_DiagnosticsServicer_to_server(
        DiagnosticsServer(program), server)
    try:
        bound_port = server.add_insecure_port(listen)
    except RuntimeError as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 7
    # If the requested port was 0 then the OS chose one, so report the real one.
    listen = f"{listen.rpartition(':')[0]}:{bound_port}"
    program.server = server
    program.listen = listen

    try:
        server.start()
        logging.info("Serving Environment and Diagnostics on %s", listen)
        program.start_environment()
        server.wait_for_termination()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop(0).wait()
        failed = program.failed
        del program

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
