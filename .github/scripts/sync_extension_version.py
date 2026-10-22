#!/usr/bin/env python3
"""
Copy the extension version from VERSION into the `version:` field of _extension.yml.

Quarto reads `_extension.yml` as static YAML, so the field cannot reference the
VERSION file directly. This script keeps the two in sync; it runs as a
pre-commit hook and the test suite checks that they match.

Example usage::

    python .github/scripts/sync_extension_version.py          # rewrite if needed
    python .github/scripts/sync_extension_version.py --check  # exit 1 if out of sync
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

EXT_DIR = Path(__file__).resolve().parents[2] / "_extensions" / "version-selector"
VERSION_LINE = re.compile(r"^version:.*$", re.MULTILINE)


def synced_extension_yml(ext_yml: str, version: str) -> str:
    """
    Return the _extension.yml text with its `version:` field set to ``version``.

    Args:
        ext_yml: Current contents of _extension.yml.
        version: Version string from the VERSION file.

    Returns:
        Updated _extension.yml contents.

    Raises:
        ValueError: If ``version`` is empty.
    """
    if not version:
        raise ValueError("The VERSION file is empty")
    line = f"version: {version}"
    if VERSION_LINE.search(ext_yml):
        updated = VERSION_LINE.sub(line, ext_yml, count=1)
    else:
        updated = re.sub(r"^(author:.*\n)", rf"\1{line}\n", ext_yml, count=1, flags=re.MULTILINE)
        if line not in updated:
            updated = f"{line}\n{ext_yml}"
    return updated


def main() -> None:
    """Sync (or check) the extension version; exits 1 when out of sync."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--check", action="store_true", help="Only check; do not modify files.")
    args = parser.parse_args()

    yml_path = EXT_DIR / "_extension.yml"
    version = (EXT_DIR / "VERSION").read_text().strip()
    current = yml_path.read_text()
    updated = synced_extension_yml(current, version)
    if updated != current:
        if args.check:
            raise SystemExit(f"{yml_path} version does not match VERSION ({version})")
        yml_path.write_text(updated)
        raise SystemExit(f"Updated {yml_path} to version {version}")


if __name__ == "__main__":
    main()
