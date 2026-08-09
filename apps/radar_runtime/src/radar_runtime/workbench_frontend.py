from __future__ import annotations

from pathlib import Path

_ASSET_ROOT = Path(__file__).with_name("workbench_static")


def _read_asset(name: str) -> str:
    path = _ASSET_ROOT / name
    value = path.read_text(encoding="utf-8")
    if not value:
        raise RuntimeError(f"Workbench frontend asset is empty: {name}")
    return value


HTML = _read_asset("index.html")
CSS = _read_asset("styles.css")
JS = _read_asset("app.js")
