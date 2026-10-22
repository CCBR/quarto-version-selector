"""Tests for migrating mkdocs + mike deployments (quarto_version_selector.migrate)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from quarto_version_selector.__main__ import cli
from quarto_version_selector.migrate import (
    convert_snippets,
    fix_readme_links,
    fix_root_links,
    latest_tag_per_version,
    nav_to_sidebar,
    plan_migration,
    quarto_config,
)

ROOT = Path(__file__).resolve().parents[1]
requires_quarto = pytest.mark.skipif(shutil.which("quarto") is None, reason="quarto not installed")

NAV = [
    {"Home": "index.md"},
    {"Usage": [{"Getting Started": "getting-started.md"}, {"Ext": "https://example.com"}]},
    "changelog.md",
]


def git(*args, cwd):
    """Run git in cwd and return stdout."""
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def test_latest_tag_per_version():
    tags = ["v0.2.0", "v0.2.10", "v0.2.2", "v0.3.0", "v0.4.0-rc1", "not-a-tag"]
    assert latest_tag_per_version(tags) == {"0.2": "v0.2.10", "0.3": "v0.3.0"}


def test_nav_to_sidebar():
    assert nav_to_sidebar(NAV) == [
        {"href": "index.md", "text": "Home"},
        {
            "section": "Usage",
            "contents": [
                {"href": "getting-started.md", "text": "Getting Started"},
                {"href": "https://example.com", "text": "Ext"},
            ],
        },
        "changelog.md",
    ]
    assert nav_to_sidebar(None) == []


def test_convert_snippets_and_root_links(tmp_path):
    docs = tmp_path / "docs"
    (docs / "devs").mkdir(parents=True)
    (docs / "index.md").write_text('--8<-- "README.md"\nsee [n](/nextflow.md)\n')
    (docs / "devs" / "contributing.md").write_text(
        '--8<-- ".github/CONTRIBUTING.md"\nsee [n](/nextflow.md#x)\n'
    )
    convert_snippets(docs)
    fix_root_links(docs)
    assert (docs / "index.md").read_text() == "{{< include ../README.md >}}\nsee [n](./nextflow.md)\n"
    assert (docs / "devs" / "contributing.md").read_text() == (
        "{{< include ../../.github/CONTRIBUTING.md >}}\nsee [n](../nextflow.md#x)\n"
    )


def test_fix_readme_links(tmp_path):
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "CONTRIBUTING.md").write_text("c")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "s.csv").write_text("s")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "pic.png").write_text("p")
    (tmp_path / "README.md").write_text(
        "[c](.github/CONTRIBUTING.md) [s](/assets/s.csv) [u](https://x.org) [a](#top) "
        "[d](docs/pic.png) [m](missing.md)\n"
    )
    fix_readme_links(tmp_path, tmp_path / "docs", "https://github.com/O/R", "v1.0.0")
    base = "https://github.com/O/R/blob/v1.0.0/"
    assert (tmp_path / "README.md").read_text() == (
        f"[c]({base}.github/CONTRIBUTING.md) [s]({base}assets/s.csv) [u](https://x.org) [a](#top) "
        "[d](docs/pic.png) [m](missing.md)\n"
    )


def test_quarto_config_keeps_template_and_replaces_nav():
    template = {
        "project": {"type": "website", "output-dir": "_site", "resources": ["examples/*.html"]},
        "website": {
            "title": "T",
            "navbar": {"left": [{"href": "guide/new.md"}], "right": [{"icon": "github"}]},
        },
        "filters": ["version-selector"],
        "format": {"fnl-html": {"toc": True}},
    }
    config = quarto_config({"nav": NAV}, template)
    assert config["filters"] == ["version-selector"]
    assert config["format"] == template["format"]
    assert config["project"]["resources"] == ["examples/*.html"]
    assert config["project"]["render"] == ["**/*.md", "!**/_*.md"]
    assert config["website"]["navbar"] == {
        "left": [{"text": "Home", "href": "index.md"}],
        "right": [{"icon": "github"}],
    }
    assert config["website"]["sidebar"]["contents"][0] == {"href": "index.md", "text": "Home"}
    assert template["website"]["navbar"]["left"] == [{"href": "guide/new.md"}]  # template not mutated


def test_plan_migration():
    versions = [
        {"version": "dev", "title": "dev", "aliases": []},
        {"version": "0.10", "title": "0.10", "aliases": ["latest"]},
        {"version": "0.2", "title": "0.2", "aliases": []},
    ]
    tags = ["v0.2.0", "v0.2.1", "v0.10.0"]
    assert plan_migration(versions, tags) == [("0.2", "v0.2.1", []), ("0.10", "v0.10.0", ["latest"])]
    assert plan_migration(versions, tags, ["0.2"]) == [("0.2", "v0.2.1", [])]
    with pytest.raises(ValueError, match="Not listed"):
        plan_migration(versions, tags, ["9.9"])
    with pytest.raises(ValueError, match="git fetch --tags"):
        plan_migration(versions, ["v0.2.0"])


@pytest.fixture
def mike_repo(tmp_path: Path) -> Path:
    """A repo with two mkdocs releases and a mike-style gh-pages branch on a bare origin."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "--bare", "-q", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    for key, value in [("user.email", "t@example.com"), ("user.name", "t"), ("commit.gpgsign", "false")]:
        git("config", key, value, cwd=work)
    git("remote", "add", "origin", str(origin), cwd=work)

    docs = work / "docs"
    docs.mkdir()
    (work / "README.md").write_text("# Pkg\n\nSee [contributing](.github/CONTRIBUTING.md).\n")
    (work / ".github").mkdir()
    (work / ".github" / "CONTRIBUTING.md").write_text("# Contributing\n")
    (docs / "index.md").write_text('--8<-- "README.md"\n')
    for version in ["1.0", "1.1"]:
        (work / "mkdocs.yml").write_text(
            "site_name: Pkg\nrepo_url: https://github.com/O/R\n"
            "markdown_extensions:\n  - pymdownx.emoji:\n      emoji_index: !!python/name:material.extensions.emoji.twemoji\n"
            f"nav:\n  - Home: index.md\n  - Guide:\n      - Usage {version}: usage.md\n"
        )
        (docs / "usage.md").write_text(f"# Usage {version}\n\nBack to [home](/index.md).\n")
        git("add", "-A", cwd=work)
        git("commit", "-q", "-m", version, cwd=work)
        git("tag", f"v{version}.0", cwd=work)

    # mike-style gh-pages, built in a separate worktree
    pages = tmp_path / "pages"
    git("worktree", "add", "-q", "--orphan", "-b", "gh-pages", str(pages), cwd=work)
    mike_versions = [
        {"version": "1.1", "title": "1.1", "aliases": ["latest"]},
        {"version": "1.0", "title": "1.0", "aliases": []},
    ]
    (pages / "versions.json").write_text(json.dumps(mike_versions))
    for name in ["1.0", "1.1", "latest"]:
        (pages / name).mkdir()
        (pages / name / "index.html").write_text("mike")
    (pages / "index.html").write_text('<meta http-equiv="refresh" content="0; url=latest/">')
    git("add", "-A", cwd=pages)
    git("commit", "-q", "-m", "mike", cwd=pages)
    git("push", "-q", "origin", "gh-pages", cwd=pages)
    git("worktree", "remove", str(pages), cwd=work)
    git("branch", "-D", "gh-pages", cwd=work)

    # main: the current docs are Quarto
    git("rm", "-rq", "mkdocs.yml", "docs", cwd=work)
    project = work / "docs"
    project.mkdir()
    (project / "_quarto.yml").write_text(
        "project:\n  type: website\n  output-dir: _site\n"
        "website:\n  title: Pkg\n  navbar:\n    left:\n      - href: new-page.md\n"
        "filters:\n  - version-selector\nformat:\n  html: default\n"
    )
    shutil.copytree(ROOT / "_extensions", project / "_extensions")
    git("add", "-A", cwd=work)
    git("commit", "-q", "-m", "quarto", cwd=work)
    git("push", "-q", "origin", "main", cwd=work)
    return work


def test_cli_migrate_mike_dry_run(mike_repo, monkeypatch):
    monkeypatch.chdir(mike_repo)
    result = CliRunner().invoke(cli, ["migrate-mike", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == ["1.0: v1.0.0", "1.1: v1.1.0 [latest]"]
    assert git("show", "origin/gh-pages:1.0/index.html", cwd=mike_repo) == "mike"


def test_cli_migrate_mike_errors(mike_repo, monkeypatch):
    monkeypatch.chdir(mike_repo)
    result = CliRunner().invoke(cli, ["migrate-mike", "--versions", "9.9", "--dry-run"])
    assert result.exit_code == 1
    assert "Error: Not listed in versions.json: 9.9" in result.output
    result = CliRunner().invoke(cli, ["migrate-mike", "--project-dir", "nope", "--dry-run"])
    assert result.exit_code == 1
    assert "convert the current docs to Quarto first" in result.output


@requires_quarto
def test_migrate_mike_renders_and_deploys(mike_repo, monkeypatch):
    monkeypatch.chdir(mike_repo)
    result = CliRunner().invoke(cli, ["migrate-mike", "--push"])
    assert result.exit_code == 0, result.output
    git("fetch", "-q", "origin", cwd=mike_repo)

    def show(path):
        return git("show", f"origin/gh-pages:{path}", cwd=mike_repo)

    for version in ["1.0", "1.1"]:
        usage = show(f"{version}/usage.html")
        assert f"Usage {version}" in usage
        assert 'href="./index.html"' in usage  # root link fixed
        assert "version-selector" in usage
    assert "Usage 1.1" in show("latest/usage.html")
    assert "https://github.com/O/R/blob/v1.0.0/.github/CONTRIBUTING.md" in show("1.0/index.html")
    versions = json.loads(show("versions.json"))
    assert [(v["version"], v["aliases"]) for v in versions] == [("1.1", ["latest"]), ("1.0", [])]
    assert "url=latest/" in show("index.html")
    assert not git("worktree", "list", "--porcelain", cwd=mike_repo).count("worktree ") > 1
