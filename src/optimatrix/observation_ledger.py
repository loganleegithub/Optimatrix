from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from optimatrix.channels import CHANNELS
from optimatrix.decision import DecisionRecord, DecisionResult, DecisionWindow
from optimatrix.lifecycle import WindowOutcome


@dataclass(frozen=True)
class WindowPopulationSummary:
    denominator: int
    recorded: int
    missing: int
    result_counts: tuple[tuple[str, int], ...]
    earliest_blocker_counts: tuple[tuple[str, int], ...]

    @property
    def complete(self) -> bool:
        return self.missing == 0

    def as_object(self) -> dict[str, object]:
        return {
            "denominator": self.denominator,
            "recorded": self.recorded,
            "missing": self.missing,
            "complete": self.complete,
            "result_counts": dict(self.result_counts),
            "earliest_blocker_counts": dict(self.earliest_blocker_counts),
        }


@dataclass(frozen=True)
class WindowOutcomePopulationSummary:
    denominator: int
    recorded: int
    missing: int
    future_path_known: int
    future_path_unknown: int
    continuous: int
    discontinuous: int
    decision_evaluable: int
    strategy_population_eligible: int

    @property
    def complete(self) -> bool:
        return self.missing == 0

    def as_object(self) -> dict[str, object]:
        return {
            "denominator": self.denominator,
            "recorded": self.recorded,
            "missing": self.missing,
            "complete": self.complete,
            "future_path_known": self.future_path_known,
            "future_path_unknown": self.future_path_unknown,
            "continuous": self.continuous,
            "discontinuous": self.discontinuous,
            "decision_evaluable": self.decision_evaluable,
            "strategy_population_eligible": self.strategy_population_eligible,
        }


class ObservationLedger:
    """Append-once DecisionRecords under one caller-supplied root."""

    def __init__(self, root: Path) -> None:
        self.path = root / "decision-records.jsonl"
        self.outcome_path = root / "window-outcomes.jsonl"

    def append(self, record: DecisionRecord) -> bool:
        existing = {item.window.identity: item for item in self.read()}
        prior = existing.get(record.window.identity)
        if prior is not None:
            if prior == record:
                return False
            raise ValueError("DecisionWindow already has a different DecisionRecord")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            record.as_object(),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return True

    def read(self) -> tuple[DecisionRecord, ...]:
        return self._read_records(recover_unterminated_tail=False)

    def _read_records(
        self,
        *,
        recover_unterminated_tail: bool,
    ) -> tuple[DecisionRecord, ...]:
        if not self.path.exists():
            return ()
        records: list[DecisionRecord] = []
        seen: set[str] = set()
        payload = self.path.read_bytes()
        lines = payload.splitlines(keepends=True)
        accepted_bytes = 0
        for index, raw_line in enumerate(lines):
            number = index + 1
            if index == len(lines) - 1 and not raw_line.endswith(b"\n"):
                if recover_unterminated_tail:
                    _truncate(self.path, accepted_bytes)
                    return tuple(records)
                raise ValueError(f"invalid ObservationLedger line {number}: unterminated write")
            try:
                line = raw_line.decode("utf-8")
                value = json.loads(line)
                record = DecisionRecord.from_object(value)
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid ObservationLedger line {number}: {exc}") from exc
            if record.window.identity in seen:
                raise ValueError("ObservationLedger contains a duplicate DecisionWindow")
            seen.add(record.window.identity)
            records.append(record)
            accepted_bytes += len(raw_line)
        return tuple(records)

    def append_outcome(self, outcome: WindowOutcome) -> bool:
        record = next(
            (item for item in self.read() if item.window.identity == outcome.decision_window_id),
            None,
        )
        if record is None:
            raise ValueError("WindowOutcome requires a matching DecisionRecord in this ledger")
        if outcome.expiry_settlement is not None and (
            outcome.expiry_settlement.product_id
            is not CHANNELS[record.window.channel_id].product.product_id
        ):
            raise ValueError("WindowOutcome settlement product does not match its DecisionWindow")
        decision_evaluable = record.result is not DecisionResult.UNKNOWN
        if outcome.eligibility.decision_evaluable.value is not decision_evaluable:
            raise ValueError("WindowOutcome Decision eligibility does not match its DecisionRecord")
        existing = {item.decision_window_id: item for item in self.read_outcomes()}
        prior = existing.get(outcome.decision_window_id)
        if prior is not None:
            if prior == outcome:
                return False
            raise ValueError("DecisionWindow already has a different WindowOutcome")
        self.outcome_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            outcome.as_object(),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        with self.outcome_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return True

    def read_outcomes(self) -> tuple[WindowOutcome, ...]:
        return self._read_outcomes(recover_unterminated_tail=False)

    def _read_outcomes(
        self,
        *,
        recover_unterminated_tail: bool,
    ) -> tuple[WindowOutcome, ...]:
        if not self.outcome_path.exists():
            return ()
        outcomes: list[WindowOutcome] = []
        seen: set[str] = set()
        payload = self.outcome_path.read_bytes()
        lines = payload.splitlines(keepends=True)
        accepted_bytes = 0
        for index, raw_line in enumerate(lines):
            number = index + 1
            if index == len(lines) - 1 and not raw_line.endswith(b"\n"):
                if recover_unterminated_tail:
                    _truncate(self.outcome_path, accepted_bytes)
                    return tuple(outcomes)
                raise ValueError(f"invalid WindowOutcome line {number}: unterminated write")
            try:
                line = raw_line.decode("utf-8")
                value = json.loads(line)
                outcome = WindowOutcome.from_object(value)
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid WindowOutcome line {number}: {exc}") from exc
            if outcome.decision_window_id in seen:
                raise ValueError("ObservationLedger contains a duplicate WindowOutcome")
            seen.add(outcome.decision_window_id)
            outcomes.append(outcome)
            accepted_bytes += len(raw_line)
        return tuple(outcomes)

    def recover(
        self,
    ) -> tuple[tuple[DecisionRecord, ...], tuple[WindowOutcome, ...]]:
        """Discard only unterminated final writes and return both accepted populations."""

        records = self._read_records(recover_unterminated_tail=True)
        outcomes = self._read_outcomes(recover_unterminated_tail=True)
        return records, outcomes

    def summarize(
        self,
        *,
        expected_windows: tuple[DecisionWindow, ...],
    ) -> WindowPopulationSummary:
        expected_ids = {window.identity for window in expected_windows}
        if len(expected_ids) != len(expected_windows):
            raise ValueError("expected DecisionWindows must be unique")
        records = self.read()
        relevant = tuple(record for record in records if record.window.identity in expected_ids)
        result_counts = _counts(record.result.value for record in relevant)
        blocker_counts = _counts(
            record.earliest_blocker for record in relevant if record.earliest_blocker is not None
        )
        return WindowPopulationSummary(
            denominator=len(expected_windows),
            recorded=len(relevant),
            missing=len(expected_windows) - len(relevant),
            result_counts=result_counts,
            earliest_blocker_counts=blocker_counts,
        )

    def summarize_outcomes(
        self,
        *,
        expected_windows: tuple[DecisionWindow, ...],
    ) -> WindowOutcomePopulationSummary:
        expected_ids = {window.identity for window in expected_windows}
        if len(expected_ids) != len(expected_windows):
            raise ValueError("expected DecisionWindows must be unique")
        outcomes = tuple(
            outcome
            for outcome in self.read_outcomes()
            if outcome.decision_window_id in expected_ids
        )
        return WindowOutcomePopulationSummary(
            denominator=len(expected_windows),
            recorded=len(outcomes),
            missing=len(expected_windows) - len(outcomes),
            future_path_known=sum(item.future_path_known for item in outcomes),
            future_path_unknown=sum(not item.future_path_known for item in outcomes),
            continuous=sum(item.future_path_continuous is True for item in outcomes),
            discontinuous=sum(item.future_path_continuous is False for item in outcomes),
            decision_evaluable=sum(
                item.eligibility.decision_evaluable.value is True for item in outcomes
            ),
            strategy_population_eligible=sum(
                item.eligibility.strategy_population_eligible.value is True for item in outcomes
            ),
        )


def _counts(values: Iterable[str]) -> tuple[tuple[str, int], ...]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return tuple(sorted(counts.items()))


def _truncate(path: Path, accepted_bytes: int) -> None:
    with path.open("r+b") as handle:
        handle.truncate(accepted_bytes)
        handle.flush()
        os.fsync(handle.fileno())
