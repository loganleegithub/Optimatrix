from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from test_workbench import _snapshot

import optimatrix.cli as cli
from optimatrix.decision import DecisionWindow
from optimatrix.deribit_snapshot import (
    DeribitClockReading,
    PublicClockPreflight,
)
from optimatrix.policy import DEFAULT_BTC_SHORT_VOL_POLICY_PATH, load_btc_short_vol_policy
from optimatrix.session import current_deribit_session


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


def test_runtime_rejects_the_new_entry_policy_without_network(
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
    constructions = _forbid_runtime_source(monkeypatch)

    assert cli.main(_runtime_command(authorized_root, policy_path=policy_copy)) == 2

    assert constructions == []
    assert "policy identity" in json.loads(capsys.readouterr().out)["error"]


def _clock_reading(at: datetime) -> DeribitClockReading:
    return DeribitClockReading(
        earliest_at=at - timedelta(milliseconds=1),
        estimate_at=at,
        latest_at=at + timedelta(milliseconds=1),
        monotonic_ns=1_000_000_000,
    )


def test_runtime_cli_delegates_time_authority_without_reading_host_wall(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorized_root = tmp_path / "authorized"
    deribit_now = datetime(2026, 8, 14, 9, 2, tzinfo=UTC)
    reading = _clock_reading(deribit_now)
    events: list[str] = []

    class FakeSource:
        def __init__(self, **_kwargs: object) -> None:
            events.append("SOURCE_CONSTRUCTED")

        def clock_reading(self) -> DeribitClockReading:
            return reading

    class FakeRuntime:
        def __init__(self, **kwargs: object) -> None:
            events.append("RUNTIME_CONSTRUCTED")
            assert events == [
                "SOURCE_CONSTRUCTED",
                "RUNTIME_CONSTRUCTED",
            ]
            assert kwargs["root"] == authorized_root
            assert "now" not in kwargs
            source = cast(FakeSource, kwargs["source"])
            self.session = current_deribit_session(source.clock_reading().estimate_at)

        def run_forever(self, *, port: int) -> int:
            assert port == 8765
            return 0

    monkeypatch.setattr(cli, "AUTHORIZED_RUNTIME_ROOT", authorized_root)
    monkeypatch.setattr(
        cli,
        "AUTHORIZED_RUNTIME_POLICY_IDENTITY",
        load_btc_short_vol_policy(DEFAULT_BTC_SHORT_VOL_POLICY_PATH).identity,
    )
    monkeypatch.setattr(cli, "DeribitPublicRuntimeSource", FakeSource)
    monkeypatch.setattr(cli, "BtcPublicShadowRuntime", FakeRuntime)

    assert not hasattr(cli, "datetime")

    assert cli.main(_runtime_command(authorized_root)) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["session_id"] == "2026-08-15T08:00:00Z"


def test_snapshot_cli_projects_post_preflight_clock_and_binds_explicit_window(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stale = datetime(2026, 8, 14, 9, 1, 59, tzinfo=UTC)
    earliest = datetime(2026, 8, 14, 9, 2, tzinfo=UTC)
    projected = DeribitClockReading(
        earliest_at=earliest,
        estimate_at=earliest + timedelta(milliseconds=500),
        latest_at=earliest + timedelta(seconds=1),
        monotonic_ns=2_000_000_000,
    )
    events: list[str] = []
    observed: dict[str, object] = {}

    class FakeClock:
        def read(self) -> DeribitClockReading:
            events.append("CLOCK_READ")
            return projected

    class FakeClient:
        def __init__(self, **_kwargs: object) -> None:
            self.clock = FakeClock()

    def fake_preflight(client: object) -> PublicClockPreflight:
        assert isinstance(client, FakeClient)
        events.append("PREFLIGHT")
        stale_reading = DeribitClockReading(
            earliest_at=stale,
            estimate_at=stale,
            latest_at=stale,
            monotonic_ns=1_000_000_000,
        )
        return PublicClockPreflight(
            server_time_ms=int(stale.timestamp() * 1000),
            request_round_trip_ms=1,
            known_at=stale,
            clock_reading=stale_reading,
        )

    def fake_evaluate(**kwargs: object) -> object:
        events.append("EVALUATE")
        observed.update(kwargs)
        return SimpleNamespace(as_object=lambda: {"projection": "captured"})

    monkeypatch.setattr(cli, "DeribitHttpClient", FakeClient)
    monkeypatch.setattr(cli, "preflight_public_clock", fake_preflight)
    monkeypatch.setattr(cli, "evaluate_live_btc_snapshot", fake_evaluate)

    assert cli.main(["snapshot", "--event-state", "NONE"]) == 0

    assert events.index("PREFLIGHT") < events.index("CLOCK_READ") < events.index("EVALUATE")
    assert observed["now"] == earliest
    target_window = cast(DecisionWindow, observed["target_window"])
    assert target_window.starts_at == datetime(2026, 8, 14, 9, tzinfo=UTC)
    assert target_window.ends_at == datetime(2026, 8, 14, 9, 15, tzinfo=UTC)
    assert target_window.starts_at <= earliest < target_window.ends_at
    assert json.loads(capsys.readouterr().out) == {"projection": "captured"}
