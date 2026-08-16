from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

import optimatrix.ai_lab.cli as ai_lab_cli
import optimatrix.ai_lab.hindsight_evidence as hindsight_evidence
from optimatrix.ai_lab.canonical import ValidationError
from optimatrix.ai_lab.cli import main as ai_lab_main
from optimatrix.ai_lab.hindsight_evidence import (
    OfficialIndexEvidence,
    fetch_official_index_evidence,
    load_official_index_evidence,
    write_official_index_evidence,
)
from optimatrix.ai_lab.session_review import (
    HindsightRvSource,
    SessionVerdict,
    WindowEvidenceStatus,
    review_session,
)
from tests.ai_lab.test_session_review import _population


def test_official_evidence_round_trips_and_restores_known_windows(policy, tmp_path) -> None:
    session_id, records, outcomes = _population(
        policy,
        implied_variance=Decimal("0.0011"),
        realized_variance=Decimal("0.0010"),
        delivery_price=Decimal("100000"),
        path_mode="SAFE_ALL",
    )
    evidence = OfficialIndexEvidence.from_history(
        session_id=session_id,
        requested_at=_expiry(session_id) + timedelta(hours=1),
        history=_history(session_id),
    )
    path = write_official_index_evidence(evidence, root=tmp_path / "ai-lab")

    assert load_official_index_evidence(path) == evidence
    assert evidence.session_coverage_complete
    review = review_session(
        session_id=session_id,
        policy=policy,
        records=records[:-1],
        outcomes=outcomes,
        official_index_evidence=evidence,
    )

    assert review.auditable_window_count == 95
    assert review.unknown_window_count == 1
    assert review.verdict is SessionVerdict.OBSERVED_RULE_TOO_CONSERVATIVE
    assert review.official_index_evidence == evidence
    assert review.coverage_fraction == Decimal(95) / Decimal(96)
    assert all(
        window.hindsight_rv_source is HindsightRvSource.OFFICIAL_INDEX_HISTORY
        for window in review.windows
        if window.evidence_status is WindowEvidenceStatus.AUDITABLE
    )
    assert "SESSION_IV_RV_CURVE_INCOMPLETE" not in dict(review.evidence_reason_counts)


def test_official_gap_invalidates_only_windows_whose_future_path_crosses_it() -> None:
    session_id = "2026-08-15T08:00:00Z"
    expiry = _expiry(session_id)
    gap_start = expiry - timedelta(hours=12)
    history = tuple(
        point
        for point in _history(session_id)
        if not gap_start <= _from_ms(point[0]) < gap_start + timedelta(minutes=20)
    )
    evidence = OfficialIndexEvidence.from_history(
        session_id=session_id,
        requested_at=expiry + timedelta(hours=1),
        history=history,
    )

    assert not evidence.session_coverage_complete
    assert any(gap.reason == "OFFICIAL_INDEX_PATH_MATERIAL_GAP" for gap in evidence.coverage_gaps)
    assert (
        evidence.forward_variance(
            starts_at=gap_start - timedelta(minutes=30),
            start_price_usd=Decimal("100000"),
            delivery_price_usd=Decimal("100000"),
        )
        is None
    )
    later_variance = evidence.forward_variance(
        starts_at=gap_start + timedelta(minutes=30),
        start_price_usd=Decimal("100000"),
        delivery_price_usd=Decimal("100000"),
    )
    assert later_variance is not None and later_variance >= 0


def test_official_evidence_tamper_is_rejected() -> None:
    session_id = "2026-08-15T08:00:00Z"
    evidence = OfficialIndexEvidence.from_history(
        session_id=session_id,
        requested_at=_expiry(session_id) + timedelta(hours=1),
        history=_history(session_id),
    ).as_object()
    evidence["points"][0]["index_price_usd"] = "99999"

    with pytest.raises(ValidationError, match="content identity mismatch"):
        OfficialIndexEvidence.from_object(evidence)


def test_fixed_fetch_uses_preflight_boundary_and_two_day_history(monkeypatch) -> None:
    session_id = "2026-08-15T08:00:00Z"
    expiry = _expiry(session_id)
    requested_at = expiry + timedelta(hours=1)
    calls: list[object] = []

    class _Clock:
        def read(self):
            return SimpleNamespace(latest_at=requested_at)

    class _Client:
        clock = _Clock()

    def client_factory(*, timeout_seconds: float):
        calls.append(("client", timeout_seconds))
        return _Client()

    def preflight(client):
        calls.append(("preflight", client))
        return SimpleNamespace(
            clock_reading=SimpleNamespace(
                earliest_at=requested_at,
                latest_at=requested_at,
            )
        )

    def fetch(client, *, known_at):
        calls.append(("history", client, known_at))
        return _history(session_id)

    monkeypatch.setattr(hindsight_evidence, "DeribitHttpClient", client_factory)
    monkeypatch.setattr(hindsight_evidence, "preflight_public_clock", preflight)
    monkeypatch.setattr(hindsight_evidence, "fetch_btc_index_history", fetch)

    evidence = fetch_official_index_evidence(session_id=session_id)

    assert evidence.session_id == session_id
    assert calls[0] == ("client", 10.0)
    assert calls[1][0] == "preflight"
    assert calls[2][0] == "history"
    assert calls[2][2] == requested_at


def test_fetch_cli_writes_only_content_sealed_lab_evidence(monkeypatch, tmp_path, capsys) -> None:
    session_id = "2026-08-15T08:00:00Z"
    evidence = OfficialIndexEvidence.from_history(
        session_id=session_id,
        requested_at=_expiry(session_id) + timedelta(hours=1),
        history=_history(session_id),
    )
    monkeypatch.setattr(
        ai_lab_cli,
        "fetch_official_index_evidence",
        lambda *, session_id: evidence,
    )

    status = ai_lab_main(
        [
            "fetch-official-evidence",
            "--session-id",
            session_id,
            "--lab-root",
            str(tmp_path / "ai-lab"),
        ]
    )

    assert status == 0
    output = capsys.readouterr().out
    assert evidence.identity in output
    files = tuple((tmp_path / "ai-lab" / "evidence").rglob("official-index-history.json"))
    assert len(files) == 1
    assert load_official_index_evidence(files[0]) == evidence


def _history(session_id: str) -> tuple[tuple[int, Decimal], ...]:
    expiry = _expiry(session_id)
    cursor = expiry - timedelta(days=1, minutes=5)
    end = expiry + timedelta(minutes=5)
    points = []
    sequence = 0
    while cursor <= end:
        points.append((_to_ms(cursor), Decimal("100000") + Decimal(sequence % 7)))
        cursor += timedelta(minutes=5)
        sequence += 1
    return tuple(points)


def _expiry(session_id: str) -> datetime:
    return datetime.fromisoformat(session_id.replace("Z", "+00:00")).astimezone(UTC)


def _to_ms(value: datetime) -> int:
    return int(value.timestamp() * 1_000)


def _from_ms(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1_000, tz=UTC)
