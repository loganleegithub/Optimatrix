from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from optimatrix.identity import require_identity
from optimatrix.lifecycle import ShadowPathStatistic, ShadowPathStatisticKind, TradeCase


@dataclass(frozen=True)
class _JournalTail:
    snapshot_count: int
    case: TradeCase
    size: int
    mtime_ns: int
    ctime_ns: int
    inode: int


class CaseJournal:
    """Append-only TradeCase snapshots under one caller-supplied root."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._tails: dict[str, _JournalTail] = {}

    def path_for(self, trade_case_id: str) -> Path:
        require_identity(trade_case_id, "trade_case_id")
        digest = trade_case_id.removeprefix("sha256:")
        return self.root / "cases" / f"{digest}.jsonl"

    def append(self, case: TradeCase) -> bool:
        tail = self._tail_for_append(case.identity)
        if tail is not None and tail.case == case:
            return False
        if tail is not None:
            _validate_transition(tail.case, case)
        path = self.path_for(case.identity)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "sequence": tail.snapshot_count if tail is not None else 0,
            "previous_snapshot_id": tail.case.snapshot_identity if tail is not None else None,
            "case": case.as_object(),
        }
        line = json.dumps(
            record,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        if path.exists() and path.stat().st_size > 0:
            with path.open("rb") as existing:
                existing.seek(-1, os.SEEK_END)
                needs_separator = existing.read(1) != b"\n"
        else:
            needs_separator = False
        with path.open("a", encoding="utf-8") as handle:
            if needs_separator:
                handle.write("\n")
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._remember_tail(
            case.identity,
            (tail.snapshot_count if tail is not None else 0) + 1,
            case,
        )
        return True

    def _tail_for_append(self, trade_case_id: str) -> _JournalTail | None:
        path = self.path_for(trade_case_id)
        cached = self._tails.get(trade_case_id)
        if cached is not None and path.exists():
            metadata = path.stat()
            if (
                metadata.st_size == cached.size
                and metadata.st_mtime_ns == cached.mtime_ns
                and metadata.st_ctime_ns == cached.ctime_ns
                and metadata.st_ino == cached.inode
            ):
                return cached
        snapshots = self.read(trade_case_id)
        if not snapshots:
            return None
        return self._tails[trade_case_id]

    def _remember_tail(
        self,
        trade_case_id: str,
        snapshot_count: int,
        case: TradeCase,
    ) -> None:
        metadata = self.path_for(trade_case_id).stat()
        self._tails[trade_case_id] = _JournalTail(
            snapshot_count=snapshot_count,
            case=case,
            size=metadata.st_size,
            mtime_ns=metadata.st_mtime_ns,
            ctime_ns=metadata.st_ctime_ns,
            inode=metadata.st_ino,
        )

    def read(self, trade_case_id: str) -> tuple[TradeCase, ...]:
        return self._read(trade_case_id, recover_truncated_tail=False)

    def _read(
        self,
        trade_case_id: str,
        *,
        recover_truncated_tail: bool,
    ) -> tuple[TradeCase, ...]:
        path = self.path_for(trade_case_id)
        if not path.exists():
            self._tails.pop(trade_case_id, None)
            return ()
        output: list[TradeCase] = []
        previous_snapshot_id: str | None = None
        payload = path.read_bytes()
        lines = payload.splitlines(keepends=True)
        accepted_bytes = 0
        for index, raw_line in enumerate(lines):
            line_number = index + 1
            if index == len(lines) - 1 and not raw_line.endswith(b"\n"):
                if recover_truncated_tail:
                    _truncate(path, accepted_bytes)
                    if output:
                        self._remember_tail(trade_case_id, len(output), output[-1])
                    else:
                        self._tails.pop(trade_case_id, None)
                    return tuple(output)
                raise ValueError(f"invalid CaseJournal line {line_number}: unterminated write")
            try:
                line = raw_line.decode("utf-8")
                value = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid CaseJournal line {line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(
                    f"invalid CaseJournal line {line_number}: record must be an object"
                )
            if value.get("sequence") != len(output):
                raise ValueError("CaseJournal sequence is not contiguous")
            if value.get("previous_snapshot_id") != previous_snapshot_id:
                raise ValueError("CaseJournal snapshot chain is broken")
            case = TradeCase.from_object(value.get("case"))
            if case.identity != trade_case_id:
                raise ValueError("CaseJournal contains a different TradeCase")
            if output:
                _validate_transition(output[-1], case)
            output.append(case)
            previous_snapshot_id = case.snapshot_identity
            accepted_bytes += len(raw_line)
        if output:
            self._remember_tail(trade_case_id, len(output), output[-1])
        else:
            self._tails.pop(trade_case_id, None)
        return tuple(output)

    def recover(self, trade_case_id: str) -> TradeCase:
        snapshots = self._read(trade_case_id, recover_truncated_tail=True)
        if not snapshots:
            raise ValueError("CaseJournal is empty")
        return snapshots[-1]

    def recover_all(
        self,
        *,
        recoverable_empty_case_ids: frozenset[str] = frozenset(),
    ) -> tuple[TradeCase, ...]:
        """Recover every accepted Case prefix after validating the cases directory."""

        for trade_case_id in recoverable_empty_case_ids:
            require_identity(trade_case_id, "recoverable_empty_case_id")
        directory = self.root / "cases"
        if directory.is_symlink():
            raise ValueError("CaseJournal cases path must be a directory, not a symlink")
        if not directory.exists():
            return ()
        if not directory.is_dir():
            raise ValueError("CaseJournal cases path must be a directory, not a symlink")
        entries: list[tuple[Path, str]] = []
        for path in sorted(directory.iterdir(), key=lambda item: item.name):
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"CaseJournal cases directory contains foreign entry: {path.name}")
            if path.suffix != ".jsonl":
                raise ValueError(f"CaseJournal cases directory contains foreign entry: {path.name}")
            trade_case_id = f"sha256:{path.stem}"
            try:
                require_identity(trade_case_id, "case journal filename")
            except ValueError as exc:
                raise ValueError(f"invalid CaseJournal filename: {path.name}") from exc
            if self.path_for(trade_case_id) != path:
                raise ValueError(f"invalid CaseJournal filename: {path.name}")
            entries.append((path, trade_case_id))
        recovered: list[TradeCase] = []
        for path, trade_case_id in entries:
            if b"\n" not in path.read_bytes():
                if trade_case_id not in recoverable_empty_case_ids:
                    raise ValueError(f"CaseJournal file has no accepted snapshot: {path.name}")
                path.unlink()
                self._tails.pop(trade_case_id, None)
                continue
            snapshots = self._read(trade_case_id, recover_truncated_tail=True)
            if not snapshots:
                raise ValueError(f"CaseJournal file is empty: {path.name}")
            recovered.append(snapshots[-1])
        return tuple(recovered)


def _truncate(path: Path, accepted_bytes: int) -> None:
    with path.open("r+b") as handle:
        handle.truncate(accepted_bytes)
        handle.flush()
        os.fsync(handle.fileno())


def _validate_transition(previous: TradeCase, current: TradeCase) -> None:
    if previous.identity != current.identity:
        raise ValueError("TradeCase identity cannot change")
    if previous.outcome is not None:
        if _is_settlement_explanation_enrichment(previous, current):
            return
        raise ValueError("terminal TradeCase permits only settlement explanation enrichment")
    stable = (
        "channel_id",
        "truth_layer",
        "decision_record_id",
        "decision_window_id",
        "decision_policy_id",
        "decision_boundary",
        "decision_session_phase",
        "decision_vrp_proxy_ratio",
        "selected_structure_id",
        "selected_structure_json",
        "risk_allocation_id",
        "risk_allocation_json",
        "opened_at",
        "entry_deadline",
        "decision_route_evidence_id",
        "decision_route_evidence_json",
    )
    if any(getattr(previous, field) != getattr(current, field) for field in stable):
        raise ValueError("frozen TradeCase facts cannot change")
    previous_path = previous.explanation_path
    current_path = current.explanation_path
    if current_path.observation_count < previous_path.observation_count:
        raise ValueError("TradeCase explanation observation count cannot decrease")
    if current_path.observation_count == previous_path.observation_count:
        if (
            current_path.last_observation_id != previous_path.last_observation_id
            or current_path.last_observed_at != previous_path.last_observed_at
            or current_path.statistics != previous_path.statistics
        ):
            raise ValueError("TradeCase explanation cursor changed without a new observation")
    elif (
        current_path.observation_count != previous_path.observation_count + 1
        or current_path.last_observed_at <= previous_path.last_observed_at
    ):
        raise ValueError("TradeCase explanation cursor must advance by one observation")
    _validate_path_statistics(
        previous_path.statistics,
        current_path.statistics,
        current_observation_id=current_path.last_observation_id,
        current_observed_at=current_path.last_observed_at,
    )
    if (
        current_path.points[: len(previous_path.points)] != previous_path.points
        or current_path.gaps[: len(previous_path.gaps)] != previous_path.gaps
    ):
        raise ValueError("TradeCase explanation path must preserve its accepted prefix")
    if previous_path.alternative_entry_bases and (
        current_path.alternative_entry_bases != previous_path.alternative_entry_bases
    ):
        raise ValueError("frozen alternative Entry bases cannot change")
    if previous.entry_final and (
        current.entry_status != previous.entry_status
        or current.entry_final != previous.entry_final
        or current.entry_observation_id != previous.entry_observation_id
        or current.entry_observed_at != previous.entry_observed_at
        or current.entry_known_at != previous.entry_known_at
        or current.entry_reason != previous.entry_reason
        or current.entry_reunderwriting_json != previous.entry_reunderwriting_json
        or current.entry_pricing_json != previous.entry_pricing_json
        or current.entry_native_net_credit != previous.entry_native_net_credit
        or current.entry_index_price_usd != previous.entry_index_price_usd
        or current.entry_vrp_proxy_ratio != previous.entry_vrp_proxy_ratio
        or current.position_id != previous.position_id
    ):
        raise ValueError("final Entry truth cannot change")
    if previous.position_id is not None and current.position_id != previous.position_id:
        raise ValueError("Shadow Position identity cannot change")
    if previous.exit_intent is not None and current.exit_intent != previous.exit_intent:
        raise ValueError("first ExitIntent cannot change")
    state_order = {None: -1, "MONITORING": 0, "EXIT_INTENT_FROZEN": 1, "TERMINAL": 2}
    previous_state = previous.position_state.value if previous.position_state is not None else None
    current_state = current.position_state.value if current.position_state is not None else None
    if state_order[current_state] < state_order[previous_state]:
        raise ValueError("Shadow Position state cannot move backwards")
    if (
        previous.last_observed_at is not None
        and current.last_observed_at is not None
        and current.last_observed_at < previous.last_observed_at
    ):
        raise ValueError("CaseJournal observation time must increase")
    if (
        previous.last_observed_at is not None
        and current.last_observed_at == previous.last_observed_at
        and not (
            (not previous.entry_final and current.entry_final)
            or (previous.outcome is None and current.outcome is not None)
            or (len(current_path.gaps) > len(previous_path.gaps))
            or (previous.exit_intent is None and current.exit_intent is not None)
        )
    ):
        raise ValueError("CaseJournal duplicate observation needs a final Entry transition")
    if previous.gap_observed and not current.gap_observed:
        raise ValueError("CaseJournal cannot erase a known DataHealth gap")


def _validate_path_statistics(
    previous: tuple[ShadowPathStatistic, ...],
    current: tuple[ShadowPathStatistic, ...],
    *,
    current_observation_id: str,
    current_observed_at: datetime,
) -> None:
    prior_by_kind = {statistic.kind: statistic for statistic in previous}
    current_by_kind = {statistic.kind: statistic for statistic in current}
    if not prior_by_kind.keys() <= current_by_kind.keys():
        raise ValueError("TradeCase explanation statistics cannot erase an accepted extreme")
    minimum_kinds = {
        ShadowPathStatisticKind.MINIMUM_PUT_SHORT_DISTANCE_USD,
        ShadowPathStatisticKind.MINIMUM_CALL_SHORT_DISTANCE_USD,
        ShadowPathStatisticKind.MINIMUM_IMPLIED_VARIANCE_PROXY,
        ShadowPathStatisticKind.MINIMUM_TRAILING_RV_PROXY,
        ShadowPathStatisticKind.MINIMUM_SHORT_MARK_IV,
    }
    for kind, prior in prior_by_kind.items():
        updated = current_by_kind[kind]
        if kind in minimum_kinds:
            monotonic = updated.value <= prior.value
        else:
            monotonic = updated.value >= prior.value
        if not monotonic or (updated.value == prior.value and updated != prior):
            raise ValueError("TradeCase explanation statistic is not a monotonic extreme")
    for kind, updated in current_by_kind.items():
        previous_statistic = prior_by_kind.get(kind)
        if updated != previous_statistic and (
            updated.observation_id != current_observation_id
            or updated.observed_at != current_observed_at
        ):
            raise ValueError("TradeCase explanation extreme must bind the advancing observation")


def _is_settlement_explanation_enrichment(
    previous: TradeCase,
    current: TradeCase,
) -> bool:
    previous_outcome = previous.outcome
    current_outcome = current.outcome
    if previous_outcome is None or current_outcome is None:
        return False
    prior_explanation = previous_outcome.explanation
    current_explanation = current_outcome.explanation
    if (
        previous_outcome.terminal_method.value != "WHOLE_PRODUCT_EXIT"
        or prior_explanation.complete
        or prior_explanation.hold_to_expiry.status.value != "UNKNOWN"
        or not current_explanation.complete
        or current_explanation.hold_to_expiry.status.value != "EVALUABLE"
    ):
        return False
    try:
        same_case = replace(current, outcome=previous_outcome) == previous
        same_outcome = replace(current_outcome, explanation=prior_explanation) == previous_outcome
        same_explanation = (
            replace(
                current_explanation,
                hold_to_expiry=prior_explanation.hold_to_expiry,
                complete=prior_explanation.complete,
            )
            == prior_explanation
        )
    except ValueError:
        return False
    return same_case and same_outcome and same_explanation
