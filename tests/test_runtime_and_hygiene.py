from __future__ import annotations

import json
from pathlib import Path

import pytest
from radar_runtime.cli import main
from radar_runtime.fixture import build_fixture_result

ROOT = Path(__file__).resolve().parents[1]


def test_fixture_and_replay_are_deterministic(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = build_fixture_result(tmp_path / "first")
    second = build_fixture_result(tmp_path / "second")
    assert first == second
    assert first["receipt_type"] == "RADAR_REFERENCE_FIXTURE"

    assert main(["inspect", str(tmp_path / "first" / "capture")]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["capture_order"] == "VERIFIED"

    assert (
        main(
            [
                "replay",
                str(tmp_path / "first" / "capture"),
                "--output",
                str(tmp_path / "replay"),
            ]
        )
        == 0
    )
    replay = json.loads(capsys.readouterr().out)
    assert replay["decision_digest"] == first["decision_digest"]
    assert replay["frame_digest"] == first["frame_digest"]


def test_active_python_tree_has_no_removed_short_vol_compatibility_objects() -> None:
    forbidden_identifiers = (
        "ShortVol" + "Playbook",
        "Research" + "SeedDefinition",
        "Qualified" + "ChampionReceipt",
        "Evolution" + "Job",
        "Shadow" + "Canary",
    )
    for root in (ROOT / "apps", ROOT / "packages"):
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for identifier in forbidden_identifiers:
                assert identifier not in text, f"{identifier} leaked into {path}"


def test_repository_has_only_current_runtime_packages() -> None:
    expected_packages = {
        "market_tape",
        "options_domain",
        "short_vol_radar",
        "shadow_engine",
    }
    actual_packages = {item.name for item in (ROOT / "packages").iterdir() if item.is_dir()}
    assert actual_packages == expected_packages
    assert {item.name for item in (ROOT / "apps").iterdir() if item.is_dir()} == {"radar_runtime"}
