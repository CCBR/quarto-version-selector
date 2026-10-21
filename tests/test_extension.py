"""Tests for the Quarto extension in _extensions/version-selector (renders with Quarto)."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXT_DIR = ROOT / "_extensions" / "version-selector"
VERSION = (ROOT / "src" / "quarto_version_selector" / "VERSION").read_text().strip()

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


def test_extension_version_matches_version_file():
    """The extension can't read src/ when installed, so its versions must be kept in sync."""
    ext_yml = (EXT_DIR / "_extension.yml").read_text()
    lua = (EXT_DIR / "version-selector.lua").read_text()
    assert re.search(r"^version:\s*(\S+)", ext_yml, re.MULTILINE).group(1) == VERSION
    assert re.search(r'version = "([^"]+)"', lua).group(1) == VERSION


def test_package_version_matches_version_file():
    from quarto_version_selector import __version__

    assert __version__ == VERSION


def test_css_exposes_documented_custom_properties():
    css = (EXT_DIR / "version-selector.css").read_text()
    readme = (EXT_DIR.parents[1] / "README.md").read_text()
    props = set(re.findall(r"(--version-selector-[a-z-]+):", css))
    assert props
    for prop in props:
        assert f"`{prop}`" in readme, f"{prop} not documented in README"
    assert "var(--bs-" in css


@requires_quarto
def test_website_defaults(tmp_path):
    proj = render(
        tmp_path,
        "project:\n  type: website\nwebsite:\n  title: t\n  navbar:\n    left: [index.qmd]\n"
        "filters:\n  - version-selector\nformat: html\n",
    )
    html = (proj / "_site" / "index.html").read_text()
    assert meta(html, "version-selector:versions-file") == "versions.json"
    assert meta(html, "version-selector:placement") == "auto"
    assert f"quarto-contrib/version-selector-{VERSION}/version-selector.js" in html
    assert f"quarto-contrib/version-selector-{VERSION}/version-selector.css" in html
    libdir = proj / "_site" / "site_libs" / "quarto-contrib" / f"version-selector-{VERSION}"
    assert (libdir / "version-selector.js").is_file()
    assert (libdir / "version-selector.css").is_file()
    # script loads after the body content, once the navbar exists
    assert html.index("version-selector.js") > html.index('id="quarto-header"')


@requires_quarto
def test_options_are_passed_through(tmp_path):
    proj = render(
        tmp_path,
        "project:\n  type: website\nwebsite:\n  title: t\nfilters:\n  - version-selector\n"
        "version-selector:\n  versions-file: meta/v.json\n  placement: fixed\nformat: html\n",
    )
    html = (proj / "_site" / "index.html").read_text()
    assert meta(html, "version-selector:versions-file") == "meta/v.json"
    assert meta(html, "version-selector:placement") == "fixed"


@requires_quarto
def test_non_html_format_is_untouched(tmp_path):
    proj = render(tmp_path, "project:\n  type: default\nfilters:\n  - version-selector\nformat: gfm\n")
    md = (proj / "index.md").read_text()
    assert "version-selector" not in md
