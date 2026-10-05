import copy
import datetime
import json
import math
import pathlib

import pytest

from npc_maker.individual import Individual


def make(genome=b"x", **fields):
    """A new individual with a genome, and the given metadata fields."""
    individual = Individual()
    individual.genome = genome
    for field, value in fields.items():
        setattr(individual, field, value)
    return individual


def test_new_individual():
    individual = Individual()
    assert individual.name
    assert individual.species
    assert individual.species != individual.name
    assert individual.generation == 0  # Founders are generation zero
    # Everything else is unset.
    assert individual.environment is None
    assert individual.body_type is None
    assert individual.controller == []
    assert individual.parents == []
    assert dict(individual.telemetry) == {}
    assert individual.score is None
    assert individual.children is None
    assert individual.ascension is None
    assert individual.birth_date is None
    assert individual.death_date is None
    assert individual.genome is None
    assert individual.epigenome is None
    assert individual.phenome is None


def test_names_are_unique_and_safe():
    individuals = [Individual() for _ in range(1000)]
    assert len({individual.name for individual in individuals}) == 1000
    assert len({individual.species for individual in individuals}) == 1000
    for individual in individuals:
        # Names are used as directory names.
        assert individual.name not in ("", ".", "..")
        assert not set(individual.name) & set("/\\\0")


def test_controller_normalization():
    individual = Individual()
    cases = [
        ("", []),
        (None, []),
        ("prog --flag 'a b'", ["prog", "--flag", "a b"]),
        (pathlib.Path("prog"), ["prog"]),
        ([pathlib.Path("prog"), 5], ["prog", "5"]),
        (("prog", "--flag"), ["prog", "--flag"]),
    ]
    for value, expected in cases:
        individual.controller = value
        assert individual.controller == expected
    with pytest.raises(TypeError):
        individual.controller = [b"prog"]


def test_optional_fields():
    individual = make()
    individual.score = 0.0
    assert individual.score == 0.0  # Zero is a value, not an absence of a value.
    individual.score = None
    assert individual.score is None
    individual.ascension = 0
    assert individual.ascension == 0
    individual.ascension = None
    assert individual.ascension is None
    individual.phenome = b""
    assert individual.phenome == b""
    individual.phenome = None
    assert individual.phenome is None


def test_dates_are_utc():
    individual = make()
    individual.birth_date = datetime.datetime(2026, 1, 2, 3, 4, 5)  # Naive is assumed to be UTC
    assert individual.birth_date == datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc)
    eastern = datetime.timezone(datetime.timedelta(hours=-5))
    individual.death_date = datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=eastern)
    assert individual.death_date == datetime.datetime(2026, 1, 2, 8, 4, 5, tzinfo=datetime.timezone.utc)
    assert individual.death_date.utcoffset() == datetime.timedelta(0)


def test_telemetry_is_live_and_requires_strings():
    individual = make()
    individual.telemetry["a"] = "1"
    individual.telemetry.update({"b": "2"})
    assert dict(individual.telemetry) == {"a": "1", "b": "2"}
    individual.telemetry = {"c": "3"}
    assert dict(individual.telemetry) == {"c": "3"}
    with pytest.raises(TypeError):
        individual.telemetry["d"] = 4


def test_proto_is_not_copied():
    individual = make()
    message = individual.to_proto()
    wrapped = Individual.from_proto(message)
    wrapped.score = 7.0
    assert individual.score == 7.0
    with pytest.raises(TypeError):
        Individual.from_proto(message.metadata)


def test_equality(make_full_individual):
    individual = make_full_individual()
    assert individual == Individual.from_proto(individual.to_proto())
    other = make_full_individual()  # Different name
    assert individual != other
    other.name = individual.name
    other.species = individual.species
    assert individual == other
    other.score = 1.0
    assert individual != other


def test_save_layout(tmp_path):
    individual = make(b"genome", environment="test-env", body_type="test-body")
    directory = individual.save(tmp_path / "population")
    assert directory == tmp_path / "population" / individual.name
    assert sorted(path.name for path in directory.iterdir()) == ["epigenome", "genome", "metadata.json", "phenome"]
    assert (directory / "genome").read_bytes() == b"genome"
    # Absent blobs are saved as empty files.
    assert (directory / "epigenome").read_bytes() == b""
    assert (directory / "phenome").read_bytes() == b""


def test_save_load_round_trip(tmp_path, make_full_individual):
    individual = make_full_individual(ascension=5)
    directory = individual.save(tmp_path)
    loaded = Individual.load(directory)
    assert loaded == individual
    assert loaded.genome == b"genome data"
    assert loaded.epigenome == b"epigenome data"
    assert loaded.phenome == b"phenome data"
    assert loaded.birth_date == individual.birth_date
    assert loaded.controller == ["test-ctrl", "--flag"]
    assert dict(loaded.telemetry) == {"temperature": "20", "mood": "ok"}
    assert loaded.extra["note"] == "héllo ✓"
    assert loaded.extra["nested"]["flag"] is True


def test_metadata_json_is_protobuf_json(tmp_path, make_full_individual):
    individual = make_full_individual(ascension=5)
    text = (individual.save(tmp_path) / "metadata.json").read_text(encoding="utf-8")
    data = json.loads(text)
    assert data["name"] == individual.name
    assert data["body_type"] == "test-body"        # Field names are not camelCase
    assert data["controller"] == ["test-ctrl", "--flag"]
    assert data["score"] == 42.5
    assert data["telemetry"] == {"temperature": "20", "mood": "ok"}
    assert data["parents"] == ["PARENT1", "PARENT2"]
    assert data["children"] == "3"                 # 64-bit integers are strings
    assert data["generation"] == "4"
    assert data["ascension"] == "5"
    assert data["birth_date"] == "2026-10-03T12:30:45.123456Z"
    assert data["death_date"] == "2026-10-03T13:00:00Z"
    assert data["extra"]["note"] == "héllo ✓"      # Not escaped
    assert data["extra"]["nested"] == {"flag": True}
    assert data["extra"]["items"] == [1, "two"]
    # Blobs are not part of the metadata.
    assert not {"genome", "epigenome", "phenome"} & set(data)


def test_metadata_json_omits_unset_fields(tmp_path):
    individual = make()
    data = json.loads((individual.save(tmp_path) / "metadata.json").read_text())
    assert not {"score", "ascension", "birth_date", "death_date", "parents", "telemetry", "extra"} & set(data)


def test_absent_blobs_load_as_empty(tmp_path):
    individual = make()
    loaded = Individual.load(individual.save(tmp_path))
    assert loaded.genome == b"x"
    assert loaded.epigenome == b""
    assert loaded.phenome == b""


@pytest.mark.parametrize("score", [math.inf, -math.inf])
def test_infinite_scores(tmp_path, score):
    individual = make()
    individual.score = score
    assert Individual.load(individual.save(tmp_path)).score == score


def test_nan_score(tmp_path):
    individual = make()
    individual.score = math.nan
    assert math.isnan(Individual.load(individual.save(tmp_path)).score)


def test_load_null_means_unset(tmp_path):
    # Rust writes null for numbers that it cannot represent in JSON, such as infinity.
    directory = make().save(tmp_path)
    metadata = json.loads((directory / "metadata.json").read_text())
    metadata.update(score=None, ascension=None, birth_date=None)
    (directory / "metadata.json").write_text(json.dumps(metadata))
    loaded = Individual.load(directory)
    assert loaded.score is None
    assert loaded.ascension is None
    assert loaded.birth_date is None


@pytest.mark.parametrize("text", [
    "2026-10-03T12:30:45.5Z",
    "2026-10-03T12:30:45.5+00:00",  # This is how Rust writes timestamps
    "2026-10-03T08:30:45.5-04:00",
])
def test_load_timestamp_formats(tmp_path, text):
    directory = make().save(tmp_path)
    metadata = json.loads((directory / "metadata.json").read_text())
    metadata["birth_date"] = text
    (directory / "metadata.json").write_text(json.dumps(metadata))
    expected = datetime.datetime(2026, 10, 3, 12, 30, 45, 500000, tzinfo=datetime.timezone.utc)
    assert Individual.load(directory).birth_date == expected


def test_save_does_not_overwrite(tmp_path):
    individual = make(b"original")
    directory = individual.save(tmp_path)
    individual.genome = b"changed"
    with pytest.raises(FileExistsError):
        individual.save(tmp_path)
    assert (directory / "genome").read_bytes() == b"original"


def test_save_creates_directory(tmp_path):
    make().save(tmp_path / "new")
    assert (tmp_path / "new").is_dir()
    with pytest.raises(FileNotFoundError):  # Only one level is created
        make().save(tmp_path / "a" / "b")


@pytest.mark.parametrize("name", ["", ".", "..", "../escape", "a/b", "a\\b", "a\0b"])
def test_save_rejects_unsafe_names(tmp_path, name):
    individual = make()
    individual.name = name
    parent = tmp_path / "population"
    with pytest.raises(ValueError):
        individual.save(parent)
    assert list(tmp_path.rglob("*")) == []


def test_save_cleans_up_after_failure(tmp_path, monkeypatch):
    individual = make()
    real_write_bytes = pathlib.Path.write_bytes

    def failing_write_bytes(self, data):
        if self.name == "phenome":
            raise OSError("disk full")
        return real_write_bytes(self, data)

    monkeypatch.setattr(pathlib.Path, "write_bytes", failing_write_bytes)
    with pytest.raises(OSError, match="disk full"):
        individual.save(tmp_path)
    assert list(tmp_path.iterdir()) == []
    monkeypatch.undo()
    individual.save(tmp_path)  # The name is not poisoned by the failed attempt


@pytest.mark.parametrize("missing", ["metadata.json", "genome", "epigenome", "phenome"])
def test_load_requires_all_files(tmp_path, missing):
    directory = make().save(tmp_path)
    (directory / missing).unlink()
    with pytest.raises(FileNotFoundError):
        Individual.load(directory)


def test_load_invalid_metadata(tmp_path):
    directory = make().save(tmp_path)
    metadata = directory / "metadata.json"
    bad_metadata = (
        b"", b"not json", b"null", b"5", b'"text"', b"[]", b'["name"]',  # Not a JSON object
        b'{"name": 5}', b'{"name": []}', b'{"children": "many"}', b'{"score": "high"}',
        b'{"name": "x", "unknown_field": 1}',  # Only the "extra" field may contain custom fields
        b"\xff\xfe", b"\xef\xbb\xbf{}",  # Not UTF-8, UTF-8 with byte-order-mark
    )
    for bad in bad_metadata:
        metadata.write_bytes(bad)
        with pytest.raises(ValueError, match="metadata.json"):
            Individual.load(directory)
        with pytest.raises(ValueError, match="metadata.json"):
            Individual.load_dir(tmp_path)


def test_load_dir(tmp_path, make_full_individual):
    first = make_full_individual()
    second = make()
    first.save(tmp_path)
    second.save(tmp_path)
    (tmp_path / "stray-file.txt").write_text("ignored")
    loaded = Individual.load_dir(tmp_path)
    assert sorted(metadata.name for metadata in loaded) == sorted([first.name, second.name])
    by_name = {metadata.name: metadata for metadata in loaded}
    assert by_name[first.name] == first.to_proto().metadata
    # Any broken subdirectory is an error.
    (tmp_path / "broken").mkdir()
    with pytest.raises(FileNotFoundError):
        Individual.load_dir(tmp_path)


def test_delete(tmp_path):
    individual = make()
    directory = individual.save(tmp_path)
    Individual.delete(directory)
    assert not directory.exists()
    assert tmp_path.exists()
    with pytest.raises(FileNotFoundError):
        Individual.load(directory)
    individual.save(tmp_path)  # The name is free again


def test_delete_is_careful(tmp_path):
    with pytest.raises(ValueError):  # Not an individual
        (tmp_path / "other").mkdir()
        (tmp_path / "other" / "precious.txt").write_text("keep me")
        Individual.delete(tmp_path / "other")
    assert (tmp_path / "other" / "precious.txt").exists()
    # Unexpected files are never deleted.
    directory = make().save(tmp_path)
    (directory / "precious.txt").write_text("keep me")
    with pytest.raises(OSError):
        Individual.delete(directory)
    assert (directory / "precious.txt").read_text() == "keep me"


def test_reproduce_one_parent(make_full_individual):
    parent = make_full_individual(generation=3, children=3)
    before = copy.deepcopy(parent.to_proto())
    child = Individual.reproduce([parent])
    # Inherited from the parent
    assert child.environment == "test-env"
    assert child.body_type == "test-body"
    assert child.controller == ["test-ctrl", "--flag"]
    assert child.species == parent.species
    # Lineage
    assert child.parents == [parent.name]
    assert child.generation == 4
    assert child.name != parent.name
    # Everything else is unset
    assert child.score is None
    assert dict(child.telemetry) == {}
    assert child.children is None
    assert child.ascension is None
    assert child.birth_date is None
    assert child.death_date is None
    assert not child.to_proto().metadata.HasField("extra")
    assert child.genome is None
    assert child.epigenome is None
    assert child.phenome is None
    # The parent counted the child, and is otherwise unchanged.
    before.metadata.children = 4
    assert parent.to_proto() == before


def test_reproduce_founder():
    parent = Individual()
    child = Individual.reproduce([parent])
    assert child.generation == 1
    assert child.parents == [parent.name]
    assert child.species == parent.species
    assert parent.children == 1  # Counted from unset
    assert Individual.reproduce([parent]).name != child.name
    assert parent.children == 2


def test_reproduce_unset_generation_counts_as_zero():
    parent = Individual()
    parent.generation = None
    assert Individual.reproduce([parent]).generation == 1


def test_reproduce_many_parents(make_full_individual):
    mother = make_full_individual(generation=2, children=3)
    father = make_full_individual(generation=7, children=None, environment="other-env")
    third = make_full_individual(generation=None, children=3)
    child = Individual.reproduce([mother, father, third])
    # The first parent is the template, not the oldest parent.
    assert child.environment == "test-env"
    assert child.species == mother.species
    # Parents are in the order given, and generation comes from the oldest.
    assert child.parents == [mother.name, father.name, third.name]
    assert child.generation == 8
    # Every parent counted the child, starting from zero if unset.
    assert (mother.children, father.children, third.children) == (4, 1, 4)


def test_reproduce_without_parent_species(make_full_individual):
    # The child inherits the lack of species, it is not given a new one.
    parent = make_full_individual(species=None, environment=None)
    child = Individual.reproduce([parent])
    assert child.species is None
    assert child.environment is None


def test_reproduce_repeated_parent(make_full_individual):
    # Separate copies of the same individual are each updated.
    a = make_full_individual(generation=1)
    b = Individual.from_proto(copy.deepcopy(a.to_proto()))
    child = Individual.reproduce([a, b])
    assert child.parents == [a.name, a.name]
    assert child.generation == 2
    assert a.children == b.children == 4
    assert a == b
    # The very same object passed twice only counts the child once.
    c = make()
    assert Individual.reproduce([c, c]).parents == [c.name, c.name]
    assert c.children == 1


def test_reproduce_validates_parents():
    with pytest.raises(ValueError, match="at least one parent"):
        Individual.reproduce([])
    parent = Individual()
    with pytest.raises(TypeError):
        Individual.reproduce([parent, "not an individual"])
    assert parent.children is None  # Nothing was counted


def test_equality_with_other_types():
    individual = Individual()
    assert individual != 5
    assert not (individual == "text")
    assert individual not in [None, 5, "text"]
    assert individual in [None, individual]


def test_get_custom_score():
    individual = make()
    assert individual.get_custom_score() == -math.inf
    assert individual.get_custom_score("ascension") == -math.inf
    individual.score = 2.5
    individual.ascension = 9
    individual.telemetry["height"] = "1.5"
    assert individual.get_custom_score() == 2.5
    assert individual.get_custom_score("score") == 2.5
    assert individual.get_custom_score("ascension") == 9.0
    assert individual.get_custom_score("height") == 1.5
    assert individual.get_custom_score(lambda i: i.score * 2) == 5.0
    with pytest.raises(ValueError):
        individual.get_custom_score("nonexistent")
