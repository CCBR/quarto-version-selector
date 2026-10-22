"""
Version/alias logic and ``versions.json`` handling.

``versions.json`` is a list of
``{"version": str, "title": str, "aliases": [str, ...]}``.
"""

from __future__ import annotations

import html
import json
import re
import subprocess
import warnings
from functools import cache
from importlib.resources import files
from pathlib import Path
from urllib.parse import quote

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
        The tag name, or None if the repository has no releases.

    Raises:
        RuntimeError: If ``gh`` is missing or the lookup fails for any reason
            other than the repository having no releases (e.g. authentication,
            rate limits, or network errors).
    """
    cmd = ["gh", "release", "view", "--json", "tagName", "--jq", ".tagName"]
    if repo:
        cmd += ["--repo", repo]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError as err:
        raise RuntimeError("The GitHub CLI `gh` is required to look up the latest release") from err
    if result.returncode == 0:
        tag = result.stdout.strip() or None
    elif "release not found" in result.stderr.lower():
        tag = None
    else:
        raise RuntimeError(
            f"Failed to look up the latest release{f' of {repo}' if repo else ''}: "
            f"{result.stderr.strip() or f'gh exited with status {result.returncode}'}"
        )
    return tag


def get_tag_hash(tag: str, cwd: str | Path | None = None) -> str:
    """
    Return the commit hash a tag points to.

    Raises:
        ValueError: If the tag does not exist in the local repository.
    """
    try:
        tag_hash = _git("rev-list", "-n", "1", tag, cwd=cwd)
    except subprocess.CalledProcessError as err:
        raise ValueError(
            f"Tag '{tag}' was not found in the local git repository. "
            "Fetch tags with `git fetch --tags`, or use `fetch-depth: 0` with actions/checkout."
        ) from err
    return tag_hash


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
    require_descendant: bool = False,
) -> tuple[str, str]:
    """
    Determine the docs version and alias for the current commit.

    Rules (mirroring ``ccbr_actions.docs.get_docs_version``):

    - Building the latest release tag at its commit -> ``(major.minor, "latest")``.
    - ``release_tag`` is an older release -> ``(major.minor, "")``.
    - Otherwise -> ``("dev", "")``. If HEAD does not descend from the latest
      release (common with squash or rebase merges), a warning is emitted, or a
      ValueError is raised when ``require_descendant`` is True.

    Args:
        release_tag: Tag of the release being built (release events only).
        latest_release_tag: Latest release tag; looked up with ``gh`` if None.
        strict_semver: Require full semantic versioning in tags.
        repo: ``owner/name`` used for the ``gh`` lookup.
        cwd: Git working directory.
        require_descendant: Raise instead of warn when HEAD does not descend
            from the latest release.

    Returns:
        Tuple of ``(version, alias)``; alias may be an empty string.

    Raises:
        ValueError: If a tag is missing locally, the release tag is not a valid
            version, or ``require_descendant`` is True and HEAD does not descend
            from the latest release.
    """
    if latest_release_tag is None:
        latest_release_tag = get_latest_release_tag(repo=repo)
    if not release_tag:
        release_tag = latest_release_tag

    current_hash = _git("rev-parse", "HEAD", cwd=cwd)
    latest_hash = get_tag_hash(latest_release_tag, cwd=cwd) if latest_release_tag else ""

    # `latest` requires both the latest tag and its commit: an older tag on the
    # same commit as the latest release must not take the alias.
    if latest_hash and latest_hash == current_hash and release_tag == latest_release_tag:
        version, alias = _release_version(release_tag, strict_semver), LATEST_ALIAS
    elif release_tag and release_tag != latest_release_tag:
        version, alias = _release_version(release_tag, strict_semver), ""
    else:
        if latest_hash and not is_ancestor(latest_hash, current_hash, cwd=cwd):
            message = (
                f"The current commit {current_hash[:7]} is not a descendant of the "
                f"latest release {latest_release_tag} ({latest_hash[:7]}); "
                "this is expected after squash or rebase merges."
            )
            if require_descendant:
                raise ValueError(message)
            warnings.warn(f"{message} Deploying as '{DEV_VERSION}'.", UserWarning, stacklevel=2)
        version, alias = DEV_VERSION, ""
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


# root entries of the docs branch that must never be replaced by a version or alias
RESERVED_NAMES = frozenset({".git", ".nojekyll", "index.html", "versions.json", "404.html", "cname"})


def all_names(versions: list[dict]) -> set[str]:
    """Return every version and alias name in ``versions``."""
    return {name for entry in versions for name in [entry["version"], *entry.get("aliases", [])]}


def validate_versions(versions: object, source: str = "versions.json") -> None:
    """
    Validate ``versions.json`` data against the schema and cross-entry rules.

    Beyond the JSON Schema, every version and alias name must be unique across
    all entries and must not collide (case-insensitively) with files at the
    root of the docs branch, since each is a directory there.

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
        errors += [f"name '{name}' is reserved" for name in sorted(seen) if name.lower() in RESERVED_NAMES]
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
    """
    Return a minimal HTML page that redirects to the ``target`` directory.

    ``target`` is URL-encoded as a single path segment, then escaped for the
    HTML attribute and JavaScript string contexts it is used in.
    """
    url = quote(target, safe="") + "/"
    attr = html.escape(url, quote=True)
    js = json.dumps(url).replace("</", "<\\/")
    return (
        '<!DOCTYPE html>\n<html>\n<head>\n<meta charset="utf-8">\n'
        f'<title>Redirecting</title>\n<meta http-equiv="refresh" content="0; url={attr}">\n'
        f'<link rel="canonical" href="{attr}">\n'
        f"<script>window.location.replace({js} + window.location.hash);</script>\n"
        f'</head>\n<body><a href="{attr}">Redirecting to {html.escape(target)}</a></body>\n</html>\n'
    )
