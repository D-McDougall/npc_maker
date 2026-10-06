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
import json
import socket
import subprocess
import sys
from concurrent import futures
from pathlib import Path

import grpc
from google.protobuf import json_format
from google.protobuf.timestamp_pb2 import Timestamp

from npc_maker import environment_pb2, environment_pb2_grpc
from npc_maker import experiment_pb2
from npc_maker import evolution_pb2, evolution_pb2_grpc
from npc_maker import genetics_pb2, genetics_pb2_grpc
from npc_maker import individual_pb2
from npc_maker.individual import Individual


class ServiceProcess:
    """
    A configured local gRPC service and its subprocess.
    """
    def __init__(self, command, stub_class, host, port, cwd=None):
        command = list(command)
        if not command:
            raise ValueError("empty service command")

        if cwd is not None:
            Path(cwd).mkdir(parents=True, exist_ok=True)

        # NOTE: Conventional services accept "--listen HOST:PORT".
        command += ["--listen", f"{host}:{port}"]
        self.process = subprocess.Popen(command, cwd=cwd)
        self.channel = grpc.insecure_channel(f"{host}:{port}")
        self.stub = stub_class(self.channel)

    def close(self):
        self.channel.close()
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()


class NpcServer(environment_pb2_grpc.EnvironmentServicer):
    """
    Implementation of the Environment service.
    """
    def __init__(self, config):
        self.config = config
        self.persistence = Path(config.persistence_directory)
        self.persistence.mkdir(parents=True, exist_ok=True)
        self.living = {}
        self.evolution = {}
        self.genetics = {}
        self.processes = []
        self.server = None
        self.environment = None
        self.failed = False

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
                    cwd=self.persistence / f"{body_type}-evolution")
                self.evolution[body_type] = service.stub
                self.processes.append(service)

            if genetics:
                port = _free_port()
                service = ServiceProcess(
                    genetics, genetics_pb2_grpc.GeneticsStub,
                    "127.0.0.1", port,
                    cwd=self.persistence / f"{body_type}-genetics")
                self.genetics[body_type] = service.stub
                self.processes.append(service)

    def _organism(self, body_type):
        if not body_type:
            if len(self.organisms) == 1:
                return next(self.organisms.values())
            else:
                raise ValueError(f'missing body type')
        try:
            return self.organisms[body_type]
        except KeyError:
            raise ValueError(f'unknown body type "{body_type}"')

    @staticmethod
    def _timestamp():
        timestamp = Timestamp()
        timestamp.GetCurrentTime()
        return timestamp

    def _set_defaults(self, individual, organism):
        if not individual.metadata.body_type:
            individual.metadata.body_type = organism.body_type
        controller = list(organism.controller) or list(self.config.controller)
        if not individual.metadata.controller and controller:
            individual.metadata.controller.extend(controller)

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

    def _save(self, individual):
        path = self.persistence / individual.metadata.name
        # TODO: Add method to individual to update metadata instead of rewriting all files.
        if path.exists():
            Individual.delete(path)
        Individual.from_proto(individual).save(self.persistence)

    def Spawn(self, request, context):
        organism = self._organism(request.body_type)
        parents = []

        if request.body_type in self.evolution:
            response = self._call(
                self.evolution[request.body_type].Spawn,
                evolution_pb2.SpawnRequest())
            parents = list(response.parents)

        if request.body_type in self.genetics:
            response = self._call(
                self.genetics[request.body_type].Reproduce,
                genetics_pb2.ReproduceRequest(parents=parents))
            child = response.child
        elif parents:
            parent = Individual.from_proto(parents[0])
            child = Individual.reproduce([parent]).to_proto()
            child.genome = parents[0].genome
        else:
            raise RuntimeError(
                f'cannot spawn body type "{request.body_type}": '
                "no genetics service and no parent was selected")

        self._set_defaults(child, organism)
        child.metadata.birth_date.CopyFrom(self._timestamp())
        self.living[child.metadata.name] = child
        self._save(child)
        return child

    def Mate(self, request, context):
        if not request.parents:
            raise ValueError("at least one parent is required")

        parents = []
        for name in request.parents:
            try:
                parents.append(self.living[name])
            except KeyError:
                raise ValueError(f'unknown living individual "{name}"')

        body_type = parents[0].metadata.body_type
        organism = self._organism(body_type)

        if body_type in self.genetics:
            child = self._call(
                self.genetics[body_type].Reproduce,
                genetics_pb2.ReproduceRequest(parents=parents)).child
        else:
            parents = [Individual.from_proto(parent) for parent in parents]
            child = Individual.reproduce(parents).to_proto()
            child.genome = parents[0].genome

        self._set_defaults(child, organism)
        child.metadata.birth_date.CopyFrom(self._timestamp())
        self.living[child.metadata.name] = child
        self._save(child)
        return child

    def Score(self, request, context):
        individual = self._living(request.name)
        individual.metadata.score = request.score
        self._save(individual)
        return environment_pb2.ScoreResponse()

    def Telemetry(self, request, context):
        individual = self._living(request.name)
        for item in request.data:
            individual.metadata.telemetry[item.key] = item.value
        self._save(individual)
        return environment_pb2.TelemetryResponse()

    def Epigenome(self, request, context):
        individual = self._living(request.name)
        for item in request.data:
            # The current environment API exposes epigenome data as key/value
            # strings, while Individual stores it as opaque bytes. Preserve the
            # request for now in metadata.extra.
            individual.metadata.extra[f"epigenome.{item.key}"] = item.value
        self._save(individual)
        return environment_pb2.EpigenomeResponse()

    def Death(self, request, context):
        individual = self._living(request.name)
        individual.metadata.death_date.CopyFrom(self._timestamp())
        body_type = individual.metadata.body_type

        if body_type in self.evolution:
            self._call(
                self.evolution[body_type].Death,
                evolution_pb2.DeathRequest(individual=individual))

        path = self.persistence / individual.metadata.name
        Individual.delete(path)
        del self.living[request.name]
        return environment_pb2.DeathResponse()

    def _living(self, name):
        try:
            return self.living[name]
        except KeyError:
            raise ValueError(f'unknown living individual "{name}"')

    def start_environment(self):
        """
        Start the single environment instance configured by the experiment.
        """
        command = list(self.config.environment)
        if not command:
            raise ValueError("experiment environment command is empty")
        self.environment = subprocess.Popen(command)

    def close(self):
        if self.environment is not None:
            if self.environment.poll() is None:
                self.environment.terminate()
                try:
                    self.environment.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.environment.kill()
                    self.environment.wait()
            self.environment = None

        for process in reversed(self.processes):
            process.close()


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
    parser.add_argument("filename", help="experiment configuration (JSON)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="address on which to serve the environment API")
    parser.add_argument("--port", type=int, default=47000,
                        help="port on which to serve the environment API")
    args = parser.parse_args()

    try:
        config = load_config(args.filename)
        program = NpcServer(config)
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 5

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    environment_pb2_grpc.add_EnvironmentServicer_to_server(program, server)
    server.add_insecure_port(f"{args.host}:{args.port}")
    program.server = server

    try:
        server.start()
        program.start_environment()
        server.wait_for_termination()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop(0).wait()
        program.close()

    return 1 if program.failed else 0


if __name__ == "__main__":
    sys.exit(main())
