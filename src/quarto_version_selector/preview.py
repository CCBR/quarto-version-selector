"""
Preview a versioned site locally, including the version selector.

The docs branch is exported (``git archive``) into a temporary directory, so
no branch, worktree, or file in the repository is changed. A locally rendered
site can be overlaid as one version (``dev`` by default), and the copy is
served over HTTP: the selector loads ``versions.json`` with ``fetch()``,
which browsers block for ``file://`` pages.

Example usage::

    quarto render docs
    quarto-version-selector serve --site-dir docs/_site
"""

from __future__ import annotations

import contextlib
import functools
import io
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Iterator
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .deploy import VERSIONS_FILE, _git, _ref_exists, _replace_dir, _write_default
from .versions import is_ancestor, read_versions, update_versions, validate_versions, write_versions


def resolve_docs_ref(branch: str = "gh-pages", remote: str = "origin", repo: str | Path = ".") -> str | None:
    """
    Return the newest ref of the docs branch to preview.

    The remote branch is fetched first (failures are ignored, e.g. offline).
    When both the local and remote branches exist, the one that contains the
    other is used, so unpushed local deploys are included.

    Args:
        branch: Docs branch name.
        remote: Git remote.
        repo: Source repository.

    Returns:
        A git ref, or None if the docs branch does not exist yet.

    Raises:
        RuntimeError: If the local and remote docs branches have diverged.
    """
    _git("fetch", remote, f"+refs/heads/{branch}:refs/remotes/{remote}/{branch}", cwd=repo, check=False)
    local = f"refs/heads/{branch}"
    remote_ref = f"refs/remotes/{remote}/{branch}"
    has_local = _ref_exists(local, cwd=repo)
    has_remote = _ref_exists(remote_ref, cwd=repo)
    if has_local and has_remote:
        if is_ancestor(remote_ref, local, cwd=repo):
            ref = local
        elif is_ancestor(local, remote_ref, cwd=repo):
            ref = remote_ref
        else:
            raise RuntimeError(
                f"The local {branch} branch has diverged from {remote}/{branch}; "
                f"reconcile them or pass --ref to choose one"
            )
    elif has_local:
        ref = local
    elif has_remote:
        ref = remote_ref
    else:
        ref = None
    return ref


def _export_ref(ref: str, dest: Path, repo: str | Path) -> None:
    """Extract the tree of ``ref`` into ``dest`` using ``git archive``."""
    archive = subprocess.run(
        ["git", "archive", "--format=tar", ref], cwd=repo, capture_output=True, check=False
    )
    if archive.returncode != 0:
        raise RuntimeError(f"Could not export {ref}: {archive.stderr.decode().strip()}")
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        if hasattr(tarfile, "data_filter"):
            tar.extractall(dest, filter="data")
        else:  # Python < 3.12 without the backported filter
            tar.extractall(dest)


@contextlib.contextmanager
def preview_site(
    site_dir: str | Path | None = None,
    version: str = "dev",
    aliases: list[str] | None = None,
    branch: str = "gh-pages",
    remote: str = "origin",
    ref: str | None = None,
    repo: str | Path = ".",
) -> Iterator[Path]:
    """
    Build a temporary copy of the versioned site for previewing.

    Args:
        site_dir: Rendered site to show as ``version``; None previews the docs branch as is.
        version: Version name for ``site_dir``.
        aliases: Aliases for ``version``.
        branch: Docs branch.
        remote: Git remote.
        ref: Git ref to preview instead of the newest docs branch.
        repo: Source repository.

    Yields:
        The root directory of the preview.

    Raises:
        FileNotFoundError: If ``site_dir`` does not exist, or there is nothing to preview.
        RuntimeError: If the docs branch cannot be exported or has diverged.
        ValueError: If a version name is invalid or versions.json is malformed.
    """
    repo = Path(repo).resolve()
    site = None
    if site_dir is not None:
        site = Path(site_dir) if Path(site_dir).is_absolute() else repo / site_dir
        if not site.is_dir():
            raise FileNotFoundError(f"Site directory not found: {site}. Did you run `quarto render`?")
    ref = ref or resolve_docs_ref(branch, remote, repo)
    if ref is None and site is None:
        raise FileNotFoundError(f"No {branch} branch found and no --site-dir given; nothing to preview")

    tmp = Path(tempfile.mkdtemp(prefix="qvs-preview-"))
    root = tmp / "site"
    root.mkdir()
    try:
        if ref is not None:
            _export_ref(ref, root, repo)
        if site is not None:
            versions_path = root / VERSIONS_FILE
            versions = read_versions(versions_path) if versions_path.is_file() else []
            versions = update_versions(versions, version, aliases or [])
            validate_versions(versions, source=VERSIONS_FILE)
            entry = next(v for v in versions if v["version"] == version)
            for name in [version, *entry["aliases"]]:
                _replace_dir(site, root, name)
            write_versions(versions_path, versions)
            if not (root / "index.html").exists():
                _write_default(root, version)
        yield root
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class _QuietHandler(SimpleHTTPRequestHandler):
    """Static file handler that only logs errors."""

    def log_message(self, format: str, *args: object) -> None:
        """Suppress per-request logging."""

    def log_error(self, format: str, *args: object) -> None:
        """Log errors (e.g. 404s) to stderr."""
        super().log_message(format, *args)


def make_server(directory: str | Path, host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    """
    Create an HTTP server for ``directory``; call ``serve_forever()`` to run it.

    Args:
        directory: Directory to serve.
        host: Interface to bind; the default only accepts local connections.
        port: Port to bind; 0 picks a free port.

    Raises:
        OSError: If the port is unavailable.
    """
    handler = functools.partial(_QuietHandler, directory=str(directory))
    return ThreadingHTTPServer((host, port), handler)
