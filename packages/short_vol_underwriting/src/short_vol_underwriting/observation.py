from __future__ import annotations

from dataclasses import dataclass

from short_vol_underwriting.domain import OutcomeReducer
from short_vol_underwriting.identity import canonical_identity, require_identity
from short_vol_underwriting.model import FactBoundary, OutcomeState, TerminalSource


@dataclass
class Observation:
    """One admitted Shadow Case's strictly-future Outcome state."""

    outcome_contract_identity: str
    shadow_entry_identity: str
    observation_identity: str
    entry_boundary: FactBoundary
    reducer: OutcomeReducer
    selected_exit_identity: str | None = None
    terminal_outcome_identity: str | None = None

    @classmethod
    def admitted(
        cls,
        *,
        outcome_contract_identity: str,
        shadow_entry_identity: str,
        entry_boundary: FactBoundary,
    ) -> Observation:
        require_identity(outcome_contract_identity, "outcome_contract_identity")
        require_identity(shadow_entry_identity, "shadow_entry_identity")
        identity = canonical_identity(
            "ShadowObservationIdentity",
            outcome_contract_identity,
            shadow_entry_identity,
        )
        return cls(
            outcome_contract_identity=outcome_contract_identity,
            shadow_entry_identity=shadow_entry_identity,
            observation_identity=identity,
            entry_boundary=entry_boundary,
            reducer=OutcomeReducer(entry_boundary),
        )

    @property
    def state(self) -> OutcomeState:
        return self.reducer.state

    def latch_close(self, action_identity: str, boundary: FactBoundary) -> None:
        self.reducer.latch_close(action_identity, boundary)

    def accept_eligible_exit(
        self,
        *,
        close_opportunity_evaluation_identity: str,
        boundary: FactBoundary,
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
        state = self.reducer.settle(
            boundary=boundary,
            eligible_exit_identity=exit_identity,
        )
        if state is not OutcomeState.MATURE_KNOWN:
            raise RuntimeError("eligible exit did not mature observation")
        self.selected_exit_identity = exit_identity
        self._freeze_terminal_identity(boundary)
        return exit_identity

    def settle_without_exit(
        self,
        *,
        boundary: FactBoundary,
        ordinary_attempt_terminal: bool,
        lifecycle_ready: bool,
        terminal_source: TerminalSource | None = None,
    ) -> OutcomeState:
        previous = self.state
        state = self.reducer.settle(
            boundary=boundary,
            ordinary_attempt_terminal=ordinary_attempt_terminal,
            lifecycle_ready=lifecycle_ready,
            terminal_source=terminal_source,
        )
        if previous is OutcomeState.PENDING and state is not OutcomeState.PENDING:
            self._freeze_terminal_identity(boundary)
        return state

    def _freeze_terminal_identity(self, boundary: FactBoundary) -> None:
        self.terminal_outcome_identity = canonical_identity(
            "ShadowOutcomeIdentity",
            self.observation_identity,
            self.state.value,
            boundary.as_object(),
        )
