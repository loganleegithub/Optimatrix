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
    DeribitHttpClient,
    DeribitSourceError,
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
ROOT_SCHEMA_VERSION = 1
RUNTIME_SCHEMA_VERSION = 1
PREFLIGHT_LEAD = timedelta(minutes=5)
SETTLEMENT_DELAY = timedelta(minutes=5)
MAXIMUM_CLOCK_SKEW_MS = 5_000
_RUNTIME_ALLOWED_ROOT_MEMBERS = {
    "cases",
    "decision-records.jsonl",
    "future-index-path.json",
    "latest-snapshot.json",
    "manifest.json",
    "runtime-events.jsonl",
    "runtime-lock",
    "runtime-state.json",
    "settlement.json",
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
    def preflight(self, *, local_now: datetime) -> datetime: ...

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

    def preflight(self, *, local_now: datetime) -> datetime:
        request_boundary = max(_utc(local_now), datetime.now(UTC))
        result = preflight_public_clock(
            self.client,
            local_now=request_boundary,
            maximum_clock_skew_ms=MAXIMUM_CLOCK_SKEW_MS,
        )
        return result.known_at

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
            known_at=max(_utc(known_at), datetime.now(UTC)),
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
    preflight_attempt_count: int
    preflight_complete: bool
    settlement_attempt_count: int
    history_attempt_count: int
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
            "preflight_attempt_count": self.preflight_attempt_count,
            "preflight_complete": self.preflight_complete,
            "settlement_attempt_count": self.settlement_attempt_count,
            "history_attempt_count": self.history_attempt_count,
            "case_attempted_at": {case_id: _iso(at) for case_id, at in self.case_attempted_at},
            "status": self.status,
            "last_error": self.last_error,
        }

    @classmethod
    def from_object(cls, value: object) -> RuntimeProgress:
        item = _mapping(value, "runtime progress")
        attempted = item.get("attempted_decision_window_ids")
        if not isinstance(attempted, list) or not all(
            isinstance(member, str) for member in attempted
        ):
            raise ValueError("runtime attempted windows must be an array of strings")
        last_error = item.get("last_error")
        if last_error is not None and not isinstance(last_error, str):
            raise ValueError("runtime last_error must be text or null")
        if item.get("schema_version") != RUNTIME_SCHEMA_VERSION:
            raise ValueError("runtime progress schema is foreign")
        expected = {
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
        if set(item) != expected:
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
            preflight_attempt_count=_integer(item, "preflight_attempt_count"),
            preflight_complete=_boolean(item, "preflight_complete"),
            settlement_attempt_count=_integer(item, "settlement_attempt_count"),
            history_attempt_count=_integer(item, "history_attempt_count"),
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
    """One Session-specific process driving the existing BTC Engine and records."""

    def __init__(
        self,
        *,
        root: Path,
        policy: BtcShortVolPolicy,
        source: BtcPublicRuntimeSource,
        event_state: EventState,
        now: datetime,
        target_session: DeribitSession | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        boundary = _utc(now)
        self.policy = policy
        self.source = source
        self.event_state = event_state
        self.sleep = sleep
        self._audit_lock = Lock()
        candidate_session = target_session or _next_complete_session(boundary, policy)
        self.root_owner = StableRuntimeRoot(
            root=root,
            policy=policy,
            session=candidate_session,
            now=boundary,
            resume_existing_session=target_session is None,
        )
        self.manifest = self.root_owner.acquire()
        try:
            self.session = _manifest_session(self.manifest, policy)
            self.engine = Btc0DteShortVolEngine(policy=policy)
            self.windows = self.engine.decision_windows(at=self.session.start)
            if (
                len(self.windows) != 96
                or tuple(window.market_session_id for window in self.windows)
                != (self.session.session_id,) * 96
            ):
                raise ValueError("runtime target Session does not produce the expected 96 Windows")
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
            self.settlement_fact = self._read_settlement()
            self.history_capture = self._read_history_capture()
            recovered_unresolved = sum(case.outcome is None for case in recovered)
            self.progress = self._start_progress(boundary, recovered_unresolved)
            self._validate_durable_population()
            self._validate_progress()
            self._write_progress(self.progress)
            bind_audit = getattr(self.source, "bind_audit", None)
            if callable(bind_audit):
                bind_audit(self._audit_public_call)
            self._reconcile_candidate_cases(boundary)
            self._reconcile_inflight_gaps(boundary)
            self._reconcile_expired_entries(boundary)
            self._reconcile_monitoring_gaps(boundary)
            self._reconcile_settlement(boundary)
            self._validate_durable_population()
            self._audit("RUNTIME_STARTED", boundary, f"restart_count={self.progress.restart_count}")
            self.publish(boundary)
        except BaseException:
            self.root_owner.release()
            raise

    def __enter__(self) -> BtcPublicShadowRuntime:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @property
    def finalization_at(self) -> datetime:
        return max(self._outcome_horizon(window)[1] for window in self.windows)

    @property
    def complete(self) -> bool:
        decisions = self.ledger.summarize(expected_windows=self.windows)
        outcomes = self.ledger.summarize_outcomes(expected_windows=self.windows)
        return (
            decisions.complete
            and outcomes.complete
            and self.settlement_fact is not None
            and all(case.outcome is not None for case in self.cases.values())
        )

    def tick(self, now: datetime) -> None:
        boundary = _utc(now)
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
        if boundary >= self.session.end + SETTLEMENT_DELAY:
            self._capture_settlement(boundary)
            if self.settlement_fact is not None:
                effective_known_at = max(effective_known_at, self.settlement_fact.known_at)
            self._reconcile_settlement(effective_known_at)
        self._finalize_due_windows(effective_known_at)
        self._reconcile_candidate_cases(effective_known_at)
        if effective_known_at >= self.finalization_at and self._settlement_resolved:
            self._finalize_outcomes(effective_known_at)
            if self.history_capture is not None:
                effective_known_at = max(effective_known_at, self.history_capture.known_at)
        if self.complete:
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
        server = _WorkbenchServer(self.root_owner.root / "workbench", port)
        server.start()
        self._audit("WORKBENCH_LISTENING", datetime.now(UTC), f"http://127.0.0.1:{port}/")
        try:
            while not self.complete:
                self.tick(datetime.now(UTC))
                self.sleep(1.0 if datetime.now(UTC) >= self.session.start else 30.0)
            self.tick(datetime.now(UTC))
            while True:
                self.sleep(30.0)
        except KeyboardInterrupt:
            self._set_status("STOPPED_FOR_RESTART", datetime.now(UTC))
            self.publish(datetime.now(UTC))
            return 0
        finally:
            server.stop()
            self.close()

    def publish(self, now: datetime) -> None:
        boundary = _utc(now)
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

    def _start_progress(self, now: datetime, recovered_count: int) -> RuntimeProgress:
        if not self.root_owner.state_path.exists():
            return RuntimeProgress(
                started_at=now,
                updated_at=now,
                restart_count=0,
                recovered_case_count=recovered_count,
                attempted_decision_window_ids=(),
                preflight_attempt_count=0,
                preflight_complete=False,
                settlement_attempt_count=0,
                history_attempt_count=0,
                case_attempted_at=(),
                status="STARTING",
                last_error=None,
            )
        prior = RuntimeProgress.from_object(_read_json(self.root_owner.state_path))
        return replace(
            prior,
            updated_at=now,
            restart_count=prior.restart_count + 1,
            recovered_case_count=recovered_count,
            status="RECOVERED",
            last_error=None,
        )

    def _write_progress(self, progress: RuntimeProgress) -> None:
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
                completed_at = self.source.preflight(local_now=now)
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
            effective_known_at = _utc(completed_at) if isinstance(completed_at, datetime) else now
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
            self._audit(
                "PUBLIC_MARKET_CUT_COMPLETE",
                now,
                f"observation={evaluation.observation.identity}",
            )
            self._set_status("RUNNING", now)
            return evaluation
        except DeribitSourceError as exc:
            self._set_status("MARKET_GAP", now, str(exc))
            self._audit("PUBLIC_MARKET_GAP", now, _safe_error(exc))
            self.latest_snapshot = _gap_snapshot(
                self.session,
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
        for window in self.windows:
            if window.identity in recorded or now < window.input_deadline:
                continue
            evaluation = self.pending_observations.pop(window.identity, None)
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
            boundary = max(
                case.last_observed_at or case.decision_boundary,
                attempts.get(case_id, case.decision_boundary),
            )
            if now <= boundary + cadence * 2 or case.gap_observed:
                continue
            gapped = replace(case, gap_observed=True)
            self.journal.append(gapped)
            self.cases[case_id] = gapped
            self._audit("LIFECYCLE_CADENCE_GAP", now, f"case={case_id}")

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
        if now < self.session.end:
            return
        for case_id, case in tuple(self.cases.items()):
            if case.entry_final:
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
            self._audit("EXPIRED_ENTRY_TERMINALIZED", known_at, f"case={case_id}")

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
            if case.outcome is not None:
                continue
            if observation is None and not case.gap_observed:
                case = replace(case, gap_observed=True)
                self.journal.append(case)
                self.cases[case.identity] = case
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
                elif observation.observed_at >= self.session.end:
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
            self._audit("TRADE_CASE_ADVANCED", now, f"case={case.identity}")

    def _capture_settlement(self, now: datetime) -> None:
        if self.settlement_fact is not None:
            return
        error: DeribitSourceError | None = None
        while self.progress.settlement_attempt_count < 3:
            attempt = self.progress.settlement_attempt_count + 1
            self._write_progress(
                replace(self.progress, settlement_attempt_count=attempt, updated_at=now)
            )
            try:
                fact = self.source.settlement(expiry=self.session.end, known_at=now)
            except DeribitSourceError as exc:
                error = exc
                self._audit(
                    "OFFICIAL_SETTLEMENT_ATTEMPT_FAILED",
                    now,
                    f"attempt={attempt}:{_safe_error(exc)}",
                )
                if attempt < 3:
                    self.sleep(float(2 ** (attempt - 1)))
                continue
            if fact is None:
                error = DeribitSourceError("OFFICIAL_DELIVERY_PRICE_NOT_FOUND")
                self._audit(
                    "OFFICIAL_SETTLEMENT_ATTEMPT_FAILED",
                    now,
                    f"attempt={attempt}:{_safe_error(error)}",
                )
                if attempt < 3:
                    self.sleep(float(2 ** (attempt - 1)))
                continue
            self._validate_settlement_fact(fact)
            self.settlement_fact = fact
            _atomic_json(self.root_owner.root / "settlement.json", fact.as_object())
            self._audit("OFFICIAL_SETTLEMENT_RECORDED", fact.known_at, f"fact={fact.identity}")
            return
        self._set_status(
            "SETTLEMENT_UNVERIFIED",
            now,
            str(error) if error is not None else "settlement interrupted before completion",
        )

    def _reconcile_settlement(self, now: datetime) -> None:
        fact = self.settlement_fact
        if fact is None:
            return
        for case_id, case in tuple(self.cases.items()):
            if case.outcome is None and case.position_id is not None:
                terminal = self.engine.settle_position(
                    journal=self.journal,
                    case=case,
                    settlement=fact,
                )
                self.cases[case_id] = terminal

    @property
    def _settlement_resolved(self) -> bool:
        return self.settlement_fact is not None or self.progress.settlement_attempt_count >= 3

    def _finalize_outcomes(self, now: datetime) -> None:
        if self.history_capture is None:
            error: DeribitSourceError | None = None
            while self.progress.history_attempt_count < 3:
                attempt = self.progress.history_attempt_count + 1
                self._write_progress(
                    replace(self.progress, history_attempt_count=attempt, updated_at=now)
                )
                try:
                    result = self.source.history(known_at=now)
                except DeribitSourceError as exc:
                    error = exc
                    self._audit(
                        "PUBLIC_FUTURE_PATH_ATTEMPT_FAILED",
                        now,
                        f"attempt={attempt}:{_safe_error(exc)}",
                    )
                    if attempt < 3:
                        self.sleep(float(2 ** (attempt - 1)))
                    continue
                self.history_capture = (
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
            if self.history_capture is None:
                detail = (
                    str(error) if error is not None else "history interrupted before completion"
                )
                self.history_capture = IndexHistoryCapture(
                    points=None,
                    known_at=now,
                    error=detail,
                )
                self._set_status("FUTURE_PATH_UNVERIFIED", now, detail)
            _atomic_json(
                self.root_owner.root / "future-index-path.json",
                self.history_capture.as_object(self.session.session_id),
            )
        history = self.history_capture.points or ()
        known_at = self.history_capture.known_at
        if self.settlement_fact is not None:
            known_at = max(known_at, self.settlement_fact.known_at)
        existing = {outcome.decision_window_id for outcome in self.ledger.read_outcomes()}
        records = {record.window.identity: record for record in self.ledger.read()}
        for window in self.windows:
            if window.identity in existing:
                continue
            record = records[window.identity]
            start, end = self._outcome_horizon(window)
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
                expiry_settlement=self.settlement_fact,
                future_path=path,
                regime_labels=(
                    ("OFFICIAL_DELIVERY_PRICE_UNAVAILABLE",) if self.settlement_fact is None else ()
                ),
                reason=None if path_known else "PUBLIC_INDEX_PATH_INCOMPLETE_OR_UNAVAILABLE",
                eligibility=window_outcome_eligibility(
                    decision_evaluable=record.result is not DecisionResult.UNKNOWN,
                    future_path_known=path_known,
                    future_path_continuous=True if path_known else None,
                ),
            )
            self.ledger.append_outcome(outcome)
        self._audit("WINDOW_OUTCOME_POPULATION_RECORDED", known_at, "count=96")

    def _outcome_horizon(self, window: DecisionWindow) -> tuple[datetime, datetime]:
        start = window.ends_at
        minimum_end = start + timedelta(minutes=self.policy.window.cadence_minutes)
        return start, max(self.session.end, minimum_end)

    def _read_settlement(self) -> ExpirySettlementFact | None:
        path = self.root_owner.root / "settlement.json"
        if not path.exists():
            return None
        fact = ExpirySettlementFact.from_object(_read_json(path))
        self._validate_settlement_fact(fact)
        return fact

    def _validate_settlement_fact(self, fact: ExpirySettlementFact) -> None:
        if (
            fact.product_id is not BTC.product_id
            or fact.expiry != self.session.end
            or fact.evidence_kind is not SettlementEvidenceKind.OFFICIAL_EXCHANGE
            or fact.source_id != DERIBIT_DELIVERY_PRICE_SOURCE_ID
            or fact.method_id != DERIBIT_DELIVERY_PRICE_METHOD_ID
        ):
            raise ValueError("settlement fact does not match the runtime Session and source")

    def _read_history_capture(self) -> IndexHistoryCapture | None:
        path = self.root_owner.root / "future-index-path.json"
        return (
            IndexHistoryCapture.from_object(
                _read_json(path),
                session_id=self.session.session_id,
            )
            if path.exists()
            else None
        )

    def _read_latest_snapshot(self, now: datetime) -> dict[str, object]:
        path = self.root_owner.root / "latest-snapshot.json"
        if not path.exists():
            return _waiting_snapshot(self.session, now)
        snapshot = _mapping(_read_json(path), "latest snapshot")
        if snapshot.get("session_id") != self.session.session_id:
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
                or allocation.get("market_session_id") != self.session.session_id
                or allocation.get("policy_id") != self.policy.identity
                or allocation.get("expires_at") != _iso(self.session.end)
                or structure_expiry != self.session.end
                or case.decision_window_id in seen_windows
            ):
                raise ValueError("CaseJournal contains a foreign or duplicate runtime Case")
            seen_windows.add(case.decision_window_id)
        if self.settlement_fact is not None:
            self._validate_settlement_fact(self.settlement_fact)

    def _validate_ledger_population(
        self,
        records: Sequence[DecisionRecord],
        outcomes: Sequence[WindowOutcome],
    ) -> dict[str, DecisionRecord]:
        expected = {window.identity: window for window in self.windows}
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
                self._validate_settlement_fact(outcome.expiry_settlement)
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
        self._audit("TRADE_CASE_OPENED", now, f"case={case.identity}")

    def _reconcile_candidate_cases(self, now: datetime) -> None:
        for record in self.ledger.read():
            if record.result is DecisionResult.CANDIDATE:
                self._open_candidate_case(record, now)

    def _validate_progress(self) -> None:
        attempted = self.progress.attempted_decision_window_ids
        expected = {window.identity for window in self.windows}
        if len(set(attempted)) != len(attempted) or not set(attempted) <= expected:
            raise ValueError("runtime progress contains invalid attempted Window identities")
        if any(
            count > 3
            for count in (
                self.progress.preflight_attempt_count,
                self.progress.settlement_attempt_count,
                self.progress.history_attempt_count,
            )
        ):
            raise ValueError("runtime progress exceeds its bounded public attempt count")
        if self.progress.preflight_complete and self.progress.preflight_attempt_count == 0:
            raise ValueError("runtime progress preflight completion lacks an attempt")
        if self.settlement_fact is not None and self.progress.settlement_attempt_count == 0:
            raise ValueError("runtime settlement fact lacks a recorded attempt")
        if self.history_capture is not None and self.progress.history_attempt_count == 0:
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

    def _audit(self, kind: str, at: datetime, detail: str) -> None:
        path = self.root_owner.root / "runtime-events.jsonl"
        value = {
            "implementation_id": self.manifest.implementation_id,
            "session_id": self.session.session_id,
            "at": _iso(at),
            "kind": kind,
            "detail": detail,
        }
        with self._audit_lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())

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
        self._audit("DERIBIT_PUBLIC_CALL", datetime.now(UTC), detail)

    def _recover_audit(self) -> None:
        path = self.root_owner.root / "runtime-events.jsonl"
        if not path.exists():
            return
        _recover_jsonl(path, field="runtime audit")
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            value = _mapping(json.loads(line), f"runtime audit line {index}")
            if set(value) != {"implementation_id", "session_id", "at", "kind", "detail"}:
                raise ValueError(f"runtime audit line {index} has foreign fields")
            if (
                value.get("implementation_id") != self.manifest.implementation_id
                or value.get("session_id") != self.manifest.target_session_id
            ):
                raise ValueError(f"runtime audit line {index} belongs to another runtime")
            _datetime(value, "at")
            _text(value, "kind")
            _text(value, "detail")


class _WorkbenchServer:
    def __init__(self, directory: Path, port: int) -> None:
        if not 1 <= port <= 65_535:
            raise ValueError("Workbench port must be in [1, 65535]")
        handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
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


def _next_complete_session(now: datetime, policy: BtcShortVolPolicy) -> DeribitSession:
    current = current_deribit_session(now, phase_policy=policy.session)
    if now == current.start:
        return current
    return current_deribit_session(current.end, phase_policy=policy.session)


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
        "session_id": session.session_id,
        "instrument_count": 0,
        "requested_book_count": 0,
        "fetched_book_count": 0,
        "warnings": ["WAITING_FOR_AUTHORIZED_COMPLETE_SESSION"],
        "window": {
            "decision_window_id": canonical_identity("PendingDecisionWindow", session.session_id),
            "channel_id": "INVERSE_BTC_SHORT_VOL",
            "market_session_id": session.session_id,
            "schedule_policy_id": canonical_identity("PendingWindowSchedule", session.session_id),
            "starts_at": _iso(session.start),
            "ends_at": _iso(session.end),
            "input_deadline": _iso(session.end),
            "observation_id": None,
            "ledger_state": "WAITING_FOR_SESSION",
        },
        "context": {"knowledge": "UNKNOWN"},
        "projection": {
            "state": "UNKNOWN",
            "phase": "WAITING",
            "blockers": ["COMPLETE_SESSION_NOT_STARTED"],
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
