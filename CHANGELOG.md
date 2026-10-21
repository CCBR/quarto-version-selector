## quarto-version-selector development version

This is the first release of quarto-version-selector 🎉

- Quarto extension `version-selector` adds a version dropdown to any Quarto HTML format, driven by a root `versions.json`. (#2, @copilot, @kelly-sovacool)
- `quarto-version-selector` CLI with `get-version`, `deploy`, `alias`, `set-default`, and `validate` commands to deploy each version into its own subfolder of the docs branch. `versions.json` is validated against a JSON schema on every read and write.
- Composite GitHub Action `deploy-version` that renders the site and deploys release builds as `major.minor` (aliased `latest` for the newest release) and main-branch builds as `dev`.
