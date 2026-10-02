"""Guards for the GitHub Pages build (``scripts/build_site.py``)."""

import ast
import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def build_site():
    spec = importlib.util.spec_from_file_location(
        "build_site", ROOT / "scripts" / "build_site.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def local_modules() -> set[str]:
    """Top-level project modules, derived from the files on disk."""
    return {p.stem for p in ROOT.glob("*.py")}


def test_every_local_import_ships_to_the_browser(build_site):
    """If app.py imports a new local module, the site must include it."""
    shipped = {Path(f).stem for f in build_site.APP_FILES}
    needed = set()
    for name in build_site.APP_FILES:
        tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                needed |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                needed.add(node.module.split(".")[0])
    assert (needed & local_modules()) <= shipped


def test_entrypoint_is_first(build_site):
    assert build_site.APP_FILES[0] == "app.py"


def test_build_output(build_site, tmp_path):
    out = build_site.build(tmp_path / "site")
    assert (out / ".nojekyll").exists()
    for name in build_site.APP_FILES:
        assert (out / "app" / name).read_bytes() == (
            ROOT / name
        ).read_bytes()
    html = (out / "index.html").read_text(encoding="utf-8")
    assert build_site.PLACEHOLDER not in html
    assert json.dumps(build_site.APP_FILES) in html


def test_stlite_version_is_pinned_and_consistent():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    versions = set(re.findall(r"@stlite/browser@([0-9.]+)/", html))
    assert len(versions) == 1, "pin one exact stlite version everywhere"


def test_browser_requirements_match_requirements_txt():
    """index.html lists runtime deps (minus streamlit) for the browser."""
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    match = re.search(r"requirements:\s*\[(.*?)\]", html)
    browser = {s.strip(" \"'") for s in match.group(1).split(",")}
    runtime = {
        re.split(r"[<>=!~\[ ]", line.strip())[0].lower()
        for line in (ROOT / "requirements.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert browser == runtime - {"streamlit"}
