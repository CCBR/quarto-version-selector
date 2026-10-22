"""
Command line interface for quarto-version-selector.

Example usage::

    quarto render
    quarto-version-selector get-version --release-tag v1.2.0
    quarto-version-selector deploy --version 1.2 --alias latest --push
    quarto-version-selector alias 1.2 stable --push
    quarto-version-selector set-default latest --push
"""

from __future__ import annotations

import os
import warnings
from pathlib import Path

import click

from . import __version__
from .deploy import VERSIONS_FILE, docs_worktree, set_default_version
from .deploy import alias as alias_version
from .deploy import deploy as deploy_version
from .versions import get_version_and_alias, read_versions

_branch = click.option("--branch", default="gh-pages", show_default=True, help="Docs branch.")
_remote = click.option("--remote", default="origin", show_default=True, help="Git remote.")
_push = click.option("--push/--no-push", default=False, show_default=True, help="Push the docs branch.")


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__)
def cli() -> None:
    """Deploy versioned Quarto websites."""


@cli.command("get-version")
@click.option("--release-tag", default=None, help="Tag of the release being built (release events).")
@click.option("--latest-release-tag", default=None, help="Latest release tag; queried with `gh` if omitted.")
@click.option("--repo", default=None, help="GitHub repo (owner/name) for the `gh` lookup.")
@click.option("--strict-semver/--no-strict-semver", default=True, show_default=True)
@click.option(
    "--require-descendant/--no-require-descendant",
    default=False,
    show_default=True,
    help="Fail (instead of warn) if HEAD does not descend from the latest release.",
)
@click.option("--github-output", is_flag=True, help="Also write version/alias to $GITHUB_OUTPUT.")
def get_version(
    release_tag: str | None,
    latest_release_tag: str | None,
    repo: str | None,
    strict_semver: bool,
    require_descendant: bool,
    github_output: bool,
) -> None:
    """Print the docs VERSION and ALIAS for the current commit."""
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            version, alias = get_version_and_alias(
                release_tag=release_tag or None,
                latest_release_tag=latest_release_tag or None,
                strict_semver=strict_semver,
                repo=repo,
                require_descendant=require_descendant,
            )
    except (ValueError, RuntimeError) as err:
        raise click.ClickException(str(err)) from err
    for warning in caught:
        click.echo(f"Warning: {warning.message}", err=True)
    click.echo(f"version={version}")
    click.echo(f"alias={alias}")
    if github_output:
        path = os.environ.get("GITHUB_OUTPUT")
        if not path:
            raise click.ClickException("--github-output given but GITHUB_OUTPUT is not set")
        with open(path, "a") as fh:
            fh.write(f"version={version}\nalias={alias}\n")


@cli.command()
@click.option("--version", "version", required=True, help="Version directory, e.g. 1.2 or dev.")
@click.option("--alias", "aliases", multiple=True, help="Alias for this version (repeatable).")
@click.option("--title", default=None, help="Display title in the selector.")
@click.option("--site-dir", default="_site", show_default=True, help="Rendered site directory.")
@click.option("--set-default", default=None, help="Version/alias the root index.html redirects to.")
@click.option("--message", "-m", default=None, help="Commit message.")
@_branch
@_remote
@_push
@click.option("--dry-run", is_flag=True, help="Print what would be deployed without deploying.")
def deploy(
    version: str,
    aliases: tuple[str, ...],
    title: str | None,
    site_dir: str,
    set_default: str | None,
    message: str | None,
    branch: str,
    remote: str,
    push: bool,
    dry_run: bool,
) -> None:
    """Deploy SITE_DIR to <branch>/<version>/ and update versions.json."""
    aliases_list = [a for a in aliases if a]
    if dry_run:
        click.echo(
            f"Dry run: would deploy {site_dir} as '{version}' aliases={aliases_list} "
            f"to {remote}/{branch} (push={push})"
        )
        return
    committed = deploy_version(
        version,
        aliases_list,
        site_dir=site_dir,
        branch=branch,
        title=title,
        set_default=set_default,
        remote=remote,
        push=push,
        message=message,
    )
    click.echo(f"Deployed '{version}' to {branch}" + ("" if committed else " (no changes)"))


@cli.command()
@click.argument("version")
@click.argument("aliases", nargs=-1, required=True)
@_branch
@_remote
@_push
def alias(version: str, aliases: tuple[str, ...], branch: str, remote: str, push: bool) -> None:
    """Point ALIASES at an already deployed VERSION."""
    alias_version(version, list(aliases), branch=branch, remote=remote, push=push)
    click.echo(f"Aliased {version} as {', '.join(aliases)}")


@cli.command("set-default")
@click.argument("target")
@_branch
@_remote
@_push
def set_default(target: str, branch: str, remote: str, push: bool) -> None:
    """Redirect the site root to TARGET (a version or alias)."""
    set_default_version(target, branch=branch, remote=remote, push=push)
    click.echo(f"Default version set to {target}")


@cli.command()
@click.argument("path", required=False, type=click.Path(dir_okay=False))
@_branch
@_remote
def validate(path: str | None, branch: str, remote: str) -> None:
    """
    Validate versions.json against the schema.

    Validates PATH if given, otherwise versions.json on the docs branch.
    """
    try:
        if path:
            if not Path(path).is_file():
                raise click.ClickException(f"{path} does not exist")
            versions = read_versions(path)
            source = path
        else:
            with docs_worktree(branch, remote=remote) as wt:
                if not (wt / VERSIONS_FILE).is_file():
                    raise click.ClickException(f"{VERSIONS_FILE} not found on {branch}")
                versions = read_versions(wt / VERSIONS_FILE)
            source = f"{branch}:{VERSIONS_FILE}"
    except ValueError as err:
        raise click.ClickException(str(err)) from err
    click.echo(f"{source} is valid ({len(versions)} versions)")


def main() -> None:
    """Entry point for the console script."""
    cli()


if __name__ == "__main__":
    main()
