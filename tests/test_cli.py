from __future__ import annotations

import json
from pathlib import Path

from test_workbench import _snapshot

from optimatrix.cli import main


def test_workbench_command_exports_the_read_only_product(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")
    output = tmp_path / "workbench"
    assert (
        main(
            [
                "workbench",
                "--snapshot",
                str(snapshot_path),
                "--output-dir",
                str(output),
            ]
        )
        == 0
    )
    assert (output / "index.html").is_file()
    assert "PUBLIC SHADOW - READ ONLY" in (output / "index.html").read_text(encoding="utf-8")
