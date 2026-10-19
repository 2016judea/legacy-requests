"""The paid open-asks set must never be a static URL.

2026-10-19: with outputDirectory "." /api/%5Ffull/rows.json.gz served the 1.5 MB paid set (200).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import deploy  # noqa: E402


def test_only_public_is_static_and_the_bundle_is_outside_it():
    assert json.loads((ROOT / "site/vercel.json").read_text())["outputDirectory"] == "public"
    assert '"outputDirectory": "public"' in (ROOT / "scripts/deploy.py").read_text()
    names = [name for _, name in deploy.collect()]
    full = [n for n in names if "_full" in n]
    assert full and all(n.startswith("api/_full/") for n in full), full
    assert "public/index.html" in names and "public/asks/index.html" in names
    assert "asks/meta.json" in names  # checkout.js requires it from outside public/
    assert not any(n.startswith("public/api") for n in names)
