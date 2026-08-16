from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path

from optimatrix.ai_lab.canonical import (
    AI_LAB_DURABLE_ROOT,
    JsonObject,
    ValidationError,
    canonical_bytes,
    decimal_text,
    isolated_path,
    load_json,
    parse_decimal,
    parse_utc,
    require_int,
    require_text,
    seal_object,
    strict_fields,
    utc_text,
    verify_seal,
)
from optimatrix.deribit_snapshot import (
    DERIBIT_INDEX_PATH_SOURCE_ID,
    DeribitHttpClient,
    btc_index_history_cadence_ms,
    fetch_btc_index_history,
    preflight_public_clock,
)
from optimatrix.products import BTC
from optimatrix.session import current_deribit_session

OFFICIAL_INDEX_EVIDENCE_SCHEMA = "optimatrix.ai-lab.official-index-evidence.v1"
OFFICIAL_INDEX_EVIDENCE_NAMESPACE = "OptimatrixAiLabOfficialIndexEvidenceV1"
OFFICIAL_INDEX_EVIDENCE_METHOD_ID = "DERIBIT_OFFICIAL_BTC_USD_2D_SAMPLED_FORWARD_LOG_VARIANCE_V1"
OFFICIAL_INDEX_RANGE = "2d"
MAXIMUM_SUPPORTED_CADENCE_MS = 15 * 60_000


@dataclass(frozen=True)
class CoverageGap:
    starts_at_ms: int
    ends_at_ms: int
    reason: str

    def __post_init__(self) -> None:
        if self.starts_at_ms < 0 or self.ends_at_ms <= self.starts_at_ms or not self.reason:
            raise ValueError("official index coverage gap is invalid")

    def as_object(self) -> JsonObject:
        return {
            "starts_at_ms": self.starts_at_ms,
            "ends_at_ms": self.ends_at_ms,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class OfficialIndexEvidence:
    session_id: str
    requested_at: datetime
    cadence_ms: int
    points: tuple[tuple[int, Decimal], ...]

    def __post_init__(self) -> None:
        expiry = _session_expiry(self.session_id)
        if self.requested_at < expiry:
            raise ValueError("official hindsight evidence cannot precede Session expiry")
        if (
            isinstance(self.cadence_ms, bool)
            or not isinstance(self.cadence_ms, int)
            or not 0 < self.cadence_ms <= MAXIMUM_SUPPORTED_CADENCE_MS
        ):
            raise ValueError("official index cadence is invalid or too coarse")
        if len(self.points) < 3:
            raise ValueError("official index evidence requires at least three points")
        normalized: list[tuple[int, Decimal]] = []
        for timestamp_ms, price in self.points:
            if (
                isinstance(timestamp_ms, bool)
                or not isinstance(timestamp_ms, int)
                or timestamp_ms < 0
                or not price.is_finite()
                or price <= 0
            ):
                raise ValueError("official index point is invalid")
            normalized.append((timestamp_ms, price))
        if any(current[0] <= previous[0] for previous, current in pairwise(normalized)):
            raise ValueError("official index points must be strictly chronological")
        detected = btc_index_history_cadence_ms(
            tuple(normalized),
            horizon_minutes=24 * 60,
        )
        if detected != self.cadence_ms:
            raise ValueError("official index cadence does not match its raw points")

    @classmethod
    def from_history(
        cls,
        *,
        session_id: str,
        requested_at: datetime,
        history: tuple[tuple[int, Decimal], ...],
    ) -> OfficialIndexEvidence:
        cadence_ms = btc_index_history_cadence_ms(history, horizon_minutes=24 * 60)
        return cls(
            session_id=session_id,
            requested_at=requested_at,
            cadence_ms=cadence_ms,
            points=history,
        )

    @classmethod
    def from_object(cls, value: object) -> OfficialIndexEvidence:
        item = strict_fields(
            value,
            {
                "schema_version",
                "evidence_id",
                "session_id",
                "requested_at",
                "source_id",
                "method_id",
                "index_name",
                "range",
                "cadence_ms",
                "point_count",
                "points",
                "session_coverage_complete",
                "coverage_gaps",
                "boundary",
            },
            "official_index_evidence",
        )
        if item["schema_version"] != OFFICIAL_INDEX_EVIDENCE_SCHEMA:
            raise ValidationError("unsupported official index evidence schema")
        verify_seal(
            item,
            id_field="evidence_id",
            namespace=OFFICIAL_INDEX_EVIDENCE_NAMESPACE,
        )
        raw_points = item["points"]
        if not isinstance(raw_points, list):
            raise ValidationError("official index points must be an array")
        points: list[tuple[int, Decimal]] = []
        for index, raw in enumerate(raw_points):
            point = strict_fields(
                raw,
                {"timestamp_ms", "index_price_usd"},
                f"official index point {index}",
            )
            points.append(
                (
                    require_int(
                        point["timestamp_ms"],
                        f"official index point {index}.timestamp_ms",
                    ),
                    parse_decimal(
                        point["index_price_usd"],
                        f"official index point {index}.index_price_usd",
                        positive=True,
                    ),
                )
            )
        evidence = cls(
            session_id=require_text(item["session_id"], "official_index_evidence.session_id"),
            requested_at=parse_utc(
                item["requested_at"],
                "official_index_evidence.requested_at",
            ),
            cadence_ms=require_int(
                item["cadence_ms"],
                "official_index_evidence.cadence_ms",
                minimum=1,
            ),
            points=tuple(points),
        )
        if item != evidence.as_object():
            raise ValidationError("official index evidence derived fields are inconsistent")
        return evidence

    @property
    def identity(self) -> str:
        return str(self.as_object()["evidence_id"])

    @property
    def coverage_gaps(self) -> tuple[CoverageGap, ...]:
        expiry = _session_expiry(self.session_id)
        return self._coverage_gaps(
            starts_at=expiry - timedelta(days=1),
            ends_at=expiry,
        )

    @property
    def session_coverage_complete(self) -> bool:
        return not self.coverage_gaps

    def forward_variance(
        self,
        *,
        starts_at: datetime,
        start_price_usd: Decimal,
        delivery_price_usd: Decimal,
    ) -> Decimal | None:
        expiry = _session_expiry(self.session_id)
        if not (
            expiry - timedelta(days=1) <= starts_at < expiry
            and start_price_usd.is_finite()
            and start_price_usd > 0
            and delivery_price_usd.is_finite()
            and delivery_price_usd > 0
        ):
            raise ValueError("official forward-variance inputs are invalid")
        if self._coverage_gaps(starts_at=starts_at, ends_at=expiry):
            return None
        start_ms = _timestamp_ms(starts_at)
        end_ms = _timestamp_ms(expiry)
        interior = tuple(point for point in self.points if start_ms < point[0] < end_ms)
        prices = (start_price_usd, *(price for _timestamp, price in interior), delivery_price_usd)
        return sum(
            (((right / left).ln()) ** 2 for left, right in pairwise(prices)),
            Decimal(0),
        )

    def as_object(self) -> JsonObject:
        draft: JsonObject = {
            "schema_version": OFFICIAL_INDEX_EVIDENCE_SCHEMA,
            "session_id": self.session_id,
            "requested_at": utc_text(self.requested_at),
            "source_id": DERIBIT_INDEX_PATH_SOURCE_ID,
            "method_id": OFFICIAL_INDEX_EVIDENCE_METHOD_ID,
            "index_name": BTC.price_index,
            "range": OFFICIAL_INDEX_RANGE,
            "cadence_ms": self.cadence_ms,
            "point_count": len(self.points),
            "points": [
                {
                    "timestamp_ms": timestamp_ms,
                    "index_price_usd": decimal_text(price),
                }
                for timestamp_ms, price in self.points
            ],
            "session_coverage_complete": self.session_coverage_complete,
            "coverage_gaps": [item.as_object() for item in self.coverage_gaps],
            "boundary": (
                "Post-Session public Deribit index history supports sampled hindsight variance "
                "only. It cannot reconstruct a decision-time option book, Base Decision, quote, "
                "fill, account fact, or executable liquidity."
            ),
        }
        return seal_object(
            draft,
            id_field="evidence_id",
            namespace=OFFICIAL_INDEX_EVIDENCE_NAMESPACE,
        )

    def _coverage_gaps(
        self,
        *,
        starts_at: datetime,
        ends_at: datetime,
    ) -> tuple[CoverageGap, ...]:
        start_ms = _timestamp_ms(starts_at)
        end_ms = _timestamp_ms(ends_at)
        if start_ms >= end_ms:
            raise ValueError("official index coverage interval must be positive")
        interval = tuple(point for point in self.points if start_ms < point[0] < end_ms)
        tolerance = self.cadence_ms * 2
        if not interval:
            return (CoverageGap(start_ms, end_ms, "NO_OFFICIAL_INDEX_POINTS"),)
        gaps: list[CoverageGap] = []
        if interval[0][0] > start_ms + tolerance:
            gaps.append(CoverageGap(start_ms, interval[0][0], "OFFICIAL_INDEX_PATH_START_LATE"))
        gaps.extend(
            CoverageGap(previous[0], current[0], "OFFICIAL_INDEX_PATH_MATERIAL_GAP")
            for previous, current in pairwise(interval)
            if current[0] - previous[0] > tolerance
        )
        if interval[-1][0] < end_ms - tolerance:
            gaps.append(CoverageGap(interval[-1][0], end_ms, "OFFICIAL_INDEX_PATH_END_EARLY"))
        return tuple(gaps)


def fetch_official_index_evidence(
    *,
    session_id: str,
    timeout_seconds: float = 10.0,
) -> OfficialIndexEvidence:
    """Perform the fixed two-call public Deribit evidence fetch for one ended Session."""

    expiry = _session_expiry(session_id)
    client = DeribitHttpClient(timeout_seconds=timeout_seconds)
    preflight = preflight_public_clock(client)
    if preflight.clock_reading.earliest_at < expiry:
        raise ValidationError("official hindsight fetch requires an ended Session")
    history = fetch_btc_index_history(
        client,
        known_at=preflight.clock_reading.latest_at,
    )
    return OfficialIndexEvidence.from_history(
        session_id=session_id,
        requested_at=client.clock.read().latest_at,
        history=history,
    )


def write_official_index_evidence(
    evidence: OfficialIndexEvidence,
    *,
    root: Path = AI_LAB_DURABLE_ROOT,
) -> Path:
    lab_root = isolated_path(root)
    session_slug = evidence.session_id.replace("-", "").replace(":", "")
    path = (
        lab_root
        / "evidence"
        / session_slug
        / evidence.identity.removeprefix("sha256:")[:16]
        / "official-index-history.json"
    )
    payload = canonical_bytes(evidence.as_object()) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise ValidationError(f"refusing to overwrite different official evidence: {path}")
        return path
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ValidationError(f"official evidence appeared concurrently: {path}") from exc
    return path


def load_official_index_evidence(path: Path) -> OfficialIndexEvidence:
    return OfficialIndexEvidence.from_object(load_json(path))


def _session_expiry(session_id: str) -> datetime:
    expiry = parse_utc(session_id, "official_index_evidence.session_id")
    session = current_deribit_session(expiry - timedelta(microseconds=1))
    if session.session_id != session_id:
        raise ValidationError("official index evidence requires a canonical Deribit Session")
    return expiry


def _timestamp_ms(value: datetime) -> int:
    if value.tzinfo is None:
        raise ValueError("official index timestamp must be timezone-aware")
    return int(value.timestamp() * 1_000)
