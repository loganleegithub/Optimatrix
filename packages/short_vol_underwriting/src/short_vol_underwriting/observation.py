from __future__ import annotations

from dataclasses import dataclass

from short_vol_underwriting.domain import OutcomeReducer
from short_vol_underwriting.identity import canonical_identity, require_identity
from short_vol_underwriting.model import (
    CaseFactBoundary,
    FactBoundary,
    ObservationQuality,
    OutcomeState,
    TerminalSource,
)


@dataclass
class Observation:
    """One admitted Shadow Case's strictly-future Outcome state."""

    outcome_contract_identity: str
    shadow_entry_identity: str
    observation_identity: str
    entry_boundary: CaseFactBoundary
    reducer: OutcomeReducer
    observation_quality: ObservationQuality = ObservationQuality.CONTINUOUS
    selected_exit_identity: str | None = None
    terminal_outcome_identity: str | None = None

    @classmethod
    def admitted(
        cls,
        *,
        outcome_contract_identity: str,
        shadow_entry_identity: str,
        entry_boundary: CaseFactBoundary | FactBoundary,
        observation_quality: ObservationQuality = ObservationQuality.CONTINUOUS,
    ) -> Observation:
        require_identity(outcome_contract_identity, "outcome_contract_identity")
        require_identity(shadow_entry_identity, "shadow_entry_identity")
        case_boundary = (
            entry_boundary
            if isinstance(entry_boundary, CaseFactBoundary)
            else CaseFactBoundary(0, entry_boundary)
        )
        identity = canonical_identity(
            "ShadowObservationIdentity",
            outcome_contract_identity,
            shadow_entry_identity,
        )
        return cls(
            outcome_contract_identity=outcome_contract_identity,
            shadow_entry_identity=shadow_entry_identity,
            observation_identity=identity,
            entry_boundary=case_boundary,
            reducer=OutcomeReducer(case_boundary),
            observation_quality=observation_quality,
        )

    @property
    def state(self) -> OutcomeState:
        return self.reducer.state

    @property
    def qualification_eligible(self) -> bool:
        return self.observation_quality is ObservationQuality.CONTINUOUS

    def latch_close(
        self,
        action_identity: str,
        boundary: CaseFactBoundary | FactBoundary,
    ) -> None:
        self.reducer.latch_close(
            action_identity,
            self._case_boundary(boundary, self.entry_boundary.segment_sequence),
        )

    def accept_eligible_exit(
        self,
        *,
        close_opportunity_evaluation_identity: str,
        boundary: CaseFactBoundary | FactBoundary,
    ) -> str | None:
        if self.state is not OutcomeState.PENDING:
            return None
        require_identity(
            close_opportunity_evaluation_identity,
            "close_opportunity_evaluation_identity",
        )
        first_close = self.reducer.first_close_identity
        if first_close is None:
            raise ValueError("eligible exit requires a first CLOSE")
        exit_identity = canonical_identity(
            "ShadowCounterfactualExitIdentity",
            self.observation_identity,
            first_close,
            close_opportunity_evaluation_identity,
        )
        first_close_boundary = self.reducer.first_close_boundary
        assert first_close_boundary is not None
        case_boundary = self._case_boundary(
            boundary,
            first_close_boundary.segment_sequence,
        )
        state = self.reducer.settle(
            boundary=case_boundary,
            eligible_exit_identity=exit_identity,
        )
        if state is not OutcomeState.EXITED_KNOWN:
            raise RuntimeError("eligible exit did not mature observation")
        self.selected_exit_identity = exit_identity
        self._freeze_terminal_identity(case_boundary)
        return exit_identity

    def accept_contract_settlement(
        self,
        *,
        settlement_fact_identity: str,
        boundary: CaseFactBoundary | FactBoundary,
    ) -> str | None:
        if self.state is not OutcomeState.PENDING:
            return None
        first_close_boundary = self.reducer.first_close_boundary
        if first_close_boundary is None:
            raise ValueError("contract settlement requires a first CLOSE")
        case_boundary = self._case_boundary(boundary, first_close_boundary.segment_sequence)
        state = self.reducer.settle(
            boundary=case_boundary,
            settlement_fact_identity=settlement_fact_identity,
        )
        if state is not OutcomeState.SETTLED_KNOWN:
            raise RuntimeError("official delivery fact did not settle observation")
        self._freeze_terminal_identity(case_boundary)
        return self.terminal_outcome_identity

    def settle_without_exit(
        self,
        *,
        boundary: CaseFactBoundary | FactBoundary,
        ordinary_attempt_terminal: bool,
        lifecycle_ready: bool,
        terminal_source: TerminalSource | None = None,
    ) -> OutcomeState:
        del terminal_source  # Process endings do not settle an admitted Observation.
        previous = self.state
        reference = self.reducer.first_close_boundary or self.entry_boundary
        case_boundary = self._case_boundary(boundary, reference.segment_sequence)
        state = self.reducer.settle(
            boundary=case_boundary,
            ordinary_attempt_terminal=ordinary_attempt_terminal,
            lifecycle_ready=lifecycle_ready,
        )
        if previous is OutcomeState.PENDING and state is not OutcomeState.PENDING:
            self._freeze_terminal_identity(case_boundary)
        return state

    def censor_control_at_process_end(
        self,
        *,
        boundary: CaseFactBoundary | FactBoundary,
        terminal_source: TerminalSource,
    ) -> OutcomeState:
        """Terminalize one selected no-trade Control, never an admitted Entry."""
        previous = self.state
        case_boundary = self._case_boundary(boundary, self.entry_boundary.segment_sequence)
        state = self.reducer.censor_control_at_process_end(
            boundary=case_boundary,
            terminal_source=terminal_source,
        )
        if previous is OutcomeState.PENDING and state is not OutcomeState.PENDING:
            self._freeze_terminal_identity(case_boundary)
        return state

    @staticmethod
    def _case_boundary(
        boundary: CaseFactBoundary | FactBoundary,
        segment_sequence: int,
    ) -> CaseFactBoundary:
        return (
            boundary
            if isinstance(boundary, CaseFactBoundary)
            else CaseFactBoundary(segment_sequence, boundary)
        )

    def _freeze_terminal_identity(self, boundary: CaseFactBoundary) -> None:
        self.terminal_outcome_identity = canonical_identity(
            "ShadowOutcomeIdentity",
            self.observation_identity,
            self.state.value,
            boundary.fact_boundary.as_object(),
        )
