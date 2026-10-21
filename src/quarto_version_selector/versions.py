"""
Version/alias logic and ``versions.json`` handling.

``versions.json`` is a list of
``{"version": str, "title": str, "aliases": [str, ...]}``.
"""

from __future__ import annotations

import json
import re
import subprocess
from functools import cache
from importlib.resources import files
from pathlib import Path

import jsonschema

DEV_VERSION = "dev"
LATEST_ALIAS = "latest"

STRICT_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
RELAXED_SEMVER = re.compile(r"^(\d+)\.(\d+)(?:\.\d+)?(?:[-+].*)?$")


def _git(*args: str, cwd: str | Path | None = None) -> str:
    """Run a git command and return stripped stdout."""
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def get_major_minor_version(version: str, strict_semver: bool = True) -> str | None:
    """
    Return ``major.minor`` from a version string, or None if it does not parse.

    Args:
        version: Version string, optionally prefixed with ``v``.
        strict_semver: Require full ``major.minor.patch`` semantic versioning.

    Returns:
        The ``major.minor`` string, or None.
    """
    pattern = STRICT_SEMVER if strict_semver else RELAXED_SEMVER
    match = pattern.match(version.lstrip("v"))
    return f"{match.group(1)}.{match.group(2)}" if match else None


def get_latest_release_tag(repo: str | None = None) -> str | None:
    """
    Return the tag of the latest GitHub release using the ``gh`` CLI.

    Args:
        repo: ``owner/name`` of the repository; defaults to the current repo.

    Returns:
        The tag name, or None if there are no releases.
    """
    cmd = ["gh", "release", "view", "--json", "tagName", "--jq", ".tagName"]
    if repo:
        cmd += ["--repo", repo]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    tag = result.stdout.strip() if result.returncode == 0 else ""
    return tag or None


def get_tag_hash(tag: str, cwd: str | Path | None = None) -> str:
    """Return the commit hash a tag points to."""
    return _git("rev-list", "-n", "1", tag, cwd=cwd)


def is_ancestor(ancestor: str, descendant: str, cwd: str | Path | None = None) -> bool:
    """Return True if ``ancestor`` is an ancestor of ``descendant``."""
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=cwd,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def get_version_and_alias(
    release_tag: str | None = None,
    latest_release_tag: str | None = None,
    strict_semver: bool = True,
    repo: str | None = None,
    cwd: str | Path | None = None,
) -> tuple[str, str]:
    """
    Determine the docs version and alias for the current commit.

    Rules (mirroring ``ccbr_actions.docs.get_docs_version``):

    - HEAD is the latest release -> ``(major.minor, "latest")``.
    - ``release_tag`` is an older release -> ``(major.minor, "")``.
    - Otherwise HEAD descends from the latest release (or there are no
      releases) -> ``("dev", "")``.

    Args:
        release_tag: Tag of the release being built (release events only).
        latest_release_tag: Latest release tag; looked up with ``gh`` if None.
        strict_semver: Require full semantic versioning in tags.
        repo: ``owner/name`` used for the ``gh`` lookup.
        cwd: Git working directory.

    Returns:
        Tuple of ``(version, alias)``; alias may be an empty string.

    Raises:
        ValueError: If HEAD does not descend from the latest release, or the
            release tag is not a valid version.
    """
    if latest_release_tag is None:
        latest_release_tag = get_latest_release_tag(repo=repo)
    if not release_tag:
        release_tag = latest_release_tag

    current_hash = _git("rev-parse", "HEAD", cwd=cwd)
    latest_hash = get_tag_hash(latest_release_tag, cwd=cwd) if latest_release_tag else ""

    if latest_hash and latest_hash == current_hash:
        version, alias = _release_version(release_tag, strict_semver), LATEST_ALIAS
    elif release_tag and release_tag != latest_release_tag:
        version, alias = _release_version(release_tag, strict_semver), ""
    elif not latest_hash or is_ancestor(latest_hash, current_hash, cwd=cwd):
        version, alias = DEV_VERSION, ""
    else:
        raise ValueError(
            f"The current commit {current_hash[:7]} is not a descendant of the "
            f"latest release {latest_release_tag} ({latest_hash[:7]})"
        )
    return version, alias


def _release_version(tag: str, strict_semver: bool) -> str:
    """Return ``major.minor`` for a release tag or raise ValueError."""
    version = get_major_minor_version(tag, strict_semver=strict_semver)
    if not version:
        raise ValueError(
            f"Cannot determine major.minor from release tag '{tag}'. Does the tag follow semantic versioning?"
        )
    return version


def _sort_key(entry: dict) -> tuple:
    """Sort dev (non-numeric) versions first, then releases newest first."""
    parts = entry["version"].split(".")
    if all(p.isdigit() for p in parts):
        return (1, [-int(p) for p in parts])
    return (0, entry["version"])


def sort_versions(versions: list[dict]) -> list[dict]:
    """Return versions with dev versions first, then releases newest first."""
    return sorted(versions, key=_sort_key)


@cache
def _validator() -> jsonschema.protocols.Validator:
    """Return a cached validator for ``versions.schema.json``."""
    schema = json.loads(files(__package__).joinpath("versions.schema.json").read_text())
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    return validator_cls(schema)


def validate_versions(versions: object, source: str = "versions.json") -> None:
    """
    Validate ``versions.json`` data against the schema and cross-entry rules.

    Beyond the JSON Schema, every version and alias name must be unique across
    all entries, since each is a directory on the docs branch.

    Args:
        versions: Parsed ``versions.json`` content.
        source: Label used in error messages, e.g. a file path.

    Raises:
        ValueError: If the data is invalid. All problems are listed.
    """
    errors = [
        f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
        for e in sorted(_validator().iter_errors(versions), key=lambda e: list(map(str, e.absolute_path)))
    ]
    if not errors:
        seen: dict[str, int] = {}
        for entry in versions:
            for name in [entry["version"], *entry["aliases"]]:
                seen[name] = seen.get(name, 0) + 1
        errors = [f"name '{name}' is used {n} times" for name, n in sorted(seen.items()) if n > 1]
    if errors:
        raise ValueError(f"Invalid {source}:\n  " + "\n  ".join(errors))


def read_versions(path: str | Path) -> list[dict]:
    """
    Read and validate ``versions.json``.

    Returns an empty list if the file does not exist.

    Raises:
        ValueError: If the file is not valid JSON or fails validation.
    """
    path = Path(path)
    data = []
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as err:
            raise ValueError(f"Invalid {path}: not valid JSON ({err})") from err
        validate_versions(data, source=str(path))
    return data


def write_versions(path: str | Path, versions: list[dict]) -> None:
    """
    Validate and write sorted ``versions.json``.

    Raises:
        ValueError: If ``versions`` fails validation; nothing is written.
    """
    versions = sort_versions(versions)
    validate_versions(versions, source=str(path))
    Path(path).write_text(json.dumps(versions, indent=2) + "\n")


def update_versions(
    versions: list[dict],
    version: str,
    aliases: list[str] | None = None,
    title: str | None = None,
) -> list[dict]:
    """
    Add or update ``version`` and move ``aliases`` onto it.

    Aliases are removed from any other version, so each alias is unique.

    Args:
        versions: Existing entries.
        version: Version to add or update.
        aliases: Aliases to attach to ``version``.
        title: Display title; defaults to the existing title or ``version``.

    Returns:
        A new, sorted list of entries.

    Raises:
        ValueError: If an alias equals an existing version name.
    """
    aliases = [a for a in (aliases or []) if a]
    names = {v["version"] for v in versions} | {version}
    clash = names.intersection(aliases)
    if clash:
        raise ValueError(f"Alias(es) conflict with version names: {sorted(clash)}")

    result = []
    found = None
    for entry in versions:
        entry = {**entry, "aliases": [a for a in entry.get("aliases", []) if a not in aliases]}
        if entry["version"] == version:
            found = entry
        result.append(entry)
    if found is None:
        found = {"version": version, "title": title or version, "aliases": []}
        result.append(found)
    if title:
        found["title"] = title
    found["aliases"] = sorted(set(found["aliases"]) | set(aliases))
    return sort_versions(result)


def redirect_html(target: str) -> str:
    """Return a minimal HTML page that redirects to ``target``."""
    return (
        '<!DOCTYPE html>\n<html>\n<head>\n<meta charset="utf-8">\n'
        f'<title>Redirecting</title>\n<meta http-equiv="refresh" content="0; url={target}">\n'
        f'<link rel="canonical" href="{target}">\n'
        f'<script>window.location.replace("{target}" + window.location.hash);</script>\n'
        f'</head>\n<body><a href="{target}">Redirecting to {target}</a></body>\n</html>\n'
    )
