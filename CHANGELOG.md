## quarto-version-selector 1.0.0

This is the first release of quarto-version-selector 🎉

- Quarto extension `version-selector` adds a version dropdown to any Quarto HTML format, driven by a root `versions.json`. (#2, #6, @copilot, @kelly-sovacool)
  - `placement` options: `navbar-left` (default), `navbar-right`, `sidebar` (falls back to `navbar-left` on pages without a docked sidebar), `fixed-left`, `fixed-right`, and `none`. Unknown values warn and fall back to `navbar-left`. (#8, #11, #12, @kelly-sovacool)
- `quarto-version-selector` CLI deploys each version into its own subfolder of the docs branch. (#2, #6, #9, @copilot, @kelly-sovacool)
  - Commands: `get-version`, `deploy`, `alias`, `set-default`, `validate`, and `serve`. `serve` previews the versioned site locally with your rendered site added as `dev`.
  - `versions.json` is checked against a JSON schema every time it is read or written.
  - If the commit doesn't descend from the latest release (e.g. after a squash or rebase merge), `get-version` warns and deploys `dev`. Use `--require-descendant` to make it fail instead. If release tags are missing, it gives an error suggesting `git fetch --tags`.
- Composite GitHub Action `deploy-version` renders and deploys the site. Release builds go out as `major.minor`, with `latest` pointing to the newest release, and main-branch builds go out as `dev`. It supports `path`/`site-dir` inputs for projects in a subfolder, and a `require-descendant` input. (#2, #6, @kelly-sovacool)
- Guide for switching an existing mkdocs + mike site to Quarto while keeping the versions mike already deployed. (#10, @kelly-sovacool)
