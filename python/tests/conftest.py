# Shared test fixtures, which pytest finds automatically.

import datetime

import pytest

from npc_maker.individual import Individual


@pytest.fixture
def make_full_individual():
    """
    Factory for individuals with every field populated.

    Note that `ascension` is assigned by the evolution program when an
    individual dies, so clear it (`ascension=None`) before sending an
    individual to the Evolution service's `Death()` method.
    """
    def make(score=42.5, **kwargs):
        individual = Individual()
        individual.environment = "test-env"
        individual.body_type  = "test-body"
        individual.controller = ["test-ctrl", "--flag"]
        individual.genome     = b"genome data"
        individual.score      = score
        individual.ascension  = 88
        individual.telemetry  = {"temperature": "20", "mood": "ok"}
        individual.parents    = ["PARENT1", "PARENT2"]
        individual.children   = 3
        individual.generation = 4
        individual.birth_date = datetime.datetime(2026, 10, 3, 12, 30, 45, 123456, tzinfo=datetime.timezone.utc)
        individual.death_date = datetime.datetime(2026, 10, 3, 13, 0, 0, tzinfo=datetime.timezone.utc)
        individual.extra["note"]   = "héllo ✓"
        individual.extra["count"]  = 2.5
        individual.extra.get_or_create_struct("nested")["flag"] = True
        individual.extra.get_or_create_list("items").extend([1, "two"])
        individual.epigenome  = b"epigenome data"
        individual.phenome    = b"phenome data"
        for key, value in kwargs.items():
            setattr(individual, key, value)
        return individual
    return make
