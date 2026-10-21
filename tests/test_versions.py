"""Tests for version logic, versions.json handling, and deploys."""

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from quarto_version_selector import versions as versions_module
from quarto_version_selector.__main__ import cli
from quarto_version_selector.deploy import alias, deploy, docs_worktree, set_default_version
from quarto_version_selector.versions import (
    get_major_minor_version,
    get_version_and_alias,
    read_versions,
    redirect_html,
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


def test_commands_refuse_corrupt_versions_json(repo):
    """deploy, alias, and set-default all validate the existing versions.json first."""
    _site(repo, "one")
    deploy("1.0", repo=repo, push=True)
    with docs_worktree("gh-pages", repo=repo) as wt:
        (wt / "versions.json").write_text('[{"version": "1.0"}]')
        git("commit", "-qam", "corrupt", cwd=wt)
        git("push", "-q", "origin", "gh-pages", cwd=wt)
    with pytest.raises(ValueError, match="Invalid"):
        deploy("1.1", repo=repo)
    with pytest.raises(ValueError, match="Invalid"):
        alias("1.0", ["stable"], repo=repo)
    with pytest.raises(ValueError, match="Invalid"):
        set_default_version("1.0", repo=repo)


def test_cli_validate_branch(repo, monkeypatch):
    _site(repo, "one")
    deploy("1.0", ["latest"], repo=repo, push=True)
    monkeypatch.chdir(repo)
    result = CliRunner().invoke(cli, ["validate"])
    assert result.exit_code == 0, result.output
    assert "gh-pages:versions.json is valid (1 versions)" in result.output


# --- review fixes -------------------------------------------------------------


@pytest.mark.parametrize("bad", ["../victim", "/abs/victim", "a/b", ".."])
def test_deploy_rejects_bad_names_before_touching_disk(repo, tmp_path, bad):
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("keep")
    _site(repo, "one")
    with pytest.raises(ValueError):
        deploy("1.0", [bad], repo=repo)
    with pytest.raises(ValueError):
        deploy(bad, repo=repo)
    assert (victim / "keep.txt").read_text() == "keep"


@pytest.mark.parametrize("bad", ["../victim", "/abs/victim", "", "versions.json"])
def test_alias_rejects_bad_names_before_touching_disk(repo, tmp_path, bad):
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("keep")
    _site(repo, "one")
    deploy("1.0", repo=repo, push=True)
    with pytest.raises(ValueError):
        alias("1.0", [bad], repo=repo)
    assert (victim / "keep.txt").read_text() == "keep"


def test_redeploy_refreshes_existing_aliases(repo):
    _site(repo, "old")
    deploy("1.0", ["stable"], repo=repo, push=True)
    _site(repo, "new")
    deploy("1.0", repo=repo, push=True)
    git("fetch", "-q", "origin", cwd=repo)
    assert _show(repo, "stable/index.html") == "new"
    assert json.loads(_show(repo, "versions.json"))[0]["aliases"] == ["stable"]


def test_deploy_set_default_must_be_deployed(repo):
    _site(repo, "one")
    with pytest.raises(ValueError, match="not a deployed version or alias"):
        deploy("1.0", set_default="latest", repo=repo)
    deploy("1.0", ["latest"], set_default="latest", repo=repo, push=True)


@pytest.mark.parametrize("target", [".", "nope"])
def test_set_default_requires_manifest_entry(repo, target):
    _site(repo, "one")
    deploy("1.0", repo=repo, push=True)
    with docs_worktree("gh-pages", repo=repo) as wt:
        (wt / "nope").mkdir()
        (wt / "nope" / "index.html").write_text("x")
        git("add", ".", cwd=wt)
        git("commit", "-qm", "stray dir", cwd=wt)
        git("push", "-q", "origin", "gh-pages", cwd=wt)
    with pytest.raises(ValueError, match="not a deployed version or alias"):
        set_default_version(target, repo=repo)


def test_local_unpushed_deploys_are_preserved(repo):
    _site(repo, "one")
    deploy("1.0", repo=repo, push=True)
    _site(repo, "two")
    deploy("1.1", repo=repo)  # not pushed
    set_default_version("1.1", repo=repo)  # must not discard the 1.1 deploy
    files = git("ls-tree", "--name-only", "gh-pages", cwd=repo).split()
    assert "1.1" in files
    assert "1.1/" in git("show", "gh-pages:index.html", cwd=repo)


def test_local_branch_fast_forwards_to_remote(repo, tmp_path):
    _site(repo, "one")
    deploy("1.0", repo=repo, push=True)
    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", "-q", git("remote", "get-url", "origin", cwd=repo), str(other)], check=True
    )
    git("config", "user.email", "t@example.com", cwd=other)
    git("config", "user.name", "t", cwd=other)
    _site(other, "two")
    deploy("1.1", repo=other, push=True)
    deploy("1.2", repo=repo, push=True)  # local gh-pages is behind; must fast-forward, not fail
    git("fetch", "-q", "origin", cwd=repo)
    names = [v["version"] for v in json.loads(_show(repo, "versions.json"))]
    assert names == ["1.2", "1.1", "1.0"]


def test_diverged_branches_are_rejected(repo, tmp_path):
    _site(repo, "one")
    deploy("1.0", repo=repo, push=True)
    _site(repo, "local")
    deploy("1.2", repo=repo)  # local-only commit
    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", "-q", git("remote", "get-url", "origin", cwd=repo), str(other)], check=True
    )
    git("config", "user.email", "t@example.com", cwd=other)
    git("config", "user.name", "t", cwd=other)
    _site(other, "two")
    deploy("1.1", repo=other, push=True)  # remote moves on -> local and remote diverge
    local_before = git("rev-parse", "gh-pages", cwd=repo)
    with pytest.raises(RuntimeError, match="diverged"):
        deploy("1.3", repo=repo)
    assert git("rev-parse", "gh-pages", cwd=repo) == local_before


@pytest.mark.parametrize(
    "name,expected",
    [("1.0", "1.0/"), ("release#1", "release%231/"), ("a?b", "a%3Fb/"), ('x"y', "x%22y/"), ("a b", "a%20b/")],
)
def test_redirect_html_encodes_target(name, expected):
    page = redirect_html(name)
    assert f'url={expected}"' in page
    assert f'href="{expected}"' in page
    assert f'replace("{expected}"' in page
    assert '"y' not in page.replace("x%22y", "")


class _Result:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


@pytest.mark.parametrize(
    "result,expected",
    [(_Result(0, "v1.2.0\n"), "v1.2.0"), (_Result(1, stderr="release not found"), None)],
)
def test_latest_release_tag(monkeypatch, result, expected):
    monkeypatch.setattr(versions_module.subprocess, "run", lambda *a, **k: result)
    assert versions_module.get_latest_release_tag("o/r") == expected


@pytest.mark.parametrize("stderr", ["HTTP 401: Bad credentials", "API rate limit exceeded", ""])
def test_latest_release_tag_raises_on_lookup_failure(monkeypatch, stderr):
    monkeypatch.setattr(versions_module.subprocess, "run", lambda *a, **k: _Result(1, stderr=stderr))
    with pytest.raises(RuntimeError, match="Failed to look up the latest release of o/r"):
        versions_module.get_latest_release_tag("o/r")


def test_latest_release_tag_without_gh(monkeypatch):
    def missing(*a, **k):
        raise FileNotFoundError("gh")

    monkeypatch.setattr(versions_module.subprocess, "run", missing)
    with pytest.raises(RuntimeError, match="GitHub CLI"):
        versions_module.get_latest_release_tag()
