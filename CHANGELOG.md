## quarto-version-selector development version

- Initial release:
  - Quarto extension `version-selector` that adds a version dropdown to any Quarto HTML format, driven by a root `versions.json`.
  - `quarto-version-selector` CLI with `get-version`, `deploy`, `alias`, and `set-default` commands to deploy each version into its own subfolder of the docs branch.
  - Composite GitHub Action `deploy-version` that renders the site and deploys release builds as `major.minor` (aliased `latest` for the newest release) and main-branch builds as `dev`.
  (#TBD, @kelly-sovacool)
