from __future__ import annotations

import fcntl
import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from typing import Protocol

from optimatrix.case_journal import CaseJournal
from optimatrix.decision import DecisionRecord, DecisionResult, DecisionWindow
from optimatrix.deribit_snapshot import (
    DERIBIT_DELIVERY_PRICE_METHOD_ID,
    DERIBIT_DELIVERY_PRICE_SOURCE_ID,
    DERIBIT_INDEX_PATH_METHOD_ID,
    DERIBIT_INDEX_PATH_SOURCE_ID,
    DeribitClockReading,
    DeribitHttpClient,
    DeribitSourceError,
    PublicClockPreflight,
    PublicSnapshotEvaluation,
    evaluate_live_btc_snapshot,
    fetch_btc_expiry_settlement,
    fetch_btc_index_history,
    preflight_public_clock,
    summarize_btc_index_path,
)
from optimatrix.engine import Btc0DteShortVolEngine
from optimatrix.identity import canonical_identity
from optimatrix.lifecycle import (
    PositionState,
    TradeCase,
    WindowOutcome,
    open_trade_case,
    window_outcome_eligibility,
)
from optimatrix.market import EventState, ExpirySettlementFact, SettlementEvidenceKind
from optimatrix.observation_ledger import ObservationLedger
from optimatrix.policy import BtcShortVolPolicy
from optimatrix.products import BTC
from optimatrix.risk import ShadowCapacity
from optimatrix.session import DeribitSession, current_deribit_session
from optimatrix.workbench import write_workbench

AUTHORIZED_RUNTIME_ROOT = Path(
    "/Users/logan/Library/Application Support/Optimatrix/b3-public-shadow-v1"
)
AUTHORIZED_RUNTIME_POLICY_IDENTITY = (
    "sha256:2e9fa566556b6223fc406ca4dd0577261c04817621fc4837b568435b6e44b21e"
)
AUTHORIZED_WORKBENCH_PORT = 8765
ROOT_SCHEMA_VERSION = 1
RUNTIME_SCHEMA_VERSION = 2
PREFLIGHT_LEAD = timedelta(minutes=5)
SETTLEMENT_DELAY = timedelta(minutes=5)
_RUNTIME_ALLOWED_ROOT_MEMBERS = {
    "cases",
    "decision-records.jsonl",
    "future-index-path.json",
    "future-index-paths.jsonl",
    "latest-snapshot.json",
    "manifest.json",
    "runtime-events.jsonl",
    "runtime-lock",
    "runtime-state.json",
    "settlement.json",
    "settlements.jsonl",
    "window-outcomes.jsonl",
    "workbench",
}
_RUNTIME_DIRECTORY_MEMBERS = {"cases", "workbench"}
_RUNTIME_FILE_MEMBERS = _RUNTIME_ALLOWED_ROOT_MEMBERS - _RUNTIME_DIRECTORY_MEMBERS
_RUNTIME_TEMP_MEMBERS = {
    ".future-index-path.json.optimatrix-tmp",
    ".latest-snapshot.json.optimatrix-tmp",
    ".manifest.json.optimatrix-tmp",
    ".runtime-state.json.optimatrix-tmp",
    ".settlement.json.optimatrix-tmp",
}
_WORKBENCH_ALLOWED_MEMBERS = {"app.js", "index.html", "styles.css", "workbench-data.js"}
_WORKBENCH_TEMP_MEMBERS = {f".{name}.optimatrix-tmp" for name in _WORKBENCH_ALLOWED_MEMBERS}


class BtcPublicRuntimeSource(Protocol):
    def preflight(
        self,
        *,
        local_now: datetime | None = None,
    ) -> PublicClockPreflight | datetime: ...

    def clock_reading(self) -> DeribitClockReading: ...

    def snapshot(
        self,
        *,
        now: datetime,
        target_window: DecisionWindow,
        required_instrument_names: tuple[str, ...],
    ) -> PublicSnapshotEvaluation: ...

    def history(self, *, known_at: datetime) -> IndexHistoryCapture: ...

    def settlement(
        self,
        *,
        expiry: datetime,
        known_at: datetime,
    ) -> ExpirySettlementFact | None: ...


class DeribitPublicRuntimeSource:
    """Production-public Deribit source for the single BTC runtime."""

    def __init__(
        self,
        *,
        policy: BtcShortVolPolicy,
        event_state: EventState,
        timeout_seconds: float = 10.0,
        maximum_books: int = 32,
        depth: int = 20,
    ) -> None:
        if policy.identity != AUTHORIZED_RUNTIME_POLICY_IDENTITY:
            raise ValueError("runtime source requires the authorized frozen Policy")
        if event_state is not EventState.NONE:
            raise ValueError("runtime source requires the authorized NONE event state")
        if timeout_seconds != 10.0 or maximum_books != 32 or depth != 20:
            raise ValueError("runtime source bounds must match the active task")
        self.policy = policy
        self.event_state = event_state
        self.maximum_books = maximum_books
        self.depth = depth
        self.client = DeribitHttpClient(timeout_seconds=timeout_seconds)

    def preflight(
        self,
        *,
        local_now: datetime | None = None,
    ) -> PublicClockPreflight:
        del local_now
        return preflight_public_clock(self.client)

    def clock_reading(self) -> DeribitClockReading:
        return self.client.clock.read()

    def snapshot(
        self,
        *,
        now: datetime,
        target_window: DecisionWindow,
        required_instrument_names: tuple[str, ...],
    ) -> PublicSnapshotEvaluation:
        return evaluate_live_btc_snapshot(
            client=self.client,
            policy=self.policy,
            now=now,
            event_state=self.event_state,
            maximum_books=self.maximum_books,
            depth=self.depth,
            target_window=target_window,
            required_instrument_names=required_instrument_names,
        )

    def history(self, *, known_at: datetime) -> IndexHistoryCapture:
        points = fetch_btc_index_history(self.client, known_at=known_at)
        return IndexHistoryCapture(
            points=points,
            known_at=self.clock_reading().latest_at,
            error=None,
        )

    def bind_audit(
        self,
        callback: Callable[[str, Mapping[str, object], float], None],
    ) -> None:
        self.client.audit_callback = callback

    def settlement(
        self,
        *,
        expiry: datetime,
        known_at: datetime,
    ) -> ExpirySettlementFact | None:
        return fetch_btc_expiry_settlement(
            self.client,
            expiry=expiry,
            known_at=known_at,
        )


@dataclass(frozen=True)
class IndexHistoryCapture:
    points: tuple[tuple[int, Decimal], ...] | None
    known_at: datetime
    error: str | None

    def __post_init__(self) -> None:
        known_at = _utc(self.known_at)
        if (self.points is None) != (self.error is not None):
            raise ValueError("history capture must contain either points or one error")
        if self.error is not None and not self.error:
            raise ValueError("history capture error must be non-empty")
        if self.points is None:
            return
        previous = -1
        for timestamp_ms, price in self.points:
            if timestamp_ms <= previous or price <= 0 or not price.is_finite():
                raise ValueError("history capture points must be chronological and positive")
            if timestamp_ms > int(known_at.timestamp() * 1000):
                raise ValueError("history capture cannot contain future points")
            previous = timestamp_ms

    def as_object(self, session_id: str) -> dict[str, object]:
        return {
            "schema_version": ROOT_SCHEMA_VERSION,
            "session_id": session_id,
            "known_at": _iso(self.known_at),
            "points": (
                [[timestamp_ms, str(price)] for timestamp_ms, price in self.points]
                if self.points is not None
                else None
            ),
            "error": self.error,
        }

    @classmethod
    def from_object(cls, value: object, *, session_id: str) -> IndexHistoryCapture:
        item = _mapping(value, "future index path capture")
        if set(item) != {"schema_version", "session_id", "known_at", "points", "error"}:
            raise ValueError("future index path capture has foreign fields")
        if (
            item.get("schema_version") != ROOT_SCHEMA_VERSION
            or item.get("session_id") != session_id
        ):
            raise ValueError("future index path capture belongs to another runtime Session")
        error = item.get("error")
        if error is not None and (not isinstance(error, str) or not error):
            raise ValueError("future index path capture error must be text or null")
        raw_points = item.get("points")
        points: tuple[tuple[int, Decimal], ...] | None
        if raw_points is None:
            points = None
        elif isinstance(raw_points, list):
            parsed: list[tuple[int, Decimal]] = []
            for member in raw_points:
                if (
                    not isinstance(member, list)
                    or len(member) != 2
                    or isinstance(member[0], bool)
                    or not isinstance(member[0], int)
                ):
                    raise ValueError("future index path capture contains a malformed point")
                try:
                    price = Decimal(str(member[1]))
                except Exception as exc:
                    raise ValueError(
                        "future index path capture contains a malformed price"
                    ) from exc
                parsed.append((member[0], price))
            points = tuple(parsed)
        else:
            raise ValueError("future index path capture points must be an array or null")
        return cls(points=points, known_at=_datetime(item, "known_at"), error=error)


@dataclass(frozen=True)
class RuntimeManifest:
    implementation_id: str
    policy_id: str
    channel_id: str
    target_session_id: str
    session_start: datetime
    session_end: datetime
    created_at: datetime

    def as_object(self) -> dict[str, object]:
        return {
            "schema_version": ROOT_SCHEMA_VERSION,
            "implementation_id": self.implementation_id,
            "policy_id": self.policy_id,
            "channel_id": self.channel_id,
            "target_session_id": self.target_session_id,
            "session_start": _iso(self.session_start),
            "session_end": _iso(self.session_end),
            "created_at": _iso(self.created_at),
        }

    @classmethod
    def from_object(cls, value: object) -> RuntimeManifest:
        item = _mapping(value, "runtime manifest")
        expected = {
            "schema_version",
            "implementation_id",
            "policy_id",
            "channel_id",
            "target_session_id",
            "session_start",
            "session_end",
            "created_at",
        }
        if set(item) != expected or item.get("schema_version") != ROOT_SCHEMA_VERSION:
            raise ValueError("runtime root manifest schema is foreign")
        return cls(
            implementation_id=_text(item, "implementation_id"),
            policy_id=_text(item, "policy_id"),
            channel_id=_text(item, "channel_id"),
            target_session_id=_text(item, "target_session_id"),
            session_start=_datetime(item, "session_start"),
            session_end=_datetime(item, "session_end"),
            created_at=_datetime(item, "created_at"),
        )


@dataclass(frozen=True)
class RuntimeProgress:
    started_at: datetime
    updated_at: datetime
    restart_count: int
    recovered_case_count: int
    attempted_decision_window_ids: tuple[str, ...]
    active_session_id: str
    preflight_attempt_count: int
    preflight_complete: bool
    settlement_attempt_counts: tuple[tuple[str, int], ...]
    history_attempt_counts: tuple[tuple[str, int], ...]
    case_attempted_at: tuple[tuple[str, datetime], ...]
    status: str
    last_error: str | None

    def as_object(self) -> dict[str, object]:
        return {
            "schema_version": RUNTIME_SCHEMA_VERSION,
            "started_at": _iso(self.started_at),
            "updated_at": _iso(self.updated_at),
            "restart_count": self.restart_count,
            "recovered_case_count": self.recovered_case_count,
            "attempted_decision_window_ids": list(self.attempted_decision_window_ids),
            "active_session_id": self.active_session_id,
            "preflight_attempt_count": self.preflight_attempt_count,
            "preflight_complete": self.preflight_complete,
            "settlement_attempt_counts": dict(self.settlement_attempt_counts),
            "history_attempt_counts": dict(self.history_attempt_counts),
            "case_attempted_at": {case_id: _iso(at) for case_id, at in self.case_attempted_at},
            "status": self.status,
            "last_error": self.last_error,
        }

    @classmethod
    def from_object(
        cls,
        value: object,
        *,
        first_session_id: str,
        active_session_id: str,
    ) -> RuntimeProgress:
        item = _mapping(value, "runtime progress")
        attempted = item.get("attempted_decision_window_ids")
        if not isinstance(attempted, list) or not all(
            isinstance(member, str) for member in attempted
        ):
            raise ValueError("runtime attempted windows must be an array of strings")
        last_error = item.get("last_error")
        if last_error is not None and not isinstance(last_error, str):
            raise ValueError("runtime last_error must be text or null")
        schema_version = item.get("schema_version")
        if schema_version not in {1, RUNTIME_SCHEMA_VERSION}:
            raise ValueError("runtime progress schema is foreign")
        settlement_attempt_counts: tuple[tuple[str, int], ...]
        history_attempt_counts: tuple[tuple[str, int], ...]
        if schema_version == 1:
            legacy_expected = {
                "schema_version",
                "started_at",
                "updated_at",
                "restart_count",
                "recovered_case_count",
                "attempted_decision_window_ids",
                "preflight_attempt_count",
                "preflight_complete",
                "settlement_attempt_count",
                "history_attempt_count",
                "case_attempted_at",
                "status",
                "last_error",
            }
            if set(item) != legacy_expected:
                raise ValueError("runtime progress has foreign fields")
            settlement_count = _integer(item, "settlement_attempt_count")
            history_count = _integer(item, "history_attempt_count")
            settlement_attempt_counts = (
                ((first_session_id, settlement_count),) if settlement_count else ()
            )
            history_attempt_counts = ((first_session_id, history_count),) if history_count else ()
        else:
            settlement_attempt_counts = _attempt_counts(item, "settlement_attempt_counts")
            history_attempt_counts = _attempt_counts(item, "history_attempt_counts")
        expected = {
            "schema_version",
            "started_at",
            "updated_at",
            "restart_count",
            "recovered_case_count",
            "attempted_decision_window_ids",
            "active_session_id",
            "preflight_attempt_count",
            "preflight_complete",
            "settlement_attempt_counts",
            "history_attempt_counts",
            "case_attempted_at",
            "status",
            "last_error",
        }
        if schema_version == RUNTIME_SCHEMA_VERSION and set(item) != expected:
            raise ValueError("runtime progress has foreign fields")
        case_attempted_at = item.get("case_attempted_at")
        if not isinstance(case_attempted_at, dict) or not all(
            isinstance(case_id, str) and isinstance(at, str)
            for case_id, at in case_attempted_at.items()
        ):
            raise ValueError("case_attempted_at must map Case identities to ISO datetimes")
        return cls(
            started_at=_datetime(item, "started_at"),
            updated_at=_datetime(item, "updated_at"),
            restart_count=_integer(item, "restart_count"),
            recovered_case_count=_integer(item, "recovered_case_count"),
            attempted_decision_window_ids=tuple(attempted),
            active_session_id=(
                _text(item, "active_session_id")
                if schema_version == RUNTIME_SCHEMA_VERSION
                else active_session_id
            ),
            preflight_attempt_count=_integer(item, "preflight_attempt_count"),
            preflight_complete=_boolean(item, "preflight_complete"),
            settlement_attempt_counts=settlement_attempt_counts,
            history_attempt_counts=history_attempt_counts,
            case_attempted_at=tuple(
                sorted(
                    (
                        case_id,
                        _utc(datetime.fromisoformat(at.replace("Z", "+00:00"))),
                    )
                    for case_id, at in case_attempted_at.items()
                )
            ),
            status=_text(item, "status"),
            last_error=last_error,
        )


class StableRuntimeRoot:
    """One manifest-bound local root with a process-exclusive lock."""

    def __init__(
        self,
        *,
        root: Path,
        policy: BtcShortVolPolicy,
        session: DeribitSession,
        now: datetime,
        resume_existing_session: bool = False,
    ) -> None:
        requested_root = root.expanduser()
        if not requested_root.is_absolute():
            requested_root = Path.cwd() / requested_root
        if _path_has_symlink(requested_root):
            raise ValueError("stable runtime root and its parents must not be symbolic links")
        self.root = requested_root.resolve()
        self.policy = policy
        self.session = session
        self.now = _utc(now)
        self.resume_existing_session = resume_existing_session
        self.manifest_path = self.root / "manifest.json"
        self.state_path = self.root / "runtime-state.json"
        self.lock_path = self.root / "runtime-lock"
        self._lock_handle: object | None = None

    @property
    def implementation_id(self) -> str:
        return canonical_identity(
            "B3PublicShadowRuntimeV1",
            self.policy.identity,
            self.policy.channel_id,
            "SINGLE_PROCESS",
            "PUBLIC_DERIBIT_PRODUCTION",
        )

    def acquire(self) -> RuntimeManifest:
        self.root.mkdir(parents=True, exist_ok=True)
        flags = os.O_CREAT | os.O_RDWR
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        lock_fd = os.open(self.lock_path, flags, 0o600)
        lock_handle = os.fdopen(lock_fd, "r+", encoding="utf-8")
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            lock_handle.close()
            raise RuntimeError("stable runtime root is already owned by another process") from exc
        self._lock_handle = lock_handle
        try:
            for name in _RUNTIME_TEMP_MEMBERS:
                temporary = self.root / name
                if temporary.is_symlink() or (temporary.exists() and not temporary.is_file()):
                    raise ValueError("stable runtime root contains a foreign temporary member")
                if temporary.exists():
                    temporary.unlink()
            unknown = {path.name for path in self.root.iterdir()} - _RUNTIME_ALLOWED_ROOT_MEMBERS
            if unknown:
                raise ValueError(f"stable runtime root contains foreign members: {sorted(unknown)}")
            for name in _RUNTIME_FILE_MEMBERS:
                member = self.root / name
                if member.is_symlink() or (member.exists() and not member.is_file()):
                    raise ValueError(f"stable runtime root member has a foreign type: {name}")
            for name in _RUNTIME_DIRECTORY_MEMBERS:
                member = self.root / name
                if member.is_symlink() or (member.exists() and not member.is_dir()):
                    raise ValueError(f"stable runtime root member has a foreign type: {name}")
            workbench = self.root / "workbench"
            if workbench.exists():
                workbench_unknown = (
                    {path.name for path in workbench.iterdir()}
                    - _WORKBENCH_ALLOWED_MEMBERS
                    - _WORKBENCH_TEMP_MEMBERS
                )
                if workbench_unknown:
                    raise ValueError(
                        "stable runtime Workbench contains foreign members: "
                        f"{sorted(workbench_unknown)}"
                    )
                for path in workbench.iterdir():
                    if path.is_symlink() or not path.is_file():
                        raise ValueError(
                            f"stable runtime Workbench member has a foreign type: {path.name}"
                        )
                for name in _WORKBENCH_TEMP_MEMBERS:
                    temporary = workbench / name
                    if temporary.exists():
                        temporary.unlink()
            existing_without_lock = tuple(
                path for path in self.root.iterdir() if path != self.lock_path
            )
            if not self.manifest_path.exists() and existing_without_lock:
                raise ValueError("non-empty stable runtime root lacks its Optimatrix manifest")
            expected = RuntimeManifest(
                implementation_id=self.implementation_id,
                policy_id=self.policy.identity,
                channel_id=self.policy.channel_id.value,
                target_session_id=self.session.session_id,
                session_start=self.session.start,
                session_end=self.session.end,
                created_at=self.now,
            )
            if self.manifest_path.exists():
                manifest = RuntimeManifest.from_object(_read_json(self.manifest_path))
                stable_implementation = (
                    manifest.implementation_id == expected.implementation_id
                    and manifest.policy_id == expected.policy_id
                    and manifest.channel_id == expected.channel_id
                )
                stable_session = self.resume_existing_session or (
                    manifest.target_session_id == expected.target_session_id
                    and manifest.session_start == expected.session_start
                    and manifest.session_end == expected.session_end
                )
                if not stable_implementation or not stable_session:
                    raise ValueError(
                        "stable runtime root belongs to another implementation or Session"
                    )
                return manifest
            _atomic_json(self.manifest_path, expected.as_object())
            return expected
        except BaseException:
            self.release()
            raise

    def release(self) -> None:
        if self._lock_handle is None:
            return
        handle = self._lock_handle
        self._lock_handle = None
        assert hasattr(handle, "fileno") and hasattr(handle, "close")
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


class BtcPublicShadowRuntime:
    """One continuous process driving the current BTC Session and all accepted Cases."""

    def __init__(
        self,
        *,
        root: Path,
        policy: BtcShortVolPolicy,
        source: BtcPublicRuntimeSource,
        event_state: EventState,
        now: datetime | None = None,
        target_session: DeribitSession | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        requested_root = Path(os.path.abspath(os.fspath(root.expanduser())))
        self._authorized_runtime_root = requested_root == AUTHORIZED_RUNTIME_ROOT
        if self._authorized_runtime_root:
            if now is not None or target_session is not None:
                raise ValueError("authorized runtime root requires the Deribit UTC clock")
            if policy.identity != AUTHORIZED_RUNTIME_POLICY_IDENTITY:
                raise ValueError("authorized runtime root requires the authorized frozen Policy")
            if event_state is not EventState.NONE:
                raise ValueError("authorized runtime root requires the NONE event state")
            if type(source) is not DeribitPublicRuntimeSource:
                raise ValueError("authorized runtime root requires the production public source")
        self.policy = policy
        self.source = source
        self.event_state = event_state
        self.sleep = sleep
        self._uses_deribit_clock = now is None
        startup_preflight: PublicClockPreflight | None = None
        startup_preflight_attempt_count = 0
        if now is None:
            startup_preflight, startup_preflight_attempt_count = self._establish_startup_clock()
            boundary = _unambiguous_clock_boundary(
                startup_preflight.clock_reading,
                policy=policy,
            )
        else:
            boundary = _utc(now)
        self._fixed_session = target_session is not None
        self._audit_lock = Lock()
        self._last_audit_at: datetime | None = None
        self._business_time_floor = boundary
        candidate_session = target_session or current_deribit_session(
            boundary,
            phase_policy=policy.session,
        )
        self.root_owner = StableRuntimeRoot(
            root=root,
            policy=policy,
            session=candidate_session,
            now=boundary,
            resume_existing_session=target_session is None,
        )
        self.manifest = self.root_owner.acquire()
        try:
            first_enrollment_session = _manifest_session(self.manifest, policy)
            self.engine = Btc0DteShortVolEngine(policy=policy)
            active_session = current_deribit_session(
                boundary,
                phase_policy=policy.session,
            )
            self.session = (
                first_enrollment_session
                if self._fixed_session
                else current_deribit_session(
                    active_session.start,
                    phase_policy=policy.session,
                )
            )
            self._sessions: dict[str, DeribitSession] = {}
            self._windows_by_session: dict[str, tuple[DecisionWindow, ...]] = {}
            self._register_sessions(first_enrollment_session, self.session)
            self.windows = self._windows_by_session[self.session.session_id]
            self.ledger = ObservationLedger(self.root_owner.root)
            self.journal = CaseJournal(self.root_owner.root)
            recovered_records, recovered_outcomes = self.ledger.recover()
            self._validate_ledger_population(recovered_records, recovered_outcomes)
            self._recover_audit()
            recoverable_empty_case_ids = frozenset(
                open_trade_case(record, self.policy).identity
                for record in recovered_records
                if record.result is DecisionResult.CANDIDATE
            )
            recovered = self.journal.recover_all(
                recoverable_empty_case_ids=recoverable_empty_case_ids
            )
            self.cases = {case.identity: case for case in recovered}
            self.pending_observations: dict[str, PublicSnapshotEvaluation] = {}
            self.latest_snapshot = self._read_latest_snapshot(boundary)
            self.settlement_facts = self._read_settlements()
            self.history_captures = self._read_history_captures()
            recovered_unresolved = sum(case.outcome is None for case in recovered)
            self.progress = self._start_progress(boundary, recovered_unresolved)
            durable_floor = max(
                self.progress.updated_at,
                self._last_audit_at or self.progress.updated_at,
            )
            self._business_time_floor = max(self._business_time_floor, durable_floor)
            if startup_preflight is not None:
                if startup_preflight.clock_reading.latest_at < self._business_time_floor:
                    raise DeribitSourceError(
                        "Deribit UTC preflight is behind durable runtime business time"
                    )
                self.progress = replace(
                    self.progress,
                    preflight_attempt_count=startup_preflight_attempt_count,
                    preflight_complete=True,
                    updated_at=max(startup_preflight.known_at, self._business_time_floor),
                    status="PREFLIGHT_COMPLETE",
                    last_error=None,
                )
            self._validate_durable_population()
            self._validate_progress()
            self._write_progress(self.progress)
            bind_audit = getattr(self.source, "bind_audit", None)
            if callable(bind_audit):
                bind_audit(self._audit_public_call)
            if startup_preflight is not None:
                self._audit(
                    "DERIBIT_PUBLIC_CALL",
                    startup_preflight.known_at,
                    json.dumps(
                        {
                            "method": "public/get_time",
                            "params": {},
                            "timeout_seconds": 10.0,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                )
                self._audit(
                    "PUBLIC_PREFLIGHT_COMPLETE",
                    startup_preflight.known_at,
                    "Deribit UTC clock established before stable-root ownership",
                )
            self._reconcile_candidate_cases(boundary)
            self._reconcile_inflight_gaps(boundary)
            self._reconcile_expired_entries(boundary)
            self._reconcile_monitoring_gaps(boundary)
            for session in self._sessions.values():
                self._reconcile_settlement(session, boundary)
            self._validate_durable_population()
            startup_known_at = (
                startup_preflight.known_at if startup_preflight is not None else boundary
            )
            self._audit(
                "RUNTIME_STARTED",
                startup_known_at,
                f"restart_count={self.progress.restart_count}",
            )
            self.publish(startup_known_at)
        except BaseException:
            self.root_owner.release()
            raise

    def __enter__(self) -> BtcPublicShadowRuntime:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @property
    def settlement_fact(self) -> ExpirySettlementFact | None:
        return self.settlement_facts.get(self.session.session_id)

    @property
    def history_capture(self) -> IndexHistoryCapture | None:
        return self.history_captures.get(self.session.session_id)

    @property
    def finalization_at(self) -> datetime:
        return self._session_finalization_at(self.session)

    @property
    def complete(self) -> bool:
        decisions = self.ledger.summarize(expected_windows=self.windows)
        outcomes = self.ledger.summarize_outcomes(expected_windows=self.windows)
        return (
            decisions.complete
            and outcomes.complete
            and self.settlement_fact is not None
            and all(
                case.outcome is not None
                for case in self.cases.values()
                if self._case_session(case).session_id == self.session.session_id
            )
        )

    def tick(self, now: datetime | None = None) -> None:
        try:
            reading = self._tick_clock_reading(now)
        except DeribitSourceError as initial_error:
            try:
                reading = self._reanchor_clock(initial_error)
            except DeribitSourceError as exc:
                boundary = self._business_time_floor
                detail = _safe_error(exc)
                self._set_status("CLOCK_UNVERIFIED", boundary, detail)
                self._audit("DERIBIT_CLOCK_UNVERIFIED", boundary, detail)
                self.publish(boundary)
                raise RuntimeError(
                    "bounded Deribit clock re-anchor failed; runtime stopped"
                ) from exc
        if self._clock_reading_is_ambiguous(reading):
            self._set_status(
                "CLOCK_BOUNDARY_UNCERTAIN",
                reading.earliest_at,
                "Deribit UTC uncertainty crosses a Session or DecisionWindow boundary",
            )
            self.publish(reading.earliest_at)
            return
        boundary = reading.earliest_at
        if boundary < self.session.start - PREFLIGHT_LEAD:
            self._set_status("WAITING_FOR_PREFLIGHT", boundary)
            self.publish(boundary)
            return
        if not self.progress.preflight_complete:
            self._run_preflight(boundary)
        if boundary < self.session.start:
            self._set_status("WAITING_FOR_SESSION", boundary)
            self.publish(boundary)
            return

        if not self._fixed_session and boundary >= self.session.end:
            self._roll_session(boundary)

        self._finalize_due_windows(boundary)
        self._reconcile_candidate_cases(boundary)
        self._reconcile_expired_entries(boundary)
        self._reconcile_monitoring_gaps(boundary)
        current_window = next(
            (window for window in self.windows if window.starts_at <= boundary < window.ends_at),
            None,
        )
        due_cases = self._due_cases(boundary)
        decision_due = (
            current_window is not None
            and current_window.identity not in self.progress.attempted_decision_window_ids
            and current_window.identity
            not in {record.window.identity for record in self.ledger.read()}
        )
        evaluation: PublicSnapshotEvaluation | None = None
        effective_known_at = boundary
        if current_window is not None and (decision_due or due_cases):
            required = self._required_instruments(due_cases)
            if decision_due:
                self._mark_window_attempted(current_window.identity, boundary)
            evaluation = self._capture(
                now=boundary,
                window=current_window,
                required_instrument_names=required,
                attempted_cases=due_cases,
            )
            if evaluation is not None:
                self.latest_snapshot = evaluation.as_object()
                effective_known_at = max(effective_known_at, evaluation.observation.known_at)
                self._reconcile_monitoring_gaps(effective_known_at)
                if decision_due:
                    self.pending_observations[current_window.identity] = evaluation
        if due_cases:
            self._advance_cases(due_cases, evaluation, boundary)
        self._finalize_due_windows(boundary)
        self._reconcile_candidate_cases(boundary)
        effective_known_at = max(
            effective_known_at,
            self._process_expired_sessions(boundary),
        )
        if self._fixed_session and self.complete:
            self._set_status("COMPLETE_PENDING_TRADER_ACCEPTANCE", effective_known_at)
        elif self.progress.status not in {
            "MARKET_GAP",
            "RECOVERY_GAP",
            "SETTLEMENT_UNVERIFIED",
            "FUTURE_PATH_UNVERIFIED",
        }:
            self._set_status("RUNNING", effective_known_at)
        self.publish(effective_known_at)

    def run_forever(self, *, port: int) -> int:
        if self._authorized_runtime_root and port != AUTHORIZED_WORKBENCH_PORT:
            raise ValueError("authorized runtime root requires the authorized Workbench port")
        server = _WorkbenchServer(self.root_owner.root / "workbench", port)
        server.start()
        boundary = self._current_clock_boundary()
        self._audit("WORKBENCH_LISTENING", boundary, f"http://127.0.0.1:{port}/")
        try:
            while True:
                self.tick()
                self.sleep(1.0)
        except KeyboardInterrupt:
            boundary = self._current_clock_boundary()
            self._set_status("STOPPED_FOR_RESTART", boundary)
            self.publish(boundary)
            return 0
        finally:
            server.stop()
            self.close()

    def publish(self, now: datetime) -> None:
        boundary = max(_utc(now), self.progress.updated_at)
        decisions = self.ledger.summarize(expected_windows=self.windows).as_object()
        outcomes = self.ledger.summarize_outcomes(expected_windows=self.windows).as_object()
        current_window = next(
            (window for window in self.windows if window.starts_at <= boundary < window.ends_at),
            None,
        )
        runtime_state = {
            "status": self.progress.status,
            "session_id": self.session.session_id,
            "session_start": _iso(self.session.start),
            "session_end": _iso(self.session.end),
            "started_at": _iso(self.progress.started_at),
            "updated_at": _iso(boundary),
            "recovered_case_count": self.progress.recovered_case_count,
            "restart_count": self.progress.restart_count,
            "current_window_id": current_window.identity if current_window is not None else None,
            "attempted_window_count": len(
                set(self.progress.attempted_decision_window_ids)
                & {window.identity for window in self.windows}
            ),
            "last_error": self.progress.last_error,
        }
        write_workbench(
            self.latest_snapshot,
            self.root_owner.root / "workbench",
            runtime_state=runtime_state,
            ledger_population={"decisions": decisions, "outcomes": outcomes},
            recovered_cases=tuple(sorted(self.cases.values(), key=lambda case: case.identity)),
        )
        _atomic_json(self.root_owner.root / "latest-snapshot.json", self.latest_snapshot)

    def close(self) -> None:
        self.root_owner.release()

    def _establish_startup_clock(self) -> tuple[PublicClockPreflight, int]:
        """Calibrate Deribit UTC before the stable root can be touched."""

        error: DeribitSourceError | None = None
        for attempt in range(1, 4):
            try:
                result = self.source.preflight()
            except DeribitSourceError as exc:
                error = exc
                if attempt < 3:
                    self.sleep(float(2 ** (attempt - 1)))
                continue
            if not isinstance(result, PublicClockPreflight):
                raise DeribitSourceError(
                    "production startup requires a validated Deribit clock preflight"
                )
            projected = self.source.clock_reading()
            if not isinstance(projected, DeribitClockReading):
                raise DeribitSourceError(
                    "production startup requires a projected Deribit clock reading"
                )
            return (
                replace(
                    result,
                    clock_reading=projected,
                    known_at=projected.latest_at,
                ),
                attempt,
            )
        detail = str(error) if error is not None else "Deribit clock preflight failed"
        raise DeribitSourceError(
            f"bounded Deribit clock preflight exhausted three attempts: {detail}"
        )

    def _tick_clock_reading(self, now: datetime | None) -> DeribitClockReading:
        if now is not None:
            if self._uses_deribit_clock:
                raise ValueError("production runtime time cannot be overridden by host wall time")
            boundary = _utc(now)
            return DeribitClockReading(
                earliest_at=boundary,
                estimate_at=boundary,
                latest_at=boundary,
                monotonic_ns=0,
            )
        if not self._uses_deribit_clock:
            boundary = self.progress.updated_at
            return DeribitClockReading(
                earliest_at=boundary,
                estimate_at=boundary,
                latest_at=boundary,
                monotonic_ns=0,
            )
        reading = self.source.clock_reading()
        if not isinstance(reading, DeribitClockReading):
            raise DeribitSourceError("runtime source returned a foreign Deribit clock reading")
        if reading.latest_at < self._business_time_floor:
            raise DeribitSourceError(
                "Deribit UTC reading is behind the committed runtime business boundary"
            )
        earliest_at = max(reading.earliest_at, self._business_time_floor)
        normalized = DeribitClockReading(
            earliest_at=earliest_at,
            estimate_at=max(earliest_at, reading.estimate_at),
            latest_at=reading.latest_at,
            monotonic_ns=reading.monotonic_ns,
        )
        self._business_time_floor = normalized.earliest_at
        return normalized

    def _reanchor_clock(self, initial_error: DeribitSourceError) -> DeribitClockReading:
        if not self._uses_deribit_clock:
            raise initial_error
        error = initial_error
        for attempt in range(1, 4):
            try:
                result = self.source.preflight()
                if not isinstance(result, PublicClockPreflight):
                    raise DeribitSourceError(
                        "runtime clock re-anchor requires a validated Deribit preflight"
                    )
                reading = self._tick_clock_reading(None)
            except DeribitSourceError as exc:
                error = exc
                self._audit(
                    "DERIBIT_CLOCK_REANCHOR_ATTEMPT_FAILED",
                    self._business_time_floor,
                    f"attempt={attempt}:{_safe_error(exc)}",
                )
                if attempt < 3:
                    self.sleep(float(2 ** (attempt - 1)))
                continue
            self._audit(
                "DERIBIT_CLOCK_REANCHORED",
                reading.latest_at,
                f"attempt={attempt}:initial={_safe_error(initial_error)}",
            )
            return reading
        raise error

    def _current_clock_boundary(self) -> datetime:
        try:
            return self._tick_clock_reading(None).earliest_at
        except DeribitSourceError:
            return self._business_time_floor

    def _clock_reading_is_ambiguous(self, reading: DeribitClockReading) -> bool:
        return _clock_scope(reading.earliest_at, self.policy) != _clock_scope(
            reading.latest_at,
            self.policy,
        )

    def _roll_session(self, now: datetime) -> None:
        next_session = current_deribit_session(now, phase_policy=self.policy.session)
        if next_session.session_id == self.session.session_id:
            return
        prior_session = self.session
        self._register_sessions(prior_session, next_session)
        self.session = next_session
        self.windows = self._windows_by_session[next_session.session_id]
        self.latest_snapshot = _waiting_snapshot(next_session, now)
        self.progress = replace(
            self.progress,
            active_session_id=next_session.session_id,
            updated_at=now,
            status="SESSION_ROLLED",
            last_error=None,
        )
        self._write_progress(self.progress)
        self._audit(
            "SESSION_ROLLED",
            now,
            f"prior={prior_session.session_id}:current={next_session.session_id}",
            session=next_session,
        )

    def _register_sessions(
        self,
        first: DeribitSession,
        last: DeribitSession,
    ) -> None:
        if last.end < first.end:
            raise ValueError("active Session cannot precede first runtime enrollment")
        cursor = first
        while cursor.end <= last.end:
            if cursor.session_id not in self._sessions:
                windows = self.engine.decision_windows(at=cursor.start)
                if (
                    len(windows) != 96
                    or tuple(window.market_session_id for window in windows)
                    != (cursor.session_id,) * 96
                ):
                    raise ValueError(
                        "runtime Session does not produce the expected 96 calendar Windows"
                    )
                self._sessions[cursor.session_id] = cursor
                self._windows_by_session[cursor.session_id] = windows
            if cursor.session_id == last.session_id:
                return
            cursor = current_deribit_session(
                cursor.end,
                phase_policy=self.policy.session,
            )
        raise ValueError("active Session is not reachable from first runtime enrollment")

    def _window_index(self) -> dict[str, DecisionWindow]:
        return {
            window.identity: window
            for windows in self._windows_by_session.values()
            for window in windows
        }

    def _session_for_window(self, window: DecisionWindow) -> DeribitSession:
        session = self._sessions.get(window.market_session_id)
        if session is None:
            raise ValueError("DecisionWindow belongs to an unenrolled runtime Session")
        return session

    def _case_session(self, case: TradeCase) -> DeribitSession:
        allocation = case.risk_allocation
        session_id = _text(allocation, "market_session_id")
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError("TradeCase belongs to an unenrolled runtime Session")
        return session

    def _session_finalization_at(self, session: DeribitSession) -> datetime:
        return max(
            self._outcome_horizon(window, session)[1]
            for window in self._windows_by_session[session.session_id]
        )

    def _start_progress(self, now: datetime, recovered_count: int) -> RuntimeProgress:
        if not self.root_owner.state_path.exists():
            return RuntimeProgress(
                started_at=now,
                updated_at=now,
                restart_count=0,
                recovered_case_count=recovered_count,
                attempted_decision_window_ids=(),
                active_session_id=self.session.session_id,
                preflight_attempt_count=0,
                preflight_complete=False,
                settlement_attempt_counts=(),
                history_attempt_counts=(),
                case_attempted_at=(),
                status="STARTING",
                last_error=None,
            )
        prior = RuntimeProgress.from_object(
            _read_json(self.root_owner.state_path),
            first_session_id=self.manifest.target_session_id,
            active_session_id=self.session.session_id,
        )
        if prior.active_session_id not in self._sessions:
            raise ValueError("runtime progress contains a foreign active Session")
        return replace(
            prior,
            active_session_id=self.session.session_id,
            updated_at=max(prior.updated_at, now),
            restart_count=prior.restart_count + 1,
            recovered_case_count=recovered_count,
            status="RECOVERED",
            last_error=None,
        )

    def _write_progress(self, progress: RuntimeProgress) -> None:
        if hasattr(self, "progress") and progress.updated_at < self.progress.updated_at:
            progress = replace(progress, updated_at=self.progress.updated_at)
        self.progress = progress
        _atomic_json(self.root_owner.state_path, progress.as_object())

    def _set_status(self, status: str, now: datetime, error: str | None = None) -> None:
        if self.progress.status == status and self.progress.last_error == error:
            return
        self._write_progress(
            replace(self.progress, status=status, updated_at=now, last_error=error)
        )

    def _run_preflight(self, now: datetime) -> None:
        error: DeribitSourceError | None = None
        while self.progress.preflight_attempt_count < 3:
            attempt = self.progress.preflight_attempt_count + 1
            self._write_progress(
                replace(
                    self.progress,
                    preflight_attempt_count=attempt,
                    updated_at=now,
                )
            )
            try:
                completed = self.source.preflight(local_now=now)
            except DeribitSourceError as exc:
                error = exc
                self._audit(
                    "PUBLIC_PREFLIGHT_ATTEMPT_FAILED",
                    now,
                    f"attempt={attempt}:{_safe_error(exc)}",
                )
                if attempt < 3:
                    self.sleep(float(2 ** (attempt - 1)))
                continue
            effective_known_at = (
                _utc(completed) if isinstance(completed, datetime) else _utc(completed.known_at)
            )
            self._write_progress(
                replace(
                    self.progress,
                    preflight_complete=True,
                    status="PREFLIGHT_COMPLETE",
                    updated_at=effective_known_at,
                    last_error=None,
                )
            )
            self._audit(
                "PUBLIC_PREFLIGHT_COMPLETE",
                effective_known_at,
                "production clock verified",
            )
            return
        detail = str(error) if error is not None else "preflight interrupted before completion"
        self._set_status("PREFLIGHT_FAILED", now, detail)
        self.publish(now)
        raise RuntimeError("the bounded public preflight exhausted its three total attempts")

    def _mark_window_attempted(self, window_id: str, now: datetime) -> None:
        attempted = tuple((*self.progress.attempted_decision_window_ids, window_id))
        self._write_progress(
            replace(
                self.progress,
                attempted_decision_window_ids=attempted,
                updated_at=now,
            )
        )

    def _mark_cases_attempted(self, cases: Sequence[TradeCase], now: datetime) -> None:
        attempted = dict(self.progress.case_attempted_at)
        for case in cases:
            attempted[case.identity] = now
        self._write_progress(
            replace(
                self.progress,
                case_attempted_at=tuple(sorted(attempted.items())),
                updated_at=now,
            )
        )

    def _capture(
        self,
        *,
        now: datetime,
        window: DecisionWindow,
        required_instrument_names: tuple[str, ...],
        attempted_cases: Sequence[TradeCase],
    ) -> PublicSnapshotEvaluation | None:
        self._mark_cases_attempted(attempted_cases, now)
        try:
            evaluation = self._retry(
                "PUBLIC_MARKET_CUT",
                lambda: self.source.snapshot(
                    now=now,
                    target_window=window,
                    required_instrument_names=required_instrument_names,
                ),
                now,
            )
            completed_at = evaluation.observation.known_at
            self._audit(
                "PUBLIC_MARKET_CUT_COMPLETE",
                completed_at,
                f"observation={evaluation.observation.identity}",
            )
            self._set_status("RUNNING", completed_at)
            return evaluation
        except DeribitSourceError as exc:
            self._set_status("MARKET_GAP", now, str(exc))
            self._audit("PUBLIC_MARKET_GAP", now, _safe_error(exc))
            self.latest_snapshot = _gap_snapshot(
                self._session_for_window(window),
                window,
                now,
                _safe_error(exc),
            )
            return None

    def _retry[T](self, label: str, operation: Callable[[], T], now: datetime) -> T:
        error: DeribitSourceError | None = None
        for attempt in range(1, 4):
            try:
                return operation()
            except DeribitSourceError as exc:
                error = exc
                self._audit(f"{label}_ATTEMPT_FAILED", now, f"attempt={attempt}:{_safe_error(exc)}")
                if attempt < 3:
                    self.sleep(float(2 ** (attempt - 1)))
        assert error is not None
        raise error

    def _finalize_due_windows(self, now: datetime) -> None:
        recorded = {record.window.identity for record in self.ledger.read()}
        attempted = set(self.progress.attempted_decision_window_ids)
        for window in sorted(self._window_index().values(), key=lambda item: item.starts_at):
            if (
                window.identity in recorded
                or window.identity not in attempted
                or now < window.input_deadline
            ):
                continue
            evaluation = self.pending_observations.pop(window.identity, None)
            finalization_cadence = timedelta(
                seconds=self.policy.lifecycle.monitoring_cadence_seconds
            )
            if now > window.input_deadline + finalization_cadence:
                evaluation = None
                self._audit(
                    "DECISION_FINALIZATION_CADENCE_MISSED",
                    now,
                    f"window={window.identity}",
                    session=self._session_for_window(window),
                )
            capacity = self._capacity(window, window.input_deadline)
            assessment = self.engine.assess_window(
                ledger=self.ledger,
                window=window,
                observation=evaluation.observation if evaluation is not None else None,
                capacity=capacity,
                known_at=now,
            )
            recorded.add(window.identity)
            if evaluation is not None:
                snapshot_window = _mapping(self.latest_snapshot.get("window"), "snapshot.window")
                if snapshot_window.get("decision_window_id") == window.identity:
                    snapshot_window["ledger_state"] = f"RECORDED:{assessment.record.result.value}"
            self._audit(
                "DECISION_WINDOW_RECORDED",
                now,
                f"window={window.identity}:result={assessment.record.result.value}",
                session=self._session_for_window(window),
            )
            if assessment.record.result is DecisionResult.CANDIDATE:
                self._open_candidate_case(assessment.record, now)

    def _capacity(self, window: DecisionWindow, known_at: datetime) -> ShadowCapacity:
        used = Decimal(0)
        open_positions = 0
        for case in self.cases.values():
            if case.outcome is not None:
                continue
            allocation = case.risk_allocation
            if allocation.get("market_session_id") != window.market_session_id:
                continue
            used += Decimal(str(allocation["maximum_contractual_payoff_usd"]))
            if case.position_id is not None and case.position_state is not PositionState.TERMINAL:
                open_positions += 1
        return ShadowCapacity(
            channel_id=self.policy.channel_id,
            market_session_id=window.market_session_id,
            contractual_payoff_used_usd=used,
            open_position_count=open_positions,
            known_at=known_at,
        )

    def _due_cases(self, now: datetime) -> tuple[TradeCase, ...]:
        due: list[TradeCase] = []
        cadence = timedelta(seconds=self.policy.lifecycle.monitoring_cadence_seconds)
        attempts = dict(self.progress.case_attempted_at)
        for case in self.cases.values():
            if case.outcome is not None:
                continue
            case_session = self._case_session(case)
            if case_session.session_id != self.session.session_id or now >= case_session.end:
                continue
            last = case.last_observed_at or case.decision_boundary
            if case.identity in attempts:
                last = max(last, attempts[case.identity])
            if now >= last + cadence or (not case.entry_final and now >= case.entry_deadline):
                due.append(case)
        return tuple(sorted(due, key=lambda case: case.identity))

    def _reconcile_monitoring_gaps(self, now: datetime) -> None:
        cadence = timedelta(seconds=self.policy.lifecycle.monitoring_cadence_seconds)
        attempts = dict(self.progress.case_attempted_at)
        for case_id, case in tuple(self.cases.items()):
            if case.outcome is not None:
                continue
            case_session = self._case_session(case)
            gap_boundary = min(now, case_session.end)
            boundary = max(
                case.last_observed_at or case.decision_boundary,
                attempts.get(case_id, case.decision_boundary),
            )
            if gap_boundary <= boundary + cadence * 2 or case.gap_observed:
                continue
            gapped = replace(case, gap_observed=True)
            self.journal.append(gapped)
            self.cases[case_id] = gapped
            self._audit(
                "LIFECYCLE_CADENCE_GAP",
                now,
                f"case={case_id}",
                session=case_session,
            )

    def _reconcile_inflight_gaps(self, now: datetime) -> None:
        recorded = {record.window.identity for record in self.ledger.read()}
        current_window = next(
            (window for window in self.windows if window.starts_at <= now < window.ends_at),
            None,
        )
        recovery_details: list[str] = []
        if (
            current_window is not None
            and current_window.identity in self.progress.attempted_decision_window_ids
            and current_window.identity not in recorded
        ):
            self.latest_snapshot = _gap_snapshot(
                self.session,
                current_window,
                now,
                "RESTART_INTERRUPTED_WINDOW_ATTEMPT",
            )
            recovery_details.append(f"window={current_window.identity}")

        attempts = dict(self.progress.case_attempted_at)
        for case_id, case in tuple(self.cases.items()):
            attempted_at = attempts.get(case_id)
            accepted_at = case.last_observed_at or case.decision_boundary
            if (
                attempted_at is None
                or attempted_at <= accepted_at
                or case.outcome is not None
                or case.gap_observed
            ):
                continue
            gapped = replace(case, gap_observed=True)
            self.journal.append(gapped)
            self.cases[case_id] = gapped
            recovery_details.append(f"case={case_id}")

        if recovery_details:
            detail = "RESTART_INTERRUPTED_CAUSAL_CUT:" + ",".join(recovery_details)
            self._set_status("RECOVERY_GAP", now, detail)
            self._audit("RESTART_CAUSAL_GAP", now, detail)

    def _reconcile_expired_entries(self, now: datetime) -> None:
        for case_id, case in tuple(self.cases.items()):
            case_session = self._case_session(case)
            if case.entry_final or now < case_session.end:
                continue
            if not case.gap_observed:
                case = replace(case, gap_observed=True)
                self.journal.append(case)
                self.cases[case_id] = case
            known_at = max(now, case.entry_deadline)
            terminal, _evaluation = self.engine.evaluate_entry(
                journal=self.journal,
                case=case,
                observation=None,
                known_at=known_at,
            )
            self.cases[case_id] = terminal
            self._audit(
                "EXPIRED_ENTRY_TERMINALIZED",
                known_at,
                f"case={case_id}",
                session=case_session,
            )

    def _required_instruments(self, cases: Sequence[TradeCase]) -> tuple[str, ...]:
        names: set[str] = set()
        for case in cases:
            legs = _mapping(case.selected_structure.get("legs"), "selected structure legs")
            for member in legs.values():
                names.add(_text(_mapping(member, "selected structure leg"), "instrument_name"))
        return tuple(sorted(names))

    def _advance_cases(
        self,
        cases: Sequence[TradeCase],
        evaluation: PublicSnapshotEvaluation | None,
        now: datetime,
    ) -> None:
        observation = evaluation.observation if evaluation is not None else None
        for prior in cases:
            case = self.cases[prior.identity]
            case_session = self._case_session(case)
            if case.outcome is not None:
                continue
            if observation is not None and any(
                quote.expiry != case_session.end for quote in observation.quotes
            ):
                raise ValueError("market cut expiry does not match the frozen TradeCase Session")
            if observation is None and not case.gap_observed:
                case = replace(case, gap_observed=True)
                self.journal.append(case)
                self.cases[case.identity] = case
            last_observed_at = case.last_observed_at or case.entry_observed_at
            if (
                observation is not None
                and last_observed_at is not None
                and observation.observed_at <= last_observed_at
            ):
                if not case.gap_observed:
                    case = replace(case, gap_observed=True)
                    self.journal.append(case)
                    self.cases[case.identity] = case
                self._audit(
                    "LIFECYCLE_MARKET_BOUNDARY_NOT_ADVANCING",
                    observation.known_at,
                    f"case={case.identity}",
                    session=case_session,
                )
                continue
            if not case.entry_final:
                evaluation_known_at = (
                    max(now, observation.known_at) if observation is not None else now
                )
                if observation is None and evaluation_known_at < case.entry_deadline:
                    continue
                updated, _entry = self.engine.evaluate_entry(
                    journal=self.journal,
                    case=case,
                    observation=observation,
                    known_at=evaluation_known_at,
                )
            elif case.position_id is not None:
                if observation is None:
                    continue
                elif observation.observed_at >= case_session.end:
                    if not case.gap_observed:
                        case = replace(case, gap_observed=True)
                        self.journal.append(case)
                        self.cases[case.identity] = case
                    continue
                elif case.exit_intent is not None:
                    updated, _exit = self.engine.evaluate_exit(
                        journal=self.journal,
                        case=case,
                        observation=observation,
                    )
                else:
                    updated, _monitor = self.engine.monitor_position(
                        journal=self.journal,
                        case=case,
                        observation=observation,
                    )
            else:
                continue
            self.cases[case.identity] = updated
            self._audit(
                "TRADE_CASE_ADVANCED",
                observation.known_at if observation is not None else now,
                f"case={case.identity}",
                session=case_session,
            )

    def _process_expired_sessions(self, now: datetime) -> datetime:
        effective_known_at = now
        records = self.ledger.read()
        sessions_with_records = {record.window.market_session_id for record in records}
        sessions_with_cases = {
            self._case_session(case).session_id
            for case in self.cases.values()
            if case.outcome is None
        }
        for session in sorted(self._sessions.values(), key=lambda item: item.end):
            if (
                now < session.end + SETTLEMENT_DELAY
                or session.session_id not in sessions_with_records | sessions_with_cases
            ):
                continue
            self._capture_settlement(session, now)
            fact = self.settlement_facts.get(session.session_id)
            if fact is not None:
                effective_known_at = max(effective_known_at, fact.known_at)
            self._reconcile_settlement(session, effective_known_at)
            if now >= self._session_finalization_at(session) and self._settlement_resolved(session):
                self._finalize_outcomes(session, now)
                capture = self.history_captures.get(session.session_id)
                if capture is not None:
                    effective_known_at = max(effective_known_at, capture.known_at)
        return effective_known_at

    def _attempt_count(self, field: str, session: DeribitSession) -> int:
        values = (
            self.progress.settlement_attempt_counts
            if field == "settlement"
            else self.progress.history_attempt_counts
        )
        return dict(values).get(session.session_id, 0)

    def _set_attempt_count(
        self,
        field: str,
        session: DeribitSession,
        count: int,
        now: datetime,
    ) -> None:
        if field == "settlement":
            values = dict(self.progress.settlement_attempt_counts)
            values[session.session_id] = count
            updated = replace(
                self.progress,
                settlement_attempt_counts=tuple(sorted(values.items())),
                updated_at=now,
            )
        else:
            values = dict(self.progress.history_attempt_counts)
            values[session.session_id] = count
            updated = replace(
                self.progress,
                history_attempt_counts=tuple(sorted(values.items())),
                updated_at=now,
            )
        self._write_progress(updated)

    def _capture_settlement(self, session: DeribitSession, now: datetime) -> None:
        if session.session_id in self.settlement_facts:
            return
        attempts_per_boundary = 3
        prior_attempts = self._attempt_count("settlement", session)
        retry_boundary = (
            session.end
            + SETTLEMENT_DELAY
            + timedelta(
                seconds=(prior_attempts // attempts_per_boundary)
                * self.policy.lifecycle.monitoring_cadence_seconds
            )
        )
        if now < retry_boundary:
            return
        error: DeribitSourceError | None = None
        boundary_attempts = 0
        while boundary_attempts < attempts_per_boundary:
            attempt = self._attempt_count("settlement", session) + 1
            self._set_attempt_count("settlement", session, attempt, now)
            boundary_attempts += 1
            try:
                fact = self.source.settlement(expiry=session.end, known_at=now)
            except DeribitSourceError as exc:
                error = exc
                self._audit(
                    "OFFICIAL_SETTLEMENT_ATTEMPT_FAILED",
                    now,
                    f"attempt={attempt}:{_safe_error(exc)}",
                    session=session,
                )
                if boundary_attempts < attempts_per_boundary:
                    self.sleep(float(2 ** (boundary_attempts - 1)))
                continue
            if fact is None:
                error = DeribitSourceError("OFFICIAL_DELIVERY_PRICE_NOT_FOUND")
                self._audit(
                    "OFFICIAL_SETTLEMENT_ATTEMPT_FAILED",
                    now,
                    f"attempt={attempt}:{_safe_error(error)}",
                    session=session,
                )
                if boundary_attempts < attempts_per_boundary:
                    self.sleep(float(2 ** (boundary_attempts - 1)))
                continue
            self._validate_settlement_fact(fact, session)
            self.settlement_facts[session.session_id] = fact
            _append_jsonl(self.root_owner.root / "settlements.jsonl", fact.as_object())
            self._audit(
                "OFFICIAL_SETTLEMENT_RECORDED",
                fact.known_at,
                f"fact={fact.identity}",
                session=session,
            )
            return
        self._set_status(
            "SETTLEMENT_UNVERIFIED",
            now,
            str(error) if error is not None else "settlement interrupted before completion",
        )

    def _reconcile_settlement(self, session: DeribitSession, now: datetime) -> None:
        fact = self.settlement_facts.get(session.session_id)
        if fact is None:
            return
        for case_id, case in tuple(self.cases.items()):
            if (
                self._case_session(case).session_id == session.session_id
                and case.outcome is None
                and case.position_id is not None
            ):
                terminal = self.engine.settle_position(
                    journal=self.journal,
                    case=case,
                    settlement=fact,
                )
                self.cases[case_id] = terminal

    def _settlement_resolved(self, session: DeribitSession) -> bool:
        return session.session_id in self.settlement_facts

    def _finalize_outcomes(self, session: DeribitSession, now: datetime) -> None:
        capture = self.history_captures.get(session.session_id)
        if capture is None:
            error: DeribitSourceError | None = None
            while self._attempt_count("history", session) < 3:
                attempt = self._attempt_count("history", session) + 1
                self._set_attempt_count("history", session, attempt, now)
                try:
                    result = self.source.history(known_at=now)
                except DeribitSourceError as exc:
                    error = exc
                    self._audit(
                        "PUBLIC_FUTURE_PATH_ATTEMPT_FAILED",
                        now,
                        f"attempt={attempt}:{_safe_error(exc)}",
                        session=session,
                    )
                    if attempt < 3:
                        self.sleep(float(2 ** (attempt - 1)))
                    continue
                capture = (
                    result
                    if isinstance(result, IndexHistoryCapture)
                    else IndexHistoryCapture(
                        points=tuple(
                            point for point in result if point[0] <= int(now.timestamp() * 1000)
                        ),
                        known_at=now,
                        error=None,
                    )
                )
                break
            if capture is None:
                detail = (
                    str(error) if error is not None else "history interrupted before completion"
                )
                capture = IndexHistoryCapture(points=None, known_at=now, error=detail)
                self._set_status("FUTURE_PATH_UNVERIFIED", now, detail)
            self.history_captures[session.session_id] = capture
            _append_jsonl(
                self.root_owner.root / "future-index-paths.jsonl",
                capture.as_object(session.session_id),
            )
        history = capture.points or ()
        fact = self.settlement_facts.get(session.session_id)
        known_at = max(capture.known_at, fact.known_at) if fact is not None else capture.known_at
        existing = {outcome.decision_window_id for outcome in self.ledger.read_outcomes()}
        records = {record.window.identity: record for record in self.ledger.read()}
        appended = 0
        for window in self._windows_by_session[session.session_id]:
            record = records.get(window.identity)
            if window.identity in existing or record is None:
                continue
            start, end = self._outcome_horizon(window, session)
            path = (
                summarize_btc_index_path(history, starts_at=start, ends_at=end) if history else None
            )
            path_known = path is not None
            outcome = WindowOutcome(
                decision_window_id=window.identity,
                horizon_starts_at=start,
                horizon_ends_at=end,
                known_at=known_at,
                future_path_known=path_known,
                future_path_continuous=True if path_known else None,
                expiry_settlement=fact,
                future_path=path,
                regime_labels=(("OFFICIAL_DELIVERY_PRICE_UNAVAILABLE",) if fact is None else ()),
                reason=None if path_known else "PUBLIC_INDEX_PATH_INCOMPLETE_OR_UNAVAILABLE",
                eligibility=window_outcome_eligibility(
                    decision_evaluable=record.result is not DecisionResult.UNKNOWN,
                    future_path_known=path_known,
                    future_path_continuous=True if path_known else None,
                ),
            )
            self.ledger.append_outcome(outcome)
            appended += 1
        if appended:
            session_outcomes = {
                item.decision_window_id
                for item in self.ledger.read_outcomes()
                if item.decision_window_id
                in {window.identity for window in self._windows_by_session[session.session_id]}
            }
            self._audit(
                "WINDOW_OUTCOME_POPULATION_RECORDED",
                known_at,
                f"count={len(session_outcomes)}",
                session=session,
            )

    def _outcome_horizon(
        self,
        window: DecisionWindow,
        session: DeribitSession | None = None,
    ) -> tuple[datetime, datetime]:
        owning_session = session or self._session_for_window(window)
        start = window.ends_at
        minimum_end = start + timedelta(minutes=self.policy.window.cadence_minutes)
        return start, max(owning_session.end, minimum_end)

    def _read_settlements(self) -> dict[str, ExpirySettlementFact]:
        facts: dict[str, ExpirySettlementFact] = {}
        legacy = self.root_owner.root / "settlement.json"
        if legacy.exists():
            fact = ExpirySettlementFact.from_object(_read_json(legacy))
            session = self._sessions.get(_iso(fact.expiry))
            if session is None:
                raise ValueError("settlement fact does not match the runtime Session and source")
            self._validate_settlement_fact(fact, session)
            facts[session.session_id] = fact
        path = self.root_owner.root / "settlements.jsonl"
        for value in _read_jsonl(path, field="runtime settlement"):
            fact = ExpirySettlementFact.from_object(value)
            session = self._sessions.get(_iso(fact.expiry))
            if session is None:
                raise ValueError("settlement fact belongs to an unenrolled runtime Session")
            self._validate_settlement_fact(fact, session)
            prior = facts.get(session.session_id)
            if prior is not None and prior != fact:
                raise ValueError("runtime contains conflicting settlement facts")
            facts[session.session_id] = fact
        return facts

    def _validate_settlement_fact(
        self,
        fact: ExpirySettlementFact,
        session: DeribitSession,
    ) -> None:
        if (
            fact.product_id is not BTC.product_id
            or fact.expiry != session.end
            or fact.evidence_kind is not SettlementEvidenceKind.OFFICIAL_EXCHANGE
            or fact.source_id != DERIBIT_DELIVERY_PRICE_SOURCE_ID
            or fact.method_id != DERIBIT_DELIVERY_PRICE_METHOD_ID
        ):
            raise ValueError("settlement fact does not match the runtime Session and source")

    def _read_history_captures(self) -> dict[str, IndexHistoryCapture]:
        captures: dict[str, IndexHistoryCapture] = {}
        legacy = self.root_owner.root / "future-index-path.json"
        if legacy.exists():
            capture = IndexHistoryCapture.from_object(
                _read_json(legacy),
                session_id=self.manifest.target_session_id,
            )
            captures[self.manifest.target_session_id] = capture
        path = self.root_owner.root / "future-index-paths.jsonl"
        for value in _read_jsonl(path, field="runtime future index path"):
            item = _mapping(value, "future index path capture")
            session_id = _text(item, "session_id")
            if session_id not in self._sessions:
                raise ValueError("future index path belongs to an unenrolled runtime Session")
            capture = IndexHistoryCapture.from_object(item, session_id=session_id)
            prior = captures.get(session_id)
            if prior is not None and prior != capture:
                raise ValueError("runtime contains conflicting future index paths")
            captures[session_id] = capture
        return captures

    def _read_latest_snapshot(self, now: datetime) -> dict[str, object]:
        path = self.root_owner.root / "latest-snapshot.json"
        if not path.exists():
            return _waiting_snapshot(self.session, now)
        snapshot = _mapping(_read_json(path), "latest snapshot")
        snapshot_session_id = snapshot.get("session_id")
        if snapshot_session_id == self.session.session_id:
            if "known_at" not in snapshot:
                observed_at = _text(snapshot, "observed_at")
                snapshot["known_at"] = observed_at
                warnings = snapshot.get("warnings")
                if not isinstance(warnings, list):
                    raise ValueError("legacy latest snapshot warnings must be an array")
                warnings.append("LEGACY_SNAPSHOT_KNOWN_AT_EQUALS_OBSERVED_AT")
            return snapshot
        if not self._fixed_session and snapshot_session_id in self._sessions:
            return _waiting_snapshot(self.session, now)
        if snapshot_session_id != self.session.session_id:
            raise ValueError("latest snapshot belongs to another Session")
        return snapshot

    def _validate_durable_population(self) -> None:
        records = self.ledger.read()
        record_by_id = self._validate_ledger_population(records, self.ledger.read_outcomes())
        seen_windows: set[str] = set()
        for case in self.cases.values():
            candidate_record = record_by_id.get(case.decision_window_id)
            allocation = case.risk_allocation
            structure = case.selected_structure
            owning_session = (
                self._session_for_window(candidate_record.window)
                if candidate_record is not None
                else None
            )
            try:
                structure_expiry = _utc(
                    datetime.fromisoformat(_text(structure, "expiry").replace("Z", "+00:00"))
                )
            except ValueError as exc:
                raise ValueError("CaseJournal contains an invalid structure expiry") from exc
            if (
                candidate_record is None
                or candidate_record.result is not DecisionResult.CANDIDATE
                or case.decision_record_id != candidate_record.identity
                or case.decision_policy_id != self.policy.identity
                or owning_session is None
                or allocation.get("market_session_id") != owning_session.session_id
                or allocation.get("policy_id") != self.policy.identity
                or allocation.get("expires_at") != _iso(owning_session.end)
                or structure_expiry != owning_session.end
                or case.decision_window_id in seen_windows
            ):
                raise ValueError("CaseJournal contains a foreign or duplicate runtime Case")
            seen_windows.add(case.decision_window_id)
        for session_id, fact in self.settlement_facts.items():
            self._validate_settlement_fact(fact, self._sessions[session_id])

    def _validate_ledger_population(
        self,
        records: Sequence[DecisionRecord],
        outcomes: Sequence[WindowOutcome],
    ) -> dict[str, DecisionRecord]:
        expected = self._window_index()
        record_by_id = {record.window.identity: record for record in records}
        for record in records:
            window = expected.get(record.window.identity)
            if (
                window is None
                or record.window != window
                or record.decision_policy_id != self.policy.identity
            ):
                raise ValueError("ObservationLedger contains a foreign Session or Policy record")
        for outcome in outcomes:
            expected_window = expected.get(outcome.decision_window_id)
            if expected_window is None or outcome.decision_window_id not in record_by_id:
                raise ValueError("WindowOutcome population contains a foreign Session")
            if (outcome.horizon_starts_at, outcome.horizon_ends_at) != self._outcome_horizon(
                expected_window
            ) or (
                outcome.future_path is not None
                and (
                    outcome.future_path.source_id != DERIBIT_INDEX_PATH_SOURCE_ID
                    or outcome.future_path.method_id != DERIBIT_INDEX_PATH_METHOD_ID
                )
            ):
                raise ValueError("WindowOutcome population has foreign path semantics")
            if outcome.expiry_settlement is not None:
                self._validate_settlement_fact(
                    outcome.expiry_settlement,
                    self._session_for_window(expected_window),
                )
        return record_by_id

    def _open_candidate_case(self, record: DecisionRecord, now: datetime) -> None:
        existing = next(
            (case for case in self.cases.values() if case.decision_record_id == record.identity),
            None,
        )
        if existing is not None:
            return
        case = self.engine.open_case(journal=self.journal, record=record)
        self.cases[case.identity] = case
        self._audit(
            "TRADE_CASE_OPENED",
            now,
            f"case={case.identity}",
            session=self._session_for_window(record.window),
        )

    def _reconcile_candidate_cases(self, now: datetime) -> None:
        for record in self.ledger.read():
            if record.result is DecisionResult.CANDIDATE:
                self._open_candidate_case(record, now)

    def _validate_progress(self) -> None:
        attempted = self.progress.attempted_decision_window_ids
        expected = set(self._window_index())
        if len(set(attempted)) != len(attempted) or not set(attempted) <= expected:
            raise ValueError("runtime progress contains invalid attempted Window identities")
        recorded = {record.window.identity for record in self.ledger.read()}
        if not recorded <= set(attempted):
            raise ValueError("ObservationLedger contains a Window without a runtime attempt")
        if self.progress.active_session_id != self.session.session_id:
            raise ValueError("runtime progress active Session is stale or foreign")
        if self.progress.preflight_attempt_count > 3 or any(
            count > 3 for _session_id, count in self.progress.history_attempt_counts
        ):
            raise ValueError("runtime progress exceeds its bounded public attempt count")
        known_sessions = set(self._sessions)
        for counts in (
            self.progress.settlement_attempt_counts,
            self.progress.history_attempt_counts,
        ):
            if (
                len(dict(counts)) != len(counts)
                or not {key for key, _count in counts} <= known_sessions
            ):
                raise ValueError("runtime progress contains a foreign Session attempt")
        if self.progress.preflight_complete and self.progress.preflight_attempt_count == 0:
            raise ValueError("runtime progress preflight completion lacks an attempt")
        for session_id in self.settlement_facts:
            if dict(self.progress.settlement_attempt_counts).get(session_id, 0) == 0:
                raise ValueError("runtime settlement fact lacks a recorded attempt")
        for session_id in self.history_captures:
            if dict(self.progress.history_attempt_counts).get(session_id, 0) == 0:
                raise ValueError("runtime history capture lacks a recorded attempt")
        known_cases = set(self.cases)
        if not {case_id for case_id, _at in self.progress.case_attempted_at} <= known_cases:
            raise ValueError("runtime progress contains an unknown TradeCase attempt")
        for boundary in (
            self.progress.started_at,
            self.progress.updated_at,
            *(at for _case_id, at in self.progress.case_attempted_at),
        ):
            if boundary is not None and boundary > self.progress.updated_at:
                raise ValueError("runtime progress has an invalid time boundary")

    def _audit(
        self,
        kind: str,
        at: datetime,
        detail: str,
        *,
        session: DeribitSession | None = None,
    ) -> None:
        owning_session = session or self.session
        path = self.root_owner.root / "runtime-events.jsonl"
        with self._audit_lock:
            boundary = _utc(at)
            if self._last_audit_at is not None:
                boundary = max(boundary, self._last_audit_at)
            value = {
                "implementation_id": self.manifest.implementation_id,
                "session_id": owning_session.session_id,
                "at": _iso(boundary),
                "kind": kind,
                "detail": detail,
            }
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._last_audit_at = boundary

    def _audit_public_call(
        self,
        method: str,
        params: Mapping[str, object],
        timeout_seconds: float,
    ) -> None:
        detail = json.dumps(
            {
                "method": method,
                "params": dict(params),
                "timeout_seconds": timeout_seconds,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        self._audit("DERIBIT_PUBLIC_CALL", self._business_time_floor, detail)

    def _recover_audit(self) -> None:
        path = self.root_owner.root / "runtime-events.jsonl"
        if not path.exists():
            return
        _recover_jsonl(path, field="runtime audit")
        previous_at: datetime | None = None
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            value = _mapping(json.loads(line), f"runtime audit line {index}")
            if set(value) != {"implementation_id", "session_id", "at", "kind", "detail"}:
                raise ValueError(f"runtime audit line {index} has foreign fields")
            if (
                value.get("implementation_id") != self.manifest.implementation_id
                or value.get("session_id") not in self._sessions
            ):
                raise ValueError(f"runtime audit line {index} belongs to another runtime")
            at = _datetime(value, "at")
            if previous_at is not None and at < previous_at:
                raise ValueError(f"runtime audit line {index} has a regressing boundary")
            previous_at = at
            self._last_audit_at = max(self._last_audit_at or at, at)
            _text(value, "kind")
            _text(value, "detail")


class _LoopbackWorkbenchHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *args: object) -> None:
        """Keep high-frequency loopback probes out of the runtime terminal."""


class _WorkbenchServer:
    def __init__(self, directory: Path, port: int) -> None:
        if not 1 <= port <= 65_535:
            raise ValueError("Workbench port must be in [1, 65535]")
        handler = partial(_LoopbackWorkbenchHandler, directory=str(directory))
        self.server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.thread = Thread(
            target=self.server.serve_forever, name="optimatrix-workbench", daemon=True
        )

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def _clock_scope(
    at: datetime,
    policy: BtcShortVolPolicy,
) -> tuple[str, str]:
    boundary = _utc(at)
    session = current_deribit_session(boundary, phase_policy=policy.session)
    windows = Btc0DteShortVolEngine(policy=policy).decision_windows(at=boundary)
    window = next(item for item in windows if item.starts_at <= boundary < item.ends_at)
    return session.session_id, window.identity


def _unambiguous_clock_boundary(
    reading: DeribitClockReading,
    *,
    policy: BtcShortVolPolicy,
) -> datetime:
    if _clock_scope(reading.earliest_at, policy) != _clock_scope(
        reading.latest_at,
        policy,
    ):
        raise DeribitSourceError(
            "Deribit clock uncertainty crosses a Session or DecisionWindow boundary"
        )
    return _utc(reading.earliest_at)


def _manifest_session(
    manifest: RuntimeManifest,
    policy: BtcShortVolPolicy,
) -> DeribitSession:
    if (
        manifest.session_end - manifest.session_start != timedelta(days=1)
        or manifest.target_session_id != _iso(manifest.session_end)
        or manifest.session_start.minute != 0
        or manifest.session_start.second != 0
        or manifest.session_start.microsecond != 0
        or manifest.session_end.hour != 8
        or manifest.session_end.minute != 0
        or manifest.session_end.second != 0
        or manifest.session_end.microsecond != 0
    ):
        raise ValueError("runtime manifest Session boundaries are invalid")
    reconstructed = current_deribit_session(
        manifest.session_start,
        phase_policy=policy.session,
    )
    if (
        reconstructed.session_id != manifest.target_session_id
        or reconstructed.start != manifest.session_start
        or reconstructed.end != manifest.session_end
    ):
        raise ValueError("runtime manifest Session does not match the frozen Policy")
    return reconstructed


def _waiting_snapshot(session: DeribitSession, now: datetime) -> dict[str, object]:
    return {
        "observed_at": _iso(now),
        "known_at": _iso(now),
        "session_id": session.session_id,
        "instrument_count": 0,
        "requested_book_count": 0,
        "fetched_book_count": 0,
        "warnings": ["AWAITING_FIRST_CURRENT_MARKET_CUT"],
        "window": {
            "decision_window_id": canonical_identity("PendingDecisionWindow", session.session_id),
            "channel_id": "INVERSE_BTC_SHORT_VOL",
            "market_session_id": session.session_id,
            "schedule_policy_id": canonical_identity("PendingWindowSchedule", session.session_id),
            "starts_at": _iso(session.start),
            "ends_at": _iso(session.end),
            "input_deadline": _iso(session.end),
            "observation_id": None,
            "ledger_state": "STARTING_CURRENT_SESSION",
        },
        "context": {"knowledge": "UNKNOWN"},
        "projection": {
            "state": "UNKNOWN",
            "phase": "WAITING",
            "blockers": ["FIRST_CURRENT_MARKET_CUT_NOT_OBSERVED"],
            "structure": None,
        },
        "quotes": [],
        "methodology": {"source": "PRODUCTION_DERIBIT_PUBLIC_RUNTIME"},
    }


def _gap_snapshot(
    session: DeribitSession,
    window: DecisionWindow,
    now: datetime,
    blocker: str,
) -> dict[str, object]:
    return {
        "observed_at": _iso(now),
        "known_at": _iso(now),
        "session_id": session.session_id,
        "instrument_count": 0,
        "requested_book_count": 0,
        "fetched_book_count": 0,
        "warnings": ["PUBLIC_MARKET_GAP"],
        "window": {
            "decision_window_id": window.identity,
            "channel_id": window.channel_id.value,
            "market_session_id": window.market_session_id,
            "schedule_policy_id": window.schedule_policy_id,
            "starts_at": _iso(window.starts_at),
            "ends_at": _iso(window.ends_at),
            "input_deadline": _iso(window.input_deadline),
            "observation_id": None,
            "ledger_state": "GAP_PENDING_UNKNOWN",
        },
        "context": {"knowledge": "UNKNOWN"},
        "projection": {
            "state": "UNKNOWN",
            "phase": "GAP",
            "blockers": ["PUBLIC_MARKET_GAP", blocker],
            "structure": None,
        },
        "quotes": [],
        "methodology": {"source": "PRODUCTION_DERIBIT_PUBLIC_RUNTIME"},
    }


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.optimatrix-tmp")
    text = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False, sort_keys=True) + "\n"
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid durable runtime file {path.name}: {exc}") from exc


def _recover_jsonl(path: Path, *, field: str) -> None:
    payload = path.read_bytes()
    lines = payload.splitlines(keepends=True)
    accepted_bytes = 0
    for index, raw_line in enumerate(lines):
        if index == len(lines) - 1 and not raw_line.endswith(b"\n"):
            with path.open("r+b") as handle:
                handle.truncate(accepted_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            return
        try:
            value = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid {field} line {index + 1}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"invalid {field} line {index + 1}: record must be an object")
        accepted_bytes += len(raw_line)


def _read_jsonl(path: Path, *, field: str) -> tuple[object, ...]:
    if not path.exists():
        return ()
    _recover_jsonl(path, field=field)
    values: list[object] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            values.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid {field} line {index}: {exc}") from exc
    return tuple(values)


def _append_jsonl(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _path_has_symlink(path: Path) -> bool:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            return True
    return False


def _safe_error(error: Exception) -> str:
    return f"{type(error).__name__}:{str(error)[:240]}"


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{field} must be an object")
    return value


def _text(value: Mapping[str, object], field: str) -> str:
    member = value.get(field)
    if not isinstance(member, str) or not member:
        raise ValueError(f"{field} must be non-empty text")
    return member


def _attempt_counts(
    value: Mapping[str, object],
    field: str,
) -> tuple[tuple[str, int], ...]:
    member = value.get(field)
    if not isinstance(member, dict) or not all(
        isinstance(session_id, str)
        and session_id
        and isinstance(count, int)
        and not isinstance(count, bool)
        and count >= 0
        for session_id, count in member.items()
    ):
        raise ValueError(f"{field} must map Session identities to non-negative integers")
    return tuple(sorted(member.items()))


def _datetime(value: Mapping[str, object], field: str) -> datetime:
    try:
        return _utc(datetime.fromisoformat(_text(value, field).replace("Z", "+00:00")))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 datetime") from exc


def _integer(value: Mapping[str, object], field: str) -> int:
    member = value.get(field)
    if isinstance(member, bool) or not isinstance(member, int) or member < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return member


def _boolean(value: Mapping[str, object], field: str) -> bool:
    member = value.get(field)
    if not isinstance(member, bool):
        raise ValueError(f"{field} must be boolean")
    return member


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("runtime datetime must be timezone-aware")
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")
