"""Deploy rendered sites into version subfolders of a docs branch via git worktree."""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

from .versions import read_versions, redirect_html, update_versions, write_versions

VERSIONS_FILE = "versions.json"


def _git(*args: str, cwd: str | Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run git and return the completed process."""
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True)


def _ref_exists(ref: str, cwd: str | Path | None = None) -> bool:
    """Return True if ``ref`` resolves to a commit."""
    return _git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", cwd=cwd, check=False).returncode == 0


@contextlib.contextmanager
def docs_worktree(branch: str, remote: str = "origin", repo: str | Path = ".") -> Iterator[Path]:
    """
    Check out ``branch`` in a temporary git worktree.

    The branch is created from ``<remote>/<branch>`` if it exists, otherwise as
    an empty orphan branch.

    Args:
        branch: Docs branch name, e.g. ``gh-pages``.
        remote: Remote to fetch the branch from.
        repo: Path to the source repository.

    Yields:
        Path to the worktree.
    """
    repo = Path(repo).resolve()
    _git("fetch", remote, f"+refs/heads/{branch}:refs/remotes/{remote}/{branch}", cwd=repo, check=False)
    tmp = Path(tempfile.mkdtemp(prefix="qvs-worktree-"))
    worktree = tmp / "site"
    try:
        if _ref_exists(f"{remote}/{branch}", cwd=repo):
            _git("worktree", "add", "-B", branch, str(worktree), f"{remote}/{branch}", cwd=repo)
        elif _ref_exists(f"refs/heads/{branch}", cwd=repo):
            _git("worktree", "add", str(worktree), branch, cwd=repo)
        else:
            _git("worktree", "add", "--detach", str(worktree), cwd=repo)
            _git("checkout", "--orphan", branch, cwd=worktree)
            _git("rm", "-rf", "--quiet", ".", cwd=worktree, check=False)
        yield worktree
    finally:
        _git("worktree", "remove", "--force", str(worktree), cwd=repo, check=False)
        shutil.rmtree(tmp, ignore_errors=True)


def _replace_dir(src: Path, dest: Path) -> None:
    """Replace ``dest`` with a copy of ``src``."""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def _write_default(worktree: Path, target: str) -> None:
    """Write the root ``index.html`` redirecting to ``target``."""
    (worktree / "index.html").write_text(redirect_html(f"{target}/"))


def _commit_and_push(worktree: Path, branch: str, message: str, remote: str, push: bool) -> bool:
    """Commit all changes in the worktree; optionally push. Return True if committed."""
    _git("add", "--all", cwd=worktree)
    committed = _git("diff", "--cached", "--quiet", cwd=worktree, check=False).returncode != 0
    if committed:
        _git("commit", "-m", message, cwd=worktree)
    if push:
        _git("push", remote, f"{branch}:{branch}", cwd=worktree)
    return committed


def deploy(
    version: str,
    aliases: list[str] | None = None,
    site_dir: str | Path = "_site",
    branch: str = "gh-pages",
    title: str | None = None,
    set_default: str | None = None,
    remote: str = "origin",
    push: bool = False,
    repo: str | Path = ".",
    message: str | None = None,
) -> bool:
    """
    Deploy a rendered site to ``<branch>/<version>/`` and update ``versions.json``.

    Alias directories are full copies of the version so same-page navigation works.
    If the branch has no root ``index.html`` yet, one is created redirecting to
    the first alias (or the version).

    Args:
        version: Version directory name, e.g. ``1.2`` or ``dev``.
        aliases: Aliases such as ``latest``.
        site_dir: Rendered Quarto output directory.
        branch: Docs branch.
        title: Display title in the selector.
        set_default: Version or alias the root ``index.html`` should redirect to.
        remote: Git remote.
        push: Push the branch after committing.
        repo: Source repository path.
        message: Commit message.

    Returns:
        True if a commit was created.

    Raises:
        FileNotFoundError: If ``site_dir`` does not exist.
    """
    aliases = [a for a in (aliases or []) if a]
    site = Path(repo, site_dir).resolve() if not Path(site_dir).is_absolute() else Path(site_dir)
    if not site.is_dir():
        raise FileNotFoundError(f"Site directory not found: {site}. Did you run `quarto render`?")

    with docs_worktree(branch, remote=remote, repo=repo) as wt:
        versions = update_versions(read_versions(wt / VERSIONS_FILE), version, aliases, title)
        for name in [version, *aliases]:
            _replace_dir(site, wt / name)
        write_versions(wt / VERSIONS_FILE, versions)
        (wt / ".nojekyll").touch()
        default = set_default or (
            None if (wt / "index.html").exists() else (aliases[0] if aliases else version)
        )
        if default:
            _write_default(wt, default)
        alias_text = f" [{', '.join(aliases)}]" if aliases else ""
        committed = _commit_and_push(
            wt, branch, message or f"docs: deploy {version}{alias_text}", remote, push
        )
    return committed


def alias(
    version: str,
    aliases: list[str],
    branch: str = "gh-pages",
    remote: str = "origin",
    push: bool = False,
    repo: str | Path = ".",
) -> bool:
    """
    Point ``aliases`` at an already deployed ``version``.

    Raises:
        ValueError: If ``version`` has not been deployed.
    """
    with docs_worktree(branch, remote=remote, repo=repo) as wt:
        existing = read_versions(wt / VERSIONS_FILE)
        if not (wt / version).is_dir() or version not in {v["version"] for v in existing}:
            raise ValueError(f"Version '{version}' is not deployed on {branch}")
        for name in aliases:
            _replace_dir(wt / version, wt / name)
        write_versions(wt / VERSIONS_FILE, update_versions(existing, version, aliases))
        committed = _commit_and_push(
            wt, branch, f"docs: alias {version} as {', '.join(aliases)}", remote, push
        )
    return committed


def set_default_version(
    target: str,
    branch: str = "gh-pages",
    remote: str = "origin",
    push: bool = False,
    repo: str | Path = ".",
) -> bool:
    """
    Make the root ``index.html`` redirect to ``target`` (a version or alias).

    Raises:
        ValueError: If ``target`` is not deployed.
    """
    with docs_worktree(branch, remote=remote, repo=repo) as wt:
        if not (wt / target).is_dir():
            raise ValueError(f"'{target}' is not deployed on {branch}")
        _write_default(wt, target)
        committed = _commit_and_push(wt, branch, f"docs: set default version to {target}", remote, push)
    return committed
