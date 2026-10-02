"""Assemble the static GitHub Pages site into ``_site/``.

The deployed app is the *same* source that runs locally: the Python modules
are copied verbatim next to ``index.html`` and executed in the browser by
stlite (Streamlit compiled to WebAssembly). Nothing is duplicated or forked.

Usage::

    python scripts/build_site.py            # writes ./_site
    python -m http.server -d _site 8000     # preview at localhost:8000
"""

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "_site"
TEMPLATE = ROOT / "web" / "index.html"

#: Python modules shipped to the browser. The first entry is the entrypoint.
APP_FILES = ["app.py", "core_logic.py", "schemas.py", "storage.py"]
PLACEHOLDER = "__APP_FILES__"


def build(out: Path = OUT) -> Path:
    """Build the site into ``out`` (replacing it) and return the path."""
    if out.exists():
        shutil.rmtree(out)
    (out / "app").mkdir(parents=True)

    for name in APP_FILES:
        shutil.copy2(ROOT / name, out / "app" / name)

    html = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in html:
        raise RuntimeError(f"{TEMPLATE} is missing {PLACEHOLDER}")
    (out / "index.html").write_text(
        html.replace(PLACEHOLDER, json.dumps(APP_FILES)), encoding="utf-8"
    )
    # Tell GitHub Pages to serve files as-is (no Jekyll processing).
    (out / ".nojekyll").touch()
    return out


if __name__ == "__main__":
    target = build()
    print(f"Built {target.relative_to(ROOT)}/ ({len(APP_FILES)} modules)")
    sys.exit(0)
