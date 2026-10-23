

<!-- README.md is generated from README.qmd; edit README.qmd and _usage.qmd, then run `quarto render README.qmd`. -->

# quarto-version-selector

A version dropdown for [Quarto](https://quarto.org/) websites.

Inspired by the [mike](https://github.com/jimporter/mike) plugin for mkdocs.

## How it works

    gh-pages/
    ├── index.html        # redirects to the default version (e.g. latest/)
    ├── versions.json     # [{"version": "1.2", "title": "1.2", "aliases": ["latest"]}, ...]
    ├── dev/              # built from the main branch
    ├── 1.2/              # built from release v1.2.x
    ├── 1.1/
    └── latest/           # copy of the newest release

The extension’s JavaScript reads `versions.json` from the parent of the current version directory and renders a dropdown. Choosing a version opens the same page in that version, or the version’s home page if the page doesn’t exist there. When `versions.json` is missing (e.g. `quarto preview`), no selector is shown.

## Install the extension

``` bash
quarto add CCBR/quarto-version-selector
```

Enable the filter in `_quarto.yml`:

``` yaml
filters:
  - version-selector

format:
  html: default     # or e.g. fnl-html
```

### Options

``` yaml
version-selector:
  versions-file: versions.json   # relative to the root of the docs branch
  placement: auto                # auto | navbar | navbar-right | fixed | none
```

- `auto` / `navbar`: the start of the left navbar menu (before the `navbar: left:` links). If the navbar has no left menu, it goes in the right-hand navbar tools; with no navbar at all, `auto` pins it to the top-right of the page.
- `navbar-right`: the start of the right-hand navbar tools (next to the GitHub icon, search, and dark-mode toggle).
- `fixed`: pinned to the top-right corner of the page.
- `none`: only shown in a `#version-selector` element (see below).

To place the selector somewhere specific, add an empty div with id `version-selector`:

``` markdown
::: {#version-selector}
:::
```

### Styling

The widget uses Bootstrap CSS variables, so it follows your `theme:` and dark mode.
Override these custom properties in your own CSS/SCSS:

| Property | Default |
|----|----|
| `--version-selector-fg` | `var(--bs-navbar-color)` |
| `--version-selector-fg-hover` | `var(--bs-navbar-hover-color)` |
| `--version-selector-bg` | `transparent` |
| `--version-selector-border` | `var(--bs-border-color)` |
| `--version-selector-menu-bg` | `var(--bs-dropdown-bg)`, else the page background (`Canvas`) |
| `--version-selector-menu-fg` | `var(--bs-dropdown-color)`, else the page text color (`CanvasText`) |
| `--version-selector-alias-bg` | `var(--bs-secondary-bg)` |
| `--version-selector-alias-fg` | `var(--bs-secondary-color)` |
| `--version-selector-font-size` | `0.875rem` |

``` css
.quarto-version-selector { --version-selector-border: transparent; }
```

## Deploy with GitHub Actions

Use the custom `deploy-version` action:

`.github/workflows/docs-quarto.yml`

``` yaml
name: quarto-publish-versioned
on:
  workflow_dispatch:
  release:
    types: [published]
  push:
    branches: [main]
concurrency: # one deploy at a time; the CLI also retries rejected pushes
  group: docs-deploy
  cancel-in-progress: false
permissions:
  contents: write # push to gh-pages
  pages: write # request a Pages build after the push
jobs:
  deploy-docs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 0 # tags and history are needed to determine the docs version
      - uses: quarto-dev/quarto-actions/setup@v2
      - uses: CCBR/quarto-version-selector/.github/actions/deploy-version@main
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
          # path: docs # if the Quarto project is in a subfolder
```

- **Release** of the newest version (e.g. `v1.2.0`) deploys `1.2/`, aliases it as `latest`, and points the root at `latest/`.
- **Release** of an older version deploys `1.1/` with no alias.
- **Push to main** deploys `dev/`.
- If the commit does not descend from the latest release (common with squash or rebase merges), the action warns and still deploys `dev/`. Set `require-descendant: true` to fail instead.

Configure GitHub Pages to [publish from the `gh-pages` branch](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site#publishing-from-a-branch). Pushes made with `GITHUB_TOKEN` don’t trigger a Pages build on their own, so the action requests one after deploying (this needs `pages: write`).

### Inputs

- `github-token`: GitHub Actions token. **Required.**
- `version-selector-version`: git ref of this repo to install. Default: `main`.
- `python-version`: Python version to install. Default: `3.14`.
- `docs-branch`: branch to deploy the docs to. Default: `gh-pages`.
- `github-actor`: username for the deploy commit. Default: `41898282+github-actions[bot]`.
- `strict-semver`: require strict semantic versioning in release tags. Default: `true`.
- `dry-run`: print the deploy command without deploying. Default: `false`.
- `path`: Quarto project directory, relative to the repo root (e.g. `docs`). Default: `.`.
- `site-dir`: rendered site directory relative to `path`; must match the project’s `output-dir`. Default: `_site`.
- `require-descendant`: fail instead of warn when the commit does not descend from the latest release. Default: `false`.

### Outputs

- `version`: the version deployed.
- `alias`: the alias deployed (empty if none).

## Migrating from mkdocs + mike

The docs branch layout and `versions.json` format match mike’s, so you can switch an existing mike site to Quarto without touching the versions mike already deployed. Their pages keep mike’s version selector, which also lists new Quarto versions. See the step-by-step guide: [Migrating from mkdocs + mike](mike.qmd).

## CLI

``` bash
pip install git+https://github.com/CCBR/quarto-version-selector.git
```

``` bash
quarto render
# compute version/alias for the current commit (uses `gh` to find the latest release)
quarto-version-selector get-version --release-tag v1.2.0
# deploy _site to gh-pages/1.2 and gh-pages/latest, update versions.json, push
quarto-version-selector deploy --version 1.2 --alias latest --set-default latest --push
# add an alias to an existing version
quarto-version-selector alias 1.2 stable --push
# change where the site root redirects
quarto-version-selector set-default latest --push
# check versions.json on the docs branch (or pass a file path)
quarto-version-selector validate
```

`versions.json` must match [versions.schema.json](https://github.com/CCBR/quarto-version-selector/blob/main/src/quarto_version_selector/versions.schema.json), and every version and alias name must be unique. `deploy`, `alias`, and `set-default` validate the existing file before changing the docs branch and validate the new file before writing it, so a malformed `versions.json` stops the deploy instead of being overwritten. Names must be single directory names (no `/`, `..`, or reserved root files such as `index.html`), and `set-default` targets must be listed in `versions.json`.

Redeploying a version also refreshes all of its aliases. Deploys without `--push` stay on your local docs branch; later commands build on them, and the CLI refuses to continue if the local and remote docs branches have diverged.

### Preview locally

`serve` previews the whole versioned site, including the version selector, without deploying:

``` bash
quarto render                                       # or: quarto render docs
quarto-version-selector serve --site-dir _site      # or: --site-dir docs/_site
```

It copies the docs branch into a temporary directory, adds your rendered site as `dev` (change it with `--version`), and serves it at http://localhost:8000/dev/. Your repository, branches, and worktrees are not changed, and the copy is deleted when you stop the server. Without `--site-dir`, it serves the docs branch as is, including deploys you haven’t pushed yet. Re-run it after `quarto render` to pick up changes.

The site has to be served over HTTP. Opening the files directly (`file://`) does not work: browsers block the `fetch()` of `versions.json`, so no selector appears, and links to version folders such as `../1.2/` show a directory listing instead of `index.html`.

Run `quarto-version-selector <command> --help` for all options. Deploys use a temporary git worktree, so your working tree is not touched.

## Development

With [Pixi](https://pixi.sh/latest/installation/):

``` bash
pixi run render            # quarto render the demo site
pixi run -e dev test       # ruff + pytest + JS tests
pixi run -e dev pre-commit # all pre-commit hooks
```

Or manually:

``` bash
pip install -e ".[dev]"
ruff check .
pytest          # CLI + extension render tests (extension tests need quarto)
npm install && npm test   # JS widget tests (node:test + jsdom)
quarto render
```

## Help & Contributing

Come across a **bug**? Open an [issue](https://github.com/CCBR/quarto-version-selector/issues)
and include a minimal reproducible example.

Have a **question**? Ask it in
[discussions](https://github.com/CCBR/quarto-version-selector/discussions).

Want to **contribute** to this project? Check out the
[contributing guidelines](.github/CONTRIBUTING.md).

**General Inquiries and Collaboration:** Please contact the CCBR Pipeliner team
at <CCBR_Pipeliner@mail.nih.gov>.
