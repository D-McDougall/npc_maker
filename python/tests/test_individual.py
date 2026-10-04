import datetime
import json
import math
import pathlib

import pytest

from npc_maker.indiv import Individual


def test_new_individual():
    individual = Individual("test-env", "test-body", ["ctrl", "--flag"], b"genome")
    assert individual.environment == "test-env"
    assert individual.body_type == "test-body"
    assert individual.controller == ["ctrl", "--flag"]
    assert individual.genome == b"genome"
    assert individual.generation == 0
    assert individual.children == 0
    assert individual.parents == []
    assert individual.species
    # Not assigned until the individual lives and dies.
    assert individual.score is None
    assert individual.ascension is None
    assert individual.birth_date is None
    assert individual.death_date is None
    assert individual.epigenome is None
    assert individual.phenome is None


def test_name_is_uuid():
    names = {Individual("", "", [], b"x").name for _ in range(1000)}
    assert len(names) == 1000
    for name in names:
        assert len(name) == 32
        assert name == name.upper()
        int(name, 16)


def test_empty_genome_rejected():
    with pytest.raises(ValueError):
        Individual("", "", [], b"")


def test_controller_normalization():
    assert Individual("", "", "", b"x").controller == []
    assert Individual("", "", None, b"x").controller == []
    assert Individual("", "", "prog --flag 'a b'", b"x").controller == ["prog", "--flag", "a b"]
    assert Individual("", "", pathlib.Path("prog"), b"x").controller == ["prog"]
    assert Individual("", "", [pathlib.Path("prog"), 5], b"x").controller == ["prog", "5"]
    with pytest.raises(TypeError):
        Individual("", "", [b"prog"], b"x")


def test_optional_fields():
    individual = Individual("", "", [], b"x")
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
    individual = Individual("", "", [], b"x")
    individual.birth_date = datetime.datetime(2026, 1, 2, 3, 4, 5)  # Naive is assumed to be UTC
    assert individual.birth_date == datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc)
    eastern = datetime.timezone(datetime.timedelta(hours=-5))
    individual.death_date = datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=eastern)
    assert individual.death_date == datetime.datetime(2026, 1, 2, 8, 4, 5, tzinfo=datetime.timezone.utc)
    assert individual.death_date.utcoffset() == datetime.timedelta(0)


def test_telemetry_is_live_and_requires_strings():
    individual = Individual("", "", [], b"x")
    individual.telemetry["a"] = "1"
    individual.telemetry.update({"b": "2"})
    assert dict(individual.telemetry) == {"a": "1", "b": "2"}
    individual.telemetry = {"c": "3"}
    assert dict(individual.telemetry) == {"c": "3"}
    with pytest.raises(TypeError):
        individual.telemetry["d"] = 4


def test_proto_is_not_copied():
    individual = Individual("", "", [], b"x")
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
    individual = Individual("test-env", "test-body", [], b"genome")
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
    individual = Individual("", "", [], b"x")
    data = json.loads((individual.save(tmp_path) / "metadata.json").read_text())
    assert not {"score", "ascension", "birth_date", "death_date", "parents", "telemetry", "extra"} & set(data)


def test_absent_blobs_load_as_empty(tmp_path):
    individual = Individual("", "", [], b"x")
    loaded = Individual.load(individual.save(tmp_path))
    assert loaded.genome == b"x"
    assert loaded.epigenome == b""
    assert loaded.phenome == b""


@pytest.mark.parametrize("score", [math.inf, -math.inf])
def test_infinite_scores(tmp_path, score):
    individual = Individual("", "", [], b"x")
    individual.score = score
    assert Individual.load(individual.save(tmp_path)).score == score


def test_nan_score(tmp_path):
    individual = Individual("", "", [], b"x")
    individual.score = math.nan
    assert math.isnan(Individual.load(individual.save(tmp_path)).score)


def test_load_null_means_unset(tmp_path):
    # Rust writes null for numbers that it cannot represent in JSON, such as infinity.
    directory = Individual("", "", [], b"x").save(tmp_path)
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
    directory = Individual("", "", [], b"x").save(tmp_path)
    metadata = json.loads((directory / "metadata.json").read_text())
    metadata["birth_date"] = text
    (directory / "metadata.json").write_text(json.dumps(metadata))
    expected = datetime.datetime(2026, 10, 3, 12, 30, 45, 500000, tzinfo=datetime.timezone.utc)
    assert Individual.load(directory).birth_date == expected


def test_save_does_not_overwrite(tmp_path):
    individual = Individual("", "", [], b"original")
    directory = individual.save(tmp_path)
    individual.genome = b"changed"
    with pytest.raises(FileExistsError):
        individual.save(tmp_path)
    assert (directory / "genome").read_bytes() == b"original"


def test_save_creates_directory(tmp_path):
    Individual("", "", [], b"x").save(tmp_path / "new")
    assert (tmp_path / "new").is_dir()
    with pytest.raises(FileNotFoundError):  # Only one level is created
        Individual("", "", [], b"x").save(tmp_path / "a" / "b")


@pytest.mark.parametrize("name", ["", ".", "..", "../escape", "a/b", "a\\b", "a\0b"])
def test_save_rejects_unsafe_names(tmp_path, name):
    individual = Individual("", "", [], b"x")
    individual.name = name
    parent = tmp_path / "population"
    with pytest.raises(ValueError):
        individual.save(parent)
    assert list(tmp_path.rglob("*")) == []


def test_save_cleans_up_after_failure(tmp_path, monkeypatch):
    individual = Individual("", "", [], b"x")
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
    directory = Individual("", "", [], b"x").save(tmp_path)
    (directory / missing).unlink()
    with pytest.raises(FileNotFoundError):
        Individual.load(directory)


def test_load_invalid_metadata(tmp_path):
    directory = Individual("", "", [], b"x").save(tmp_path)
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
    second = Individual("", "", [], b"x")
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
    individual = Individual("", "", [], b"x")
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
    directory = Individual("", "", [], b"x").save(tmp_path)
    (directory / "precious.txt").write_text("keep me")
    with pytest.raises(OSError):
        Individual.delete(directory)
    assert (directory / "precious.txt").read_text() == "keep me"


def test_asex():
    parent = Individual("test-env", "test-body", ["ctrl"], b"parent genome")
    parent.generation = 3
    child = parent.asex(b"child genome")
    assert child.name != parent.name
    assert child.genome == b"child genome"
    assert child.parents == [parent.name]
    assert child.generation == 4
    assert child.environment == "test-env"
    assert child.body_type == "test-body"
    assert child.controller == ["ctrl"]
    assert child.species == parent.species
    assert child.children == 0
    assert child.score is None and child.ascension is None and child.phenome is None
    assert parent.children == 1
    parent.asex(b"another")
    assert parent.children == 2


def test_sex():
    mother = Individual("env", "body", ["ctrl"], b"m")
    father = Individual("env", "body", ["ctrl"], b"f")
    father.generation = 5
    child = Individual.sex([mother, father], b"child")
    assert child.parents == [mother.name, father.name]
    assert child.generation == 6
    assert child.species == mother.species
    assert (mother.children, father.children) == (1, 1)
    # Parents may repeat, but a child is only counted once by each parent.
    selfed = Individual.sex([mother, mother], b"selfed")
    assert selfed.parents == [mother.name, mother.name]
    assert mother.children == 2
    with pytest.raises(ValueError):
        Individual.sex([], b"orphan")
    with pytest.raises(TypeError):
        Individual.sex([mother, "not an individual"], b"x")


def test_get_custom_score():
    individual = Individual("", "", [], b"x")
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
