"""Tests for the Quarto extension in _extensions/version-selector (renders with Quarto)."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXT_DIR = ROOT / "_extensions" / "version-selector"
VERSION = (EXT_DIR / "VERSION").read_text().strip()

requires_quarto = pytest.mark.skipif(shutil.which("quarto") is None, reason="quarto not installed")


def render(tmp_path: Path, quarto_yml: str, filename: str = "index.qmd", body: str = "# Hi\n") -> Path:
    """Render a single-page project using the extension; return the project dir."""
    shutil.copytree(EXT_DIR, tmp_path / "_extensions" / "version-selector")
    (tmp_path / "_quarto.yml").write_text(quarto_yml)
    (tmp_path / filename).write_text(f"---\ntitle: Test\n---\n\n{body}")
    subprocess.run(["quarto", "render"], cwd=tmp_path, check=True, capture_output=True, text=True)
    return tmp_path


def meta(html: str, name: str) -> str | None:
    """Return the content of <meta name=...>, or None."""
    match = re.search(rf'<meta name="{re.escape(name)}" content="([^"]*)">', html)
    return match.group(1) if match else None


def test_extension_metadata():
    text = (EXT_DIR / "_extension.yml").read_text()
    assert "quarto-required" in text
    assert "version-selector.lua" in text
    for name in ["version-selector.lua", "version-selector.js", "version-selector.css"]:
        assert (EXT_DIR / name).is_file()


@requires_quarto
def test_website_defaults(tmp_path):
    proj = render(
        tmp_path,
        "project:\n  type: website\nwebsite:\n  title: t\n  navbar:\n    left: [index.qmd]\n"
        "filters:\n  - version-selector\nformat: html\n",
    )
    html = (proj / "_site" / "index.html").read_text()
    assert meta(html, "version-selector:versions-file") == "versions.json"
    assert meta(html, "version-selector:placement") == "navbar-left"
    assert f"quarto-contrib/version-selector-{VERSION}/version-selector.js" in html
    assert f"quarto-contrib/version-selector-{VERSION}/version-selector.css" in html
    libdir = proj / "_site" / "site_libs" / "quarto-contrib" / f"version-selector-{VERSION}"
    assert (libdir / "version-selector.js").is_file()
    assert (libdir / "version-selector.css").is_file()
    # script loads after the body content, once the navbar exists
    assert html.index("version-selector.js") > html.index('id="quarto-header"')


@requires_quarto
def test_dev_version_is_used_for_the_dependency(tmp_path):
    shutil.copytree(EXT_DIR, tmp_path / "_extensions" / "version-selector")
    (tmp_path / "_extensions" / "version-selector" / "VERSION").write_text("0.2.0-dev\n")
    (tmp_path / "_quarto.yml").write_text(
        "project:\n  type: website\nwebsite:\n  title: t\nfilters:\n  - version-selector\n"
    )
    (tmp_path / "index.qmd").write_text("---\ntitle: Test\n---\n\nhi\n")
    subprocess.run(["quarto", "render"], cwd=tmp_path, check=True, capture_output=True, text=True)
    html = (tmp_path / "_site" / "index.html").read_text()
    assert "quarto-contrib/version-selector-0.2.0-dev/version-selector.js" in html


@requires_quarto
def test_options_are_passed_through(tmp_path):
    proj = render(
        tmp_path,
        "project:\n  type: website\nwebsite:\n  title: t\nfilters:\n  - version-selector\n"
        "version-selector:\n  versions-file: meta/v.json\n  placement: fixed-right\nformat: html\n",
    )
    html = (proj / "_site" / "index.html").read_text()
    assert meta(html, "version-selector:versions-file") == "meta/v.json"
    assert meta(html, "version-selector:placement") == "fixed-right"
    assert meta(html, "version-selector:label") == ""


@requires_quarto
def test_label_option_is_passed_through(tmp_path):
    proj = render(
        tmp_path,
        "project:\n  type: website\nwebsite:\n  title: t\nfilters:\n  - version-selector\n"
        'version-selector:\n  label: "Version"\nformat: html\n',
    )
    html = (proj / "_site" / "index.html").read_text()
    assert meta(html, "version-selector:label") == "Version"


@requires_quarto
def test_sidebar_placement_is_accepted(tmp_path):
    proj = render(
        tmp_path,
        "project:\n  type: website\nwebsite:\n  title: t\nfilters:\n  - version-selector\n"
        "version-selector:\n  placement: sidebar\nformat: html\n",
    )
    html = (proj / "_site" / "index.html").read_text()
    assert meta(html, "version-selector:placement") == "sidebar"


@requires_quarto
def test_unknown_placement_falls_back_to_navbar_left(tmp_path):
    proj = render(
        tmp_path,
        "project:\n  type: website\nwebsite:\n  title: t\nfilters:\n  - version-selector\n"
        "version-selector:\n  placement: auto\nformat: html\n",
    )
    html = (proj / "_site" / "index.html").read_text()
    assert meta(html, "version-selector:placement") == "navbar-left"


@requires_quarto
def test_non_html_format_is_untouched(tmp_path):
    proj = render(tmp_path, "project:\n  type: default\nfilters:\n  - version-selector\nformat: gfm\n")
    md = (proj / "index.md").read_text()
    assert "version-selector" not in md


def test_sync_extension_version():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "sync", ROOT / ".github" / "scripts" / "sync_extension_version.py"
    )
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)
    assert (
        sync.synced_extension_yml("title: X\nauthor: A\n", "1.2.3") == "title: X\nauthor: A\nversion: 1.2.3\n"
    )
    assert sync.synced_extension_yml("title: X\nversion: 0.1.0\n", "1.2.3") == "title: X\nversion: 1.2.3\n"
    with pytest.raises(ValueError, match="empty"):
        sync.synced_extension_yml("title: X\n", "")
