"""
Migrate versions deployed by mkdocs + mike to Quarto.

For each version listed in the docs branch's ``versions.json`` (mike writes the
same format), the newest release tag for that ``major.minor`` is checked out
into a temporary git worktree. Its mkdocs docs are converted in place:

- the ``nav`` in ``mkdocs.yml`` becomes a Quarto sidebar,
- ``--8<-- "path"`` snippets become ``{{< include >}}`` shortcodes,
- root-relative page links (``](/page.md)``) become page-relative,
- README links to other repo files point at GitHub for that tag (the README is
  rendered inside the site, where relative links to repo files break).

The current Quarto project's ``_quarto.yml`` supplies the theme, filters and
footer, and its ``_extensions`` are copied in. The site is rendered and
deployed over the mike-built folder, keeping aliases (e.g. ``latest``).

Example usage::

    quarto-version-selector migrate-mike --dry-run
    quarto-version-selector migrate-mike --versions 0.6 --versions 0.7
    git push origin gh-pages
"""

from __future__ import annotations

import copy
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterable
from pathlib import Path

import yaml

from .deploy import VERSIONS_FILE, _git, deploy
from .versions import DEV_VERSION, LATEST_ALIAS, get_major_minor_version, read_versions

SNIPPET = re.compile(r'^--8<--[ \t]+"([^"]+)"[ \t]*$', re.MULTILINE)
ROOT_LINK = re.compile(r"\]\(/(?!/)([^)\s]+\.md[^)\s]*)\)")
MARKDOWN_LINK = re.compile(r"\]\(([^)\s]+)\)")


class _MkdocsLoader(yaml.SafeLoader):
    """SafeLoader that ignores mkdocs' ``!!python/name:`` tags."""


_MkdocsLoader.add_multi_constructor("tag:yaml.org,2002:python/", lambda loader, suffix, node: None)


def latest_tag_per_version(tags: Iterable[str]) -> dict[str, str]:
    """
    Map each ``major.minor`` to its newest release tag, skipping pre-releases.

    Args:
        tags: Tag names, e.g. ``["v0.2.0", "v0.2.2"]``.

    Returns:
        ``{"0.2": "v0.2.2", ...}``; tags that are not semantic versions are skipped.
    """
    best: dict[str, tuple[tuple[int, ...], str]] = {}
    for tag in tags:
        version = get_major_minor_version(tag, strict_semver=True)
        if not version or "-" in tag:
            continue
        key = tuple(int(p) for p in tag.lstrip("v").split("+")[0].split("."))
        if version not in best or key > best[version][0]:
            best[version] = (key, tag)
    return {version: tag for version, (_, tag) in best.items()}


def nav_to_sidebar(nav: list | None) -> list:
    """
    Convert an mkdocs ``nav`` list into Quarto ``website.sidebar.contents``.

    Args:
        nav: The ``nav`` value from mkdocs.yml.

    Returns:
        Quarto sidebar contents.
    """
    contents: list = []
    for item in nav or []:
        if isinstance(item, str):
            contents.append(item)
            continue
        for text, target in item.items():
            if isinstance(target, list):
                contents.append({"section": text, "contents": nav_to_sidebar(target)})
            else:
                contents.append({"href": target, "text": text})
    return contents


def convert_snippets(docs_dir: Path) -> None:
    """
    Replace mkdocs ``--8<-- "path"`` snippets with Quarto include shortcodes.

    Snippet paths are relative to the repo root (the parent of ``docs_dir``);
    include paths are relative to the page.
    """
    for md in docs_dir.rglob("*.md"):
        text = md.read_text()
        if "--8<--" not in text:
            continue
        prefix = "../" * len(md.relative_to(docs_dir).parts)
        md.write_text(SNIPPET.sub(rf"{{{{< include {prefix}\1 >}}}}", text))


def fix_root_links(docs_dir: Path) -> None:
    """Rewrite root-relative page links like ``](/nextflow.md)`` to page-relative ones."""
    for md in docs_dir.rglob("*.md"):
        prefix = "../" * (len(md.relative_to(docs_dir).parts) - 1) or "./"
        text = md.read_text()
        fixed = ROOT_LINK.sub(rf"]({prefix}\1)", text)
        if fixed != text:
            md.write_text(fixed)


def fix_readme_links(root: Path, docs_dir: Path, repo_url: str, ref: str) -> None:
    """
    Point README links to repo files outside ``docs_dir`` at GitHub.

    Links to URLs, anchors, and files inside ``docs_dir`` are left alone.

    Args:
        root: Repository root (contains README.md).
        docs_dir: mkdocs docs directory.
        repo_url: Repository URL, e.g. ``https://github.com/OWNER/REPO``.
        ref: Git ref to link to, e.g. the release tag.
    """
    readme = root / "README.md"
    if not readme.is_file() or not repo_url:
        return
    base = f"{repo_url.rstrip('/')}/blob/{ref}/"

    def replace(match: re.Match) -> str:
        target = match.group(1)
        path = target.split("#")[0].lstrip("/")
        if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#") or not path:
            return match.group(0)
        resolved = (root / path).resolve()
        if not resolved.exists() or resolved.is_relative_to(docs_dir.resolve()):
            return match.group(0)
        return f"]({base}{target.lstrip('/')})"

    text = readme.read_text()
    fixed = MARKDOWN_LINK.sub(replace, text)
    if fixed != text:
        readme.write_text(fixed)


def quarto_config(mkdocs: dict, template: dict) -> dict:
    """
    Build a ``_quarto.yml`` for an old release.

    The current ``_quarto.yml`` (``template``) supplies the theme, filters and
    footer; the old mkdocs nav supplies the sidebar. Every page except
    ``_``-prefixed partials is rendered, so pages linked but missing from the nav
    still work. The navbar is reduced to a Home link because current navbar
    targets may not exist in old releases.

    Args:
        mkdocs: Parsed mkdocs.yml of the old release.
        template: Parsed current ``_quarto.yml``.

    Returns:
        The new Quarto config.
    """
    config = copy.deepcopy(template)
    project = config.setdefault("project", {})
    project["type"] = "website"
    project["render"] = ["**/*.md", "!**/_*.md"]
    website = config.setdefault("website", {})
    website["sidebar"] = {"style": "docked", "contents": nav_to_sidebar(mkdocs.get("nav"))}
    navbar = website.setdefault("navbar", {})
    navbar["left"] = [{"text": "Home", "href": "index.md"}]
    return config


def build_version(tag: str, repo: Path, template: dict, extensions: Path | None, worktree: Path) -> Path:
    """
    Check out ``tag`` into ``worktree``, convert its mkdocs docs, and render them.

    Args:
        tag: Release tag to build.
        repo: Source repository.
        template: Parsed current ``_quarto.yml``.
        extensions: Current ``_extensions`` directory to copy in, if any.
        worktree: Path for the temporary git worktree (must not exist).

    Returns:
        The rendered site directory.

    Raises:
        FileNotFoundError: If the tag has no mkdocs.yml.
        RuntimeError: If quarto is missing or rendering fails.
    """
    _git("worktree", "add", "--detach", str(worktree), tag, cwd=repo)
    mkdocs_path = worktree / "mkdocs.yml"
    if not mkdocs_path.is_file():
        raise FileNotFoundError(f"{tag} has no mkdocs.yml; was it built with mkdocs?")
    mkdocs = yaml.load(mkdocs_path.read_text(), Loader=_MkdocsLoader) or {}
    docs = worktree / mkdocs.get("docs_dir", "docs")
    convert_snippets(docs)
    fix_root_links(docs)
    fix_readme_links(worktree, docs, mkdocs.get("repo_url", ""), tag)
    config = quarto_config(mkdocs, template)
    (docs / "_quarto.yml").write_text(yaml.safe_dump(config, sort_keys=False))
    if extensions and extensions.is_dir():
        shutil.rmtree(docs / "_extensions", ignore_errors=True)
        shutil.copytree(extensions, docs / "_extensions")
    try:
        subprocess.run(["quarto", "render", str(docs)], check=True)
    except FileNotFoundError as err:
        raise RuntimeError(
            "quarto is required to render the docs; install it from https://quarto.org"
        ) from err
    except subprocess.CalledProcessError as err:
        raise RuntimeError(f"quarto render failed for {tag} (exit status {err.returncode})") from err
    return docs / config["project"].get("output-dir", "_site")


def plan_migration(
    versions: list[dict], tags: Iterable[str], only: Iterable[str] = ()
) -> list[tuple[str, str, list[str]]]:
    """
    Pair each deployed version with the release tag to rebuild it from.

    Args:
        versions: Entries of the docs branch's versions.json.
        tags: All git tags in the repository.
        only: Restrict to these versions (default: all except ``dev``).

    Returns:
        ``(version, tag, aliases)`` tuples, oldest first so the newest
        release's aliases are written last.

    Raises:
        ValueError: If a requested version is not deployed or has no release tag.
    """
    only = set(only)
    deployed = {v["version"] for v in versions}
    missing = only - deployed
    if missing:
        raise ValueError(f"Not listed in {VERSIONS_FILE}: {', '.join(sorted(missing))}")
    latest = latest_tag_per_version(tags)
    plan = []
    for entry in versions:
        version = entry["version"]
        if version == DEV_VERSION or (only and version not in only):
            continue
        if version not in latest:
            raise ValueError(
                f"No release tag found for deployed version {version}. Fetch tags with `git fetch --tags`."
            )
        plan.append((version, latest[version], list(entry.get("aliases", []))))
    plan.sort(key=lambda p: tuple(int(x) for x in p[0].split(".")))
    return plan


def migrate_mike(
    project_dir: str | Path = "docs",
    versions: Iterable[str] = (),
    branch: str = "gh-pages",
    remote: str = "origin",
    push: bool = False,
    dry_run: bool = False,
    repo: str | Path = ".",
    echo=print,
) -> list[tuple[str, str, list[str]]]:
    """
    Re-render mike-deployed versions with Quarto and redeploy them.

    Args:
        project_dir: Current Quarto project directory, relative to ``repo``.
        versions: Only migrate these versions (default: all except ``dev``).
        branch: Docs branch.
        remote: Git remote.
        push: Push after each deploy.
        dry_run: Only return and print the plan.
        repo: Source repository path.
        echo: Function used to report progress.

    Returns:
        The migration plan as ``(version, tag, aliases)`` tuples.

    Raises:
        FileNotFoundError: If the project has no _quarto.yml or the branch has no versions.json.
        RuntimeError: If fetching the docs branch or rendering fails.
        ValueError: If a version cannot be matched to a release tag.
    """
    repo = Path(_git("rev-parse", "--show-toplevel", cwd=repo).stdout.strip())
    project = repo / project_dir
    quarto_yml = project / "_quarto.yml"
    if not quarto_yml.is_file():
        raise FileNotFoundError(f"{quarto_yml} not found; convert the current docs to Quarto first")
    fetch = _git("fetch", remote, f"+{branch}:refs/remotes/{remote}/{branch}", cwd=repo, check=False)
    if fetch.returncode != 0:
        raise RuntimeError(f"Could not fetch {remote}/{branch}: {fetch.stderr.strip()}")
    shown = _git("show", f"{remote}/{branch}:{VERSIONS_FILE}", cwd=repo, check=False)
    if shown.returncode != 0:
        raise FileNotFoundError(f"{VERSIONS_FILE} not found on {remote}/{branch}")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp, VERSIONS_FILE)
        path.write_text(shown.stdout)
        deployed = read_versions(path)

    plan = plan_migration(deployed, _git("tag", cwd=repo).stdout.split(), versions)
    for version, tag, aliases in plan:
        echo(f"{version}: {tag}" + (f" [{', '.join(aliases)}]" if aliases else ""))
    if dry_run:
        return plan

    template = yaml.safe_load(quarto_yml.read_text()) or {}
    for version, tag, aliases in plan:
        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp, "src")
            try:
                site = build_version(tag, repo, template, project / "_extensions", worktree)
                deploy(
                    version,
                    aliases,
                    site_dir=site,
                    branch=branch,
                    set_default=LATEST_ALIAS if LATEST_ALIAS in aliases else None,
                    remote=remote,
                    push=push,
                    repo=repo,
                    message=f"docs: redeploy {version} ({tag}) with quarto",
                )
            finally:
                _git("worktree", "remove", "--force", str(worktree), cwd=repo, check=False)
        echo(f"Redeployed {version} from {tag}")
    return plan
