from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from test_workbench import _snapshot

import optimatrix.cli as cli
from optimatrix.policy import DEFAULT_BTC_SHORT_VOL_POLICY_PATH


def _runtime_command(
    root: Path,
    *,
    event_state: str = "NONE",
    workbench_port: int = 8765,
    policy_path: Path = DEFAULT_BTC_SHORT_VOL_POLICY_PATH,
) -> list[str]:
    return [
        "runtime",
        "--policy",
        str(policy_path),
        "--event-state",
        event_state,
        "--root",
        str(root),
        "--workbench-port",
        str(workbench_port),
    ]


def _forbid_runtime_source(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    constructions: list[dict[str, object]] = []

    def forbidden_source(**kwargs: object) -> None:
        constructions.append(kwargs)
        raise AssertionError("runtime source must not be constructed")

    monkeypatch.setattr(cli, "DeribitPublicRuntimeSource", forbidden_source)
    return constructions


def test_workbench_command_exports_the_read_only_product(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")
    output = tmp_path / "workbench"
    assert (
        cli.main(
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


def test_runtime_rejects_resolved_equivalent_foreign_root_before_source_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorized_root = tmp_path / "authorized"
    monkeypatch.setattr(cli, "AUTHORIZED_RUNTIME_ROOT", authorized_root)
    constructions = _forbid_runtime_source(monkeypatch)
    foreign_spelling = tmp_path / "unused" / ".." / authorized_root.name

    assert cli.main(_runtime_command(foreign_spelling)) == 2

    assert constructions == []
    assert "runtime root is outside" in json.loads(capsys.readouterr().out)["error"]


@pytest.mark.parametrize("symlink_parent", [False, True], ids=("root", "parent"))
def test_runtime_rejects_symlink_in_authorized_root_path_before_source_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    symlink_parent: bool,
) -> None:
    real_directory = tmp_path / "real"
    real_directory.mkdir()
    if symlink_parent:
        linked_parent = tmp_path / "linked-parent"
        linked_parent.symlink_to(real_directory, target_is_directory=True)
        authorized_root = linked_parent / "authorized"
    else:
        authorized_root = tmp_path / "authorized"
        authorized_root.symlink_to(real_directory, target_is_directory=True)
    monkeypatch.setattr(cli, "AUTHORIZED_RUNTIME_ROOT", authorized_root)
    constructions = _forbid_runtime_source(monkeypatch)

    assert cli.main(_runtime_command(authorized_root)) == 2

    assert constructions == []
    assert "symbolic links" in json.loads(capsys.readouterr().out)["error"]


def test_runtime_rejects_non_none_event_state_before_source_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorized_root = tmp_path / "authorized"
    monkeypatch.setattr(cli, "AUTHORIZED_RUNTIME_ROOT", authorized_root)
    constructions = _forbid_runtime_source(monkeypatch)

    assert cli.main(_runtime_command(authorized_root, event_state="PRE_EVENT")) == 2

    assert constructions == []
    assert "event state" in json.loads(capsys.readouterr().out)["error"]


def test_runtime_rejects_non_authorized_workbench_port_before_source_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorized_root = tmp_path / "authorized"
    monkeypatch.setattr(cli, "AUTHORIZED_RUNTIME_ROOT", authorized_root)
    constructions = _forbid_runtime_source(monkeypatch)

    assert cli.main(_runtime_command(authorized_root, workbench_port=8766)) == 2

    assert constructions == []
    assert "Workbench port" in json.loads(capsys.readouterr().out)["error"]


def test_runtime_rejects_foreign_policy_identity_before_source_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorized_root = tmp_path / "authorized"
    monkeypatch.setattr(cli, "AUTHORIZED_RUNTIME_ROOT", authorized_root)
    constructions = _forbid_runtime_source(monkeypatch)
    policy_value = json.loads(DEFAULT_BTC_SHORT_VOL_POLICY_PATH.read_text(encoding="utf-8"))
    policy_value["policy_name"] = "FOREIGN_BTC_POLICY"
    foreign_policy = tmp_path / "foreign-policy.json"
    foreign_policy.write_text(json.dumps(policy_value), encoding="utf-8")

    assert cli.main(_runtime_command(authorized_root, policy_path=foreign_policy)) == 2

    assert constructions == []
    assert "policy identity" in json.loads(capsys.readouterr().out)["error"]


def test_runtime_accepts_an_alternate_path_with_the_frozen_policy_identity_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorized_root = tmp_path / "authorized"
    monkeypatch.setattr(cli, "AUTHORIZED_RUNTIME_ROOT", authorized_root)
    policy_copy = tmp_path / "policy-copy.json"
    policy_copy.write_text(
        DEFAULT_BTC_SHORT_VOL_POLICY_PATH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    observed: dict[str, object] = {}

    def fake_source(**kwargs: object) -> object:
        observed["source"] = kwargs
        return object()

    class FakeRuntime:
        def __init__(self, **kwargs: object) -> None:
            observed["runtime"] = kwargs
            self.session = SimpleNamespace(session_id="2026-08-14T08:00:00Z")

        def run_forever(self, *, port: int) -> int:
            observed["port"] = port
            return 0

    monkeypatch.setattr(cli, "DeribitPublicRuntimeSource", fake_source)
    monkeypatch.setattr(cli, "BtcPublicShadowRuntime", FakeRuntime)

    assert cli.main(_runtime_command(authorized_root, policy_path=policy_copy)) == 0

    assert observed["port"] == 8765
    assert cast(dict[str, object], observed["runtime"])["root"] == authorized_root
    output = json.loads(capsys.readouterr().out)
    assert output["root"] == str(authorized_root)
