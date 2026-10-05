"""
Evolutionary algorithms and supporting tools.
"""

from npc_maker.individual import Individual
from npc_maker.evo import API, eprint
from pathlib import Path
import json
import math
import os
import os.path
import tempfile
import threading

def _scan_dir(path):
    """
    Find saved individuals in the given directory.
    """
    path = Path(path)
    for file in path.iterdir():
        if file.suffix.lower() == ".indiv":
            yield file

class Player(API):
    """
    Replay saved individuals
    """
    def __init__(self, genome_cls, path, select="Random", score="score"):
        """
        Argument path is the directory containing the saved individuals.
                 Individuals must have the file extension ".json"

        Argument select is a mate selection algorithm.

        Argument score is an optional custom scoring function.
        """
        self._genome_cls    = genome_cls
        self._path          = Path(path)
        self._lock          = threading.RLock()
        self._select        = select
        self._score         = score
        self._scan_time     = -1
        self._members       = []
        self._scores        = [] # Runs parallel to the members list.
        self._buffer        = [] # Queue of selected individuals wait to be born.

    def get_members(self):
        """
        Returns a list of individuals.
        """
        with self._lock:
            self._scan()
            return list(self._members)

    def spawn(self):
        with self._lock:
            self._scan()
            if not self._buffer:
                buffer_size = len(self._members)
                indices = self._select.select(buffer_size, self._scores)
                self._buffer.extend(self._members[i] for i in indices)
            individual = self._buffer.pop()
        # Reload into a new instance for the environment to modify.
        return Individual.load(individual.get_path())

    def death(self, individual):
        pass

    def _scan(self):
        if self._scan_time == os.path.getmtime(self._path):
            return
        self._members = [Individual.load(file)
                         for file in _scan_dir(self._path)]
        self._scores = [individual.get_custom_score(self._score)
                        for individual in self._members]
        self._buffer = []
        self._scan_time = os.path.getmtime(self._path)



from concurrent import futures
import logging

import grpc
import helloworld_pb2
import helloworld_pb2_grpc


class Greeter(helloworld_pb2_grpc.GreeterServicer):
    def SayHello(self, request, context):
        return helloworld_pb2.HelloReply(message="Hello, %s!" % request.name)


def serve():
    port = "50051"
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    helloworld_pb2_grpc.add_GreeterServicer_to_server(Greeter(), server)
    server.add_insecure_port("[::]:" + port)
    server.start()
    print("Server started, listening on " + port)
    server.wait_for_termination()


if __name__ == "__main__":
    logging.basicConfig()
    serve()
