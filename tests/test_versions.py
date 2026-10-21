"""Tests for version logic, versions.json handling, and deploys."""

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from quarto_version_selector.__main__ import cli
from quarto_version_selector.deploy import alias, deploy, set_default_version
from quarto_version_selector.versions import (
    get_major_minor_version,
    get_version_and_alias,
    read_versions,
    sort_versions,
    update_versions,
)


def git(*args, cwd):
    """Run git in cwd and return stdout."""
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def commit(repo: Path, name: str) -> None:
    """Create a commit touching file ``name``."""
    (repo / name).write_text(name)
    git("add", name, cwd=repo)
    git("commit", "-m", name, cwd=repo)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo with a bare 'origin' remote and an initial commit."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "--bare", "-q", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    git("config", "user.email", "t@example.com", cwd=work)
    git("config", "user.name", "t", cwd=work)
    git("config", "commit.gpgsign", "false", cwd=work)
    git("remote", "add", "origin", str(origin), cwd=work)
    commit(work, "a")
    return work


@pytest.mark.parametrize(
    "tag,strict,expected",
    [
        ("v1.2.3", True, "1.2"),
        ("1.2", True, None),
        ("1.2", False, "1.2"),
        ("v2.0.0-rc1", True, "2.0"),
        ("x", False, None),
    ],
)
def test_major_minor(tag, strict, expected):
    assert get_major_minor_version(tag, strict_semver=strict) == expected


def test_version_latest_release(repo):
    git("tag", "v1.0.0", cwd=repo)
    assert get_version_and_alias("v1.0.0", "v1.0.0", cwd=repo) == ("1.0", "latest")
    assert get_version_and_alias(None, "v1.0.0", cwd=repo) == ("1.0", "latest")


def test_version_dev_and_old_release(repo):
    git("tag", "v1.0.0", cwd=repo)
    commit(repo, "b")
    git("tag", "v1.1.0", cwd=repo)
    commit(repo, "c")
    assert get_version_and_alias(None, "v1.1.0", cwd=repo) == ("dev", "")
    assert get_version_and_alias("v1.0.0", "v1.1.0", cwd=repo) == ("1.0", "")


def test_version_no_releases(repo):
    assert get_version_and_alias(None, "", cwd=repo) == ("dev", "")


def test_version_not_descendant(repo):
    git("checkout", "-q", "-b", "other", cwd=repo)
    commit(repo, "b")
    git("tag", "v1.0.0", cwd=repo)
    git("checkout", "-q", "main", cwd=repo)
    commit(repo, "c")
    with pytest.raises(ValueError, match="not a descendant"):
        get_version_and_alias(None, "v1.0.0", cwd=repo)


def test_version_bad_tag(repo):
    git("tag", "v1.0", cwd=repo)
    with pytest.raises(ValueError, match="semantic versioning"):
        get_version_and_alias(None, "v1.0", cwd=repo)


def test_sort_and_update():
    versions = update_versions([], "1.0", ["latest"])
    versions = update_versions(versions, "1.10", ["latest"])
    versions = update_versions(versions, "dev")
    versions = update_versions(versions, "1.2")
    assert [v["version"] for v in versions] == ["dev", "1.10", "1.2", "1.0"]
    assert {v["version"]: v["aliases"] for v in versions}["1.10"] == ["latest"]
    assert {v["version"]: v["aliases"] for v in versions}["1.0"] == []
    assert sort_versions(versions) == versions


def test_alias_clash():
    with pytest.raises(ValueError, match="conflict"):
        update_versions([{"version": "1.0", "title": "1.0", "aliases": []}], "1.1", ["1.0"])


def _site(repo: Path, text: str) -> None:
    site = repo / "_site"
    site.mkdir(exist_ok=True)
    (site / "index.html").write_text(text)


def _show(repo: Path, path: str) -> str:
    return git("show", f"origin/gh-pages:{path}", cwd=repo)


def test_deploy_two_versions(repo):
    _site(repo, "dev")
    assert deploy("dev", repo=repo, push=True)
    _site(repo, "one")
    assert deploy("1.0", ["latest"], set_default="latest", repo=repo, push=True)
    git("fetch", "-q", "origin", cwd=repo)

    versions = json.loads(_show(repo, "versions.json"))
    assert [(v["version"], v["aliases"]) for v in versions] == [("dev", []), ("1.0", ["latest"])]
    assert _show(repo, "dev/index.html") == "dev"
    assert _show(repo, "latest/index.html") == "one"
    assert "latest/" in _show(repo, "index.html")
    # source branch untouched
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo) == "main"
    assert git("worktree", "list", cwd=repo).count("\n") == 0


def test_alias_and_set_default(repo):
    _site(repo, "one")
    deploy("1.0", repo=repo, push=True)
    alias("1.0", ["stable"], repo=repo, push=True)
    set_default_version("stable", repo=repo, push=True)
    git("fetch", "-q", "origin", cwd=repo)
    assert _show(repo, "stable/index.html") == "one"
    assert "stable/" in _show(repo, "index.html")
    with pytest.raises(ValueError):
        alias("9.9", ["x"], repo=repo)


def test_deploy_missing_site(repo):
    with pytest.raises(FileNotFoundError):
        deploy("dev", repo=repo)


def test_cli_dry_run(repo, monkeypatch):
    monkeypatch.chdir(repo)
    result = CliRunner().invoke(cli, ["deploy", "--version", "dev", "--dry-run"])
    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert read_versions(repo / "versions.json") == []
