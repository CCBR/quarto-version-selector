"""Deploy rendered sites into version subfolders of a docs branch via git worktree."""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

from .versions import (
    all_names,
    is_ancestor,
    read_versions,
    redirect_html,
    update_versions,
    validate_versions,
    write_versions,
)

VERSIONS_FILE = "versions.json"
PUSH_RETRIES = 3


class PushRejectedError(RuntimeError):
    """The docs branch push was rejected because the remote moved on."""


def _git(*args: str, cwd: str | Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run git and return the completed process."""
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True)


def _ref_exists(ref: str, cwd: str | Path | None = None) -> bool:
    """Return True if ``ref`` resolves to a commit."""
    return _git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", cwd=cwd, check=False).returncode == 0


def _sync_local_branch(branch: str, remote: str, repo: Path) -> bool:
    """
    Bring the local docs branch up to date with ``<remote>/<branch>`` without losing commits.

    - Only the remote branch exists: create the local branch from it.
    - The local branch is behind: fast-forward it.
    - The local branch is ahead (unpublished deploys): keep it.
    - The branches have diverged: refuse.

    Returns:
        True if the local branch exists afterwards.

    Raises:
        RuntimeError: If the local and remote branches have diverged.
    """
    local_ref = f"refs/heads/{branch}"
    remote_ref = f"refs/remotes/{remote}/{branch}"
    has_local = _ref_exists(local_ref, cwd=repo)
    if _ref_exists(remote_ref, cwd=repo):
        remote_sha = _git("rev-parse", remote_ref, cwd=repo).stdout.strip()
        if not has_local:
            _git("branch", branch, remote_sha, cwd=repo)
        else:
            local_sha = _git("rev-parse", local_ref, cwd=repo).stdout.strip()
            if local_sha != remote_sha and is_ancestor(local_sha, remote_sha, cwd=repo):
                # compare-and-swap so a concurrent update is not overwritten
                _git("update-ref", local_ref, remote_sha, local_sha, cwd=repo)
            elif local_sha != remote_sha and not is_ancestor(remote_sha, local_sha, cwd=repo):
                raise RuntimeError(
                    f"Local branch '{branch}' has diverged from '{remote}/{branch}'. "
                    f"Reconcile them (e.g. push or reset '{branch}') before deploying."
                )
        has_local = True
    return has_local


@contextlib.contextmanager
def docs_worktree(branch: str, remote: str = "origin", repo: str | Path = ".") -> Iterator[Path]:
    """
    Check out ``branch`` in a temporary git worktree.

    The local branch is synced with ``<remote>/<branch>`` first (see
    ``_sync_local_branch``), so unpublished local deploys are preserved. If
    neither exists, an empty orphan branch is created.

    Args:
        branch: Docs branch name, e.g. ``gh-pages``.
        remote: Remote to fetch the branch from.
        repo: Path to the source repository.

    Yields:
        Path to the worktree.

    Raises:
        RuntimeError: If the local and remote branches have diverged.
    """
    repo = Path(repo).resolve()
    _git("fetch", remote, f"+refs/heads/{branch}:refs/remotes/{remote}/{branch}", cwd=repo, check=False)
    has_local = _sync_local_branch(branch, remote, repo)
    tmp = Path(tempfile.mkdtemp(prefix="qvs-worktree-"))
    worktree = tmp / "site"
    try:
        if has_local:
            _git("worktree", "add", str(worktree), branch, cwd=repo)
        else:
            _git("worktree", "add", "--detach", str(worktree), cwd=repo)
            _git("checkout", "--orphan", branch, cwd=worktree)
            _git("rm", "-rf", "--quiet", ".", cwd=worktree, check=False)
        yield worktree
    finally:
        _git("worktree", "remove", "--force", str(worktree), cwd=repo, check=False)
        shutil.rmtree(tmp, ignore_errors=True)


def _child_dir(worktree: Path, name: str) -> Path:
    """
    Return ``worktree / name`` (unresolved), ensuring it is a direct child of the worktree.

    Names are validated by the schema before this is called; this is a second
    guard so a bad name can never delete or write outside the worktree. The
    path is returned unresolved so an existing symlink (e.g. an alias that
    links to a version) is replaced itself rather than its target.

    Raises:
        ValueError: If ``name`` is not a single path component or a
            non-symlink entry resolves outside ``worktree``.
    """
    root = worktree.resolve()
    if not name or name in (".", "..") or Path(name).name != name or "\\" in name:
        raise ValueError(f"Refusing to write outside the docs worktree: {name!r}")
    path = root / name
    if not path.is_symlink() and path.resolve().parent != root:
        raise ValueError(f"Refusing to write outside the docs worktree: {name!r}")
    return path


def _replace_dir(src: Path, worktree: Path, name: str) -> None:
    """Replace the ``name`` directory of the worktree with a copy of ``src``."""
    dest = _child_dir(worktree, name)
    if dest.is_symlink() or dest.is_file():
        dest.unlink()
    elif dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def _write_default(worktree: Path, target: str) -> None:
    """Write the root ``index.html`` redirecting to the ``target`` directory."""
    _child_dir(worktree, target)
    (worktree / "index.html").write_text(redirect_html(target))


def _require_deployed(target: str, versions: list[dict], worktree: Path | None, branch: str) -> None:
    """
    Require ``target`` to be a registered version or alias (and, if given, present in the worktree).

    Raises:
        ValueError: If ``target`` is not deployed.
    """
    if target not in all_names(versions) or (worktree is not None and not (worktree / target).is_dir()):
        raise ValueError(f"'{target}' is not a deployed version or alias on {branch}")


def _commit_and_push(worktree: Path, branch: str, message: str, remote: str, push: bool) -> bool:
    """
    Commit all changes in the worktree; optionally push. Return True if committed.

    Raises:
        PushRejectedError: If the push is rejected because the remote branch moved.
        subprocess.CalledProcessError: If the push fails for another reason.
    """
    _git("add", "--all", cwd=worktree)
    committed = _git("diff", "--cached", "--quiet", cwd=worktree, check=False).returncode != 0
    if committed:
        _git("commit", "-m", message, cwd=worktree)
    if push:
        result = _git("push", remote, f"{branch}:{branch}", cwd=worktree, check=False)
        if result.returncode != 0:
            stderr = result.stderr.lower()
            if any(s in stderr for s in ("rejected", "fetch first", "non-fast-forward")):
                raise PushRejectedError(f"Push to {remote}/{branch} was rejected: {result.stderr.strip()}")
            raise subprocess.CalledProcessError(
                result.returncode, result.args, output=result.stdout, stderr=result.stderr
            )
    return committed


def _with_push_retry(operation, branch: str, remote: str, repo: str | Path, push: bool) -> bool:
    """
    Run ``operation`` and, if its push is rejected, rewind the local docs branch and retry.

    Concurrent deploys (e.g. a push to main and a release) can start from the
    same docs-branch tip; the second push is then rejected. Rewinding the local
    branch to where it was before the attempt and re-running the operation
    rebuilds the change on top of the new remote tip.

    Raises:
        PushRejectedError: If the push is still rejected after ``PUSH_RETRIES`` retries.
    """
    repo = Path(repo).resolve()
    local_ref = f"refs/heads/{branch}"
    result = None
    for attempt in range(PUSH_RETRIES + 1):
        before = _git("rev-parse", "--verify", "--quiet", local_ref, cwd=repo, check=False).stdout.strip()
        try:
            result = operation()
            break
        except PushRejectedError:
            if not push or attempt == PUSH_RETRIES:
                raise
            if before:
                _git("update-ref", local_ref, before, cwd=repo)
            else:
                _git("update-ref", "-d", local_ref, cwd=repo)
    return result


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
        ValueError: If a name is invalid or ``set_default`` is not deployed.
    """
    aliases = [a for a in (aliases or []) if a]
    site = Path(repo, site_dir).resolve() if not Path(site_dir).is_absolute() else Path(site_dir)
    if not site.is_dir():
        raise FileNotFoundError(f"Site directory not found: {site}. Did you run `quarto render`?")

    def operation() -> bool:
        return _deploy_once(version, aliases, site, branch, title, set_default, remote, push, repo, message)

    return _with_push_retry(operation, branch, remote, repo, push)


def _deploy_once(
    version: str,
    aliases: list[str],
    site: Path,
    branch: str,
    title: str | None,
    set_default: str | None,
    remote: str,
    push: bool,
    repo: str | Path,
    message: str | None,
) -> bool:
    """Run one deploy attempt (see ``deploy``)."""
    with docs_worktree(branch, remote=remote, repo=repo) as wt:
        versions = update_versions(read_versions(wt / VERSIONS_FILE), version, aliases, title)
        # validate every name before touching the filesystem
        validate_versions(versions, source=VERSIONS_FILE)
        if set_default:
            _require_deployed(set_default, versions, None, branch)
        entry = next(v for v in versions if v["version"] == version)
        # refresh every alias of this version, not only the ones passed now
        for name in [version, *entry["aliases"]]:
            _replace_dir(site, wt, name)
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
        ValueError: If ``version`` has not been deployed or an alias is invalid.
    """
    aliases = [a for a in aliases if a]
    if not aliases:
        raise ValueError("At least one alias is required")

    def operation() -> bool:
        return _alias_once(version, aliases, branch, remote, push, repo)

    return _with_push_retry(operation, branch, remote, repo, push)


def _alias_once(
    version: str, aliases: list[str], branch: str, remote: str, push: bool, repo: str | Path
) -> bool:
    """Run one alias attempt (see ``alias``)."""
    with docs_worktree(branch, remote=remote, repo=repo) as wt:
        existing = read_versions(wt / VERSIONS_FILE)
        if version not in {v["version"] for v in existing} or not (wt / version).is_dir():
            raise ValueError(f"Version '{version}' is not deployed on {branch}")
        versions = update_versions(existing, version, aliases)
        # validate every name before touching the filesystem
        validate_versions(versions, source=VERSIONS_FILE)
        for name in aliases:
            _replace_dir(_child_dir(wt, version), wt, name)
        write_versions(wt / VERSIONS_FILE, versions)
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
        ValueError: If ``target`` is not a version or alias listed in
            ``versions.json`` with a directory on the branch.
    """

    def operation() -> bool:
        return _set_default_once(target, branch, remote, push, repo)

    return _with_push_retry(operation, branch, remote, repo, push)


def _set_default_once(target: str, branch: str, remote: str, push: bool, repo: str | Path) -> bool:
    """Run one set-default attempt (see ``set_default_version``)."""
    with docs_worktree(branch, remote=remote, repo=repo) as wt:
        _require_deployed(target, read_versions(wt / VERSIONS_FILE), wt, branch)
        _write_default(wt, target)
        committed = _commit_and_push(wt, branch, f"docs: set default version to {target}", remote, push)
    return committed
