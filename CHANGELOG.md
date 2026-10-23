## quarto-version-selector development version

This is the first release of quarto-version-selector 🎉

- Quarto extension `version-selector` adds a version dropdown to any Quarto HTML format, driven by a root `versions.json`. (#2, @copilot, @kelly-sovacool)
- `quarto-version-selector` CLI with `get-version`, `deploy`, `alias`, `set-default`, and `validate` commands to deploy each version into its own subfolder of the docs branch. `versions.json` is validated against a JSON schema on every read and write.
- Composite GitHub Action `deploy-version` that renders the site and deploys release builds as `major.minor` (aliased `latest` for the newest release) and main-branch builds as `dev`.
- `deploy-version` action gains `path` and `site-dir` inputs to render and deploy Quarto projects in a subfolder (e.g. `docs/`). (#6, @kelly-sovacool)
- `get-version` no longer fails when the commit does not descend from the latest release (e.g. after squash or rebase merges); it warns and deploys `dev`. Use `--require-descendant` (or the action's `require-descendant` input) for the strict behavior. (#6, @kelly-sovacool)
- Missing release tags now produce a readable error suggesting `git fetch --tags` instead of a traceback. (#6, @kelly-sovacool)
- `_extension.yml` now includes a `version` field, kept in sync with the `VERSION` file by a pre-commit hook. (#6, @kelly-sovacool)
- New `serve` command previews the versioned site locally, with a working version selector, by serving a temporary copy of the docs branch with your rendered site added as `dev`. (#9, @kelly-sovacool)
- The selector now defaults to the start of the left navbar menu; use `placement: navbar-right` for the previous position next to the navbar tools. (#8, @kelly-sovacool)
- New guide for switching an existing mkdocs + mike site to Quarto while keeping the versions mike already deployed. (#10, @kelly-sovacool)
- `placement` options are now `navbar-left` (default), `navbar-right`, `fixed-left`, `fixed-right`, and `none`; `auto`, `navbar`, and `fixed` are removed. Unknown values warn and fall back to `navbar-left`. (#11, @kelly-sovacool)
