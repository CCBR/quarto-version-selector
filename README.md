

<!-- README.md is generated from README.qmd; edit README.qmd and _quickstart.qmd, then run `pixi run render README.qmd`. -->

# quarto-version-selector

A version dropdown for [Quarto](https://quarto.org/) websites.

Inspired by the [mike](https://github.com/jimporter/mike) plugin for mkdocs.

## Getting started

### Install the extension

``` bash
quarto add CCBR/quarto-version-selector
```

Enable the filter in `_quarto.yml`:

``` yaml
filters:
  - version-selector
```

### Choose a placement

``` yaml
version-selector:
  placement: navbar-left   # navbar-left | navbar-right | fixed-left | fixed-right | sidebar | none
```

- `navbar-left` (default): the start of the left navbar menu. Falls back to the right-hand navbar tools, or the top-left of the page if there is no navbar.

- `navbar-right`: the start of the right-hand navbar tools (next to the GitHub icon, search, and dark-mode toggle). Falls back to the top-right of the page if there is no navbar.

- `fixed-left` / `fixed-right`: pinned to the top-left or top-right corner of the page.

- `sidebar`: the top of the docked sidebar. Falls back to `navbar-left` if the page has no sidebar.

- `none`: only shown in an element you place yourself:

  ``` markdown
  ::: {#version-selector}
  :::
  ```

### Deploy with GitHub Actions

`.github/workflows/docs-quarto.yml`

``` yaml
name: quarto-publish-versioned
on:
  workflow_dispatch:
  release:
    types: [published]
  push:
    branches: [main]
concurrency:
  group: docs-deploy
  cancel-in-progress: false
permissions:
  contents: write
  pages: write
jobs:
  deploy-docs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0
      - uses: quarto-dev/quarto-actions/setup@v2
      - uses: CCBR/quarto-version-selector/.github/actions/deploy-version@main
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
```

Then configure GitHub Pages to [publish from the `gh-pages` branch](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site#publishing-from-a-branch).

See the [documentation website](https://ccbr.github.io/quarto-version-selector/usage)
for advanced usage information such as custom styling, all extension and action options, the CLI for local previews,
and [migrating from mike](https://ccbr.github.io/quarto-version-selector/mike).

## Help & Contributing

Come across a **bug**? Open an [issue](https://github.com/CCBR/quarto-version-selector/issues)
and include a minimal reproducible example.

Have a **question**? Ask it in
[discussions](https://github.com/CCBR/quarto-version-selector/discussions).

Want to **contribute** to this project? Check out the
[contributing guidelines](.github/CONTRIBUTING.md).

**General Inquiries and Collaboration:** Please contact the CCBR Pipeliner team
at <CCBR_Pipeliner@mail.nih.gov>.
