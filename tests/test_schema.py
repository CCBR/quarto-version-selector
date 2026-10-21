"""Tests for versions.schema.json."""

import json
from importlib.resources import files

import jsonschema
import pytest
from click.testing import CliRunner

from quarto_version_selector.__main__ import cli
from quarto_version_selector.versions import (
    read_versions,
    update_versions,
    validate_versions,
    write_versions,
)

SCHEMA = json.loads(files("quarto_version_selector").joinpath("versions.schema.json").read_text())
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)


def test_schema_is_valid():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)


def test_written_versions_file_is_valid(tmp_path):
    versions = update_versions([], "1.0", ["latest"])
    versions = update_versions(versions, "1.1", ["latest", "stable"], title="v1.1")
    versions = update_versions(versions, "dev")
    path = tmp_path / "versions.json"
    write_versions(path, versions)
    VALIDATOR.validate(json.loads(path.read_text()))


def test_empty_list_is_valid():
    VALIDATOR.validate([])


@pytest.mark.parametrize(
    "data",
    [
        pytest.param({"version": "1.0"}, id="not-a-list"),
        pytest.param([{"version": "1.0", "title": "1.0"}], id="missing-aliases"),
        pytest.param([{"title": "1.0", "aliases": []}], id="missing-version"),
        pytest.param([{"version": "", "title": "x", "aliases": []}], id="empty-version"),
        pytest.param([{"version": "a/b", "title": "x", "aliases": []}], id="slash-in-version"),
        pytest.param([{"version": "..", "title": "x", "aliases": []}], id="dotdot-version"),
        pytest.param([{"version": "1.0", "title": "", "aliases": []}], id="empty-title"),
        pytest.param([{"version": 1.0, "title": "1.0", "aliases": []}], id="numeric-version"),
        pytest.param([{"version": "1.0", "title": "1.0", "aliases": "latest"}], id="aliases-not-list"),
        pytest.param([{"version": "1.0", "title": "1.0", "aliases": ["x", "x"]}], id="duplicate-alias"),
        pytest.param([{"version": "1.0", "title": "1.0", "aliases": ["../x"]}], id="bad-alias"),
        pytest.param([{"version": "1.0", "title": "1.0", "aliases": [], "extra": 1}], id="extra-key"),
    ],
)
def test_invalid_versions_rejected(data):
    assert not VALIDATOR.is_valid(data)


ENTRY = {"version": "1.0", "title": "1.0", "aliases": []}


def test_validate_rejects_names_reused_across_entries():
    data = [ENTRY, {"version": "1.1", "title": "1.1", "aliases": ["1.0"]}]
    with pytest.raises(ValueError, match="'1.0' is used 2 times"):
        validate_versions(data)


def test_validate_lists_all_errors():
    data = [{"version": "a/b", "title": "", "aliases": []}]
    with pytest.raises(ValueError) as err:
        validate_versions(data, source="x.json")
    assert "Invalid x.json" in str(err.value)
    assert "0/version" in str(err.value)
    assert "0/title" in str(err.value)


def test_read_rejects_invalid_file(tmp_path):
    path = tmp_path / "versions.json"
    path.write_text('[{"version": "1.0"}]')
    with pytest.raises(ValueError, match="aliases"):
        read_versions(path)
    path.write_text("not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        read_versions(path)


def test_read_missing_file_is_empty(tmp_path):
    assert read_versions(tmp_path / "versions.json") == []


def test_write_rejects_invalid_and_writes_nothing(tmp_path):
    path = tmp_path / "versions.json"
    with pytest.raises(ValueError):
        write_versions(path, [{**ENTRY, "version": "../x"}])
    assert not path.exists()


def test_cli_validate_file(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps([ENTRY]))
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{**ENTRY, "extra": 1}]))
    runner = CliRunner()
    ok = runner.invoke(cli, ["validate", str(good)])
    assert ok.exit_code == 0, ok.output
    assert "is valid (1 versions)" in ok.output
    fail = runner.invoke(cli, ["validate", str(bad)])
    assert fail.exit_code == 1
    assert "Additional properties" in fail.output
    missing = runner.invoke(cli, ["validate", str(tmp_path / "nope.json")])
    assert missing.exit_code == 1
