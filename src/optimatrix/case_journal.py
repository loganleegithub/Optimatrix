from __future__ import annotations

import json
import os
from pathlib import Path

from optimatrix.identity import require_identity
from optimatrix.lifecycle import TradeCase


class CaseJournal:
    """Append-only TradeCase snapshots under one caller-supplied root."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, trade_case_id: str) -> Path:
        require_identity(trade_case_id, "trade_case_id")
        digest = trade_case_id.removeprefix("sha256:")
        return self.root / "cases" / f"{digest}.jsonl"

    def append(self, case: TradeCase) -> bool:
        snapshots = self.read(case.identity)
        if snapshots and snapshots[-1] == case:
            return False
        if snapshots:
            _validate_transition(snapshots[-1], case)
        path = self.path_for(case.identity)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "sequence": len(snapshots),
            "previous_snapshot_id": snapshots[-1].snapshot_identity if snapshots else None,
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
        return True

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
        raise ValueError("terminal TradeCase cannot append another snapshot")
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
        "entry_pricing_basis",
    )
    if any(getattr(previous, field) != getattr(current, field) for field in stable):
        raise ValueError("frozen TradeCase facts cannot change")
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
            or (not previous.gap_observed and current.gap_observed)
            or (previous.exit_intent is None and current.exit_intent is not None)
        )
    ):
        raise ValueError("CaseJournal duplicate observation needs a final Entry transition")
    if previous.gap_observed and not current.gap_observed:
        raise ValueError("CaseJournal cannot erase a known DataHealth gap")
