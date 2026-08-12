from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from pathlib import Path

from options_domain import INVERSE_BTC, OptionProductSpec
from short_vol_underwriting import (
    POSITION_CLOSE_REASONS,
    PolicyChain,
    RuntimeBindings,
    ShadowCaseRead,
    ShadowCaseStore,
    canonical_decimal,
    canonical_identity,
    is_shadow_case_staging_name,
    shadow_case_id_from_directory_name,
)
from short_vol_underwriting.identity import require_identity

from radar_runtime.identity import git_repository_root
from radar_runtime.service import load_persistent_product_policies

V2_CASE_REPORT_SCHEMA_VERSION = 3
V2_CHANNEL_ID = "INVERSE_BTC_SHORT_VOL_V2"


class V2CaseReportError(ValueError):
    """A schema-v5 Case repository cannot support the declared offline report."""


@dataclass(frozen=True)
class _CaseOutcomeRow:
    case_id: str
    enrollment_kind: str
    observation_quality: str
    terminal_state: str
    expiry_ms: int
    selection_tte_band_id: str
    selection_option_type: str
    selection_delta_bucket: str
    selection_score_band: str
    selection_score_coverage: str
    entry_refresh_score_band: str
    selected_economic_action: str
    refreshed_economic_action: str
    sampling_kind: str | None
    inclusion_numerator: int | None
    inclusion_denominator: int | None
    stressed_normalized_net_pnl: Decimal | None
    raw_vwap_normalized_net_pnl: Decimal | None
    terminal_method: str | None
    terminal_economics_eligible: bool
    continuous_path_eligible: bool
    terminal_sample_integrity_eligible: bool
    exit_acquisition_eligible: bool
    exit_acquisition_window_status: str

    def as_object(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "enrollment_kind": self.enrollment_kind,
            "observation_quality": self.observation_quality,
            "terminal_state": self.terminal_state,
            "expiry_ms": self.expiry_ms,
            "selection_tte_band_id": self.selection_tte_band_id,
            "selection_option_type": self.selection_option_type,
            "selection_delta_bucket": self.selection_delta_bucket,
            "selection_score_band": self.selection_score_band,
            "selection_score_coverage": self.selection_score_coverage,
            "entry_refresh_score_band": self.entry_refresh_score_band,
            "selected_economic_action": self.selected_economic_action,
            "refreshed_economic_action": self.refreshed_economic_action,
            "sampling_kind": self.sampling_kind,
            "inclusion_numerator": self.inclusion_numerator,
            "inclusion_denominator": self.inclusion_denominator,
            "stressed_normalized_net_pnl": _decimal_text(self.stressed_normalized_net_pnl),
            "raw_vwap_normalized_net_pnl": _decimal_text(self.raw_vwap_normalized_net_pnl),
            "terminal_method": self.terminal_method,
            "terminal_economics_eligible": self.terminal_economics_eligible,
            "continuous_path_eligible": self.continuous_path_eligible,
            "terminal_sample_integrity_eligible": (self.terminal_sample_integrity_eligible),
            "exit_acquisition_eligible": self.exit_acquisition_eligible,
            "exit_acquisition_window_status": self.exit_acquisition_window_status,
        }


def load_v2_case_report(
    cases_directory: Path,
    *,
    repository: Path | None = None,
    runtime_active: bool = False,
) -> dict[str, object]:
    """Read only official schema-v5 Cases and derive one descriptive research report."""

    directory = _existing_absolute_directory(cases_directory)
    repo = git_repository_root(repository or Path.cwd())
    product, policies = load_persistent_product_policies(repo, INVERSE_BTC)
    bindings = RuntimeBindings(
        code_identity="0" * 40,
        runtime_identity=canonical_identity(
            "V2OfflineCaseReportReader",
            directory.as_posix(),
            policies.radar.identity,
            policies.underwriting.identity,
            policies.position.identity,
        ),
        radar_policy_identity=policies.radar.identity,
        underwriting_policy_identity=policies.underwriting.identity,
        position_policy_identity=policies.position.identity,
    )
    store = ShadowCaseStore(directory, bindings=bindings, policies=policies)
    case_ids: list[str] = []
    for member in sorted(directory.iterdir(), key=lambda value: value.name):
        if member.is_symlink() or not member.is_dir():
            raise V2CaseReportError("cases directory contains a non-Case member")
        if is_shadow_case_staging_name(member.name):
            continue
        try:
            case_ids.append(shadow_case_id_from_directory_name(member.name))
        except ValueError as exc:
            raise V2CaseReportError("cases directory contains an invalid Case identity") from exc
    cases = tuple(store.read_case(case_id, runtime_active=runtime_active) for case_id in case_ids)
    return build_v2_case_report(
        cases,
        product=product,
        policies=policies,
        snapshot_mode=(
            "CALLER_ASSERTED_ACTIVE_RUNTIME" if runtime_active else "INACTIVE_OR_UNKNOWN_RUNTIME"
        ),
    )


def build_v2_case_report(
    cases: Sequence[ShadowCaseRead],
    *,
    product: OptionProductSpec,
    policies: PolicyChain,
    snapshot_mode: str = "SUPPLIED_CASE_READ_STATES",
) -> dict[str, object]:
    """Derive conditional V2 score-band and Outcome evidence without replay or storage."""

    rows = tuple(_case_outcome_row(case, product=product, policies=policies) for case in cases)
    incomplete = tuple(row for row in rows if row.terminal_state == "INCOMPLETE_UNCLEAN_EXIT")
    continuous = tuple(
        row
        for row in rows
        if row.observation_quality == "CONTINUOUS"
        and row.terminal_state != "INCOMPLETE_UNCLEAN_EXIT"
    )
    gapped = tuple(
        row
        for row in rows
        if row.observation_quality == "GAPPED" and row.terminal_state != "INCOMPLETE_UNCLEAN_EXIT"
    )
    unavailable = tuple(
        row
        for row in rows
        if row.observation_quality == "NOT_AVAILABLE"
        and row.terminal_state != "INCOMPLETE_UNCLEAN_EXIT"
    )
    pending = tuple(row for row in rows if row.terminal_state == "PENDING_OPEN")
    if len(continuous) + len(gapped) + len(incomplete) + len(unavailable) != len(rows):
        raise V2CaseReportError("Case lifecycle/observation projection is incomplete")
    return {
        "report_schema_version": V2_CASE_REPORT_SCHEMA_VERSION,
        "channel_id": V2_CHANNEL_ID,
        "product_spec_identity": product.identity,
        "policy_identities": {
            "radar": policies.radar.identity,
            "underwriting": policies.underwriting.identity,
            "position": policies.position.identity,
        },
        "claim_boundary": {
            "population": "SCHEMA_V5_CASE_OPENED_AFTER_SUCCESSFUL_PAIRED_REFRESH",
            "interpretation": "CONDITIONAL_DESCRIPTIVE_RESEARCH_ONLY",
            "primary_view": "CONTINUOUS",
            "secondary_view": "GAPPED",
            "pending_view": "PENDING_OPEN",
            "incomplete_view": "INCOMPLETE_UNCLEAN_EXIT",
            "observation_unavailable_view": "NOT_AVAILABLE",
            "snapshot_mode": snapshot_mode,
            "non_claims": [
                "NOT_UNCONDITIONAL_MARKET_OPPORTUNITY_RATE",
                "NOT_CAUSAL_ALPHA_OR_EXPECTED_PROFIT",
                "NOT_CROSS_ENROLLMENT_ALPHA_COMPARISON",
                "NOT_ORDER_FILL_TRADE_OR_ACCOUNT_PNL",
            ],
        },
        "views": {
            "continuous_primary": _view_object(continuous),
            "gapped_secondary": _view_object(gapped),
            "pending_open": _view_object(pending),
            "incomplete_unclean_exit": _view_object(incomplete),
            "observation_unavailable": _view_object(unavailable),
        },
        "cohorts": {
            "terminal_economics": _view_object(
                tuple(row for row in rows if row.terminal_economics_eligible)
            ),
            "continuous_path": _view_object(
                tuple(row for row in rows if row.continuous_path_eligible)
            ),
            "terminal_sample_integrity": _view_object(
                tuple(row for row in rows if row.terminal_sample_integrity_eligible)
            ),
            "exit_acquisition": _view_object(
                tuple(row for row in rows if row.exit_acquisition_eligible)
            ),
        },
    }


def _case_outcome_row(
    case: ShadowCaseRead,
    *,
    product: OptionProductSpec,
    policies: PolicyChain,
) -> _CaseOutcomeRow:
    opened = case.opened
    if opened.get("schema_version") != product.case_schema_version:
        raise V2CaseReportError("offline V2 report accepts schema-v5 Cases only")
    case_id = _identity(opened.get("case_id"), "case_id")
    enrollment_kind = _text(opened.get("enrollment_kind"), "enrollment_kind")
    if enrollment_kind not in {
        "ADMITTED_SHADOW_TRADE",
        "SELECTED_UNDERWRITING_DECISION_CONTROL",
        "RADAR_SCORE_BAND_NO_TRADE_CONTROL",
    }:
        raise V2CaseReportError("Case carries an invalid enrollment kind")
    structure = _mapping(opened.get("structure"), "structure")
    expiry_ms = _non_negative_integer(structure.get("expiry_ms"), "expiry_ms")
    selection_packet = _mapping(
        opened.get("selection_score_packet"),
        "selection_score_packet",
    )
    entry_packet = _mapping(
        opened.get("entry_refresh_score_packet"),
        "entry_refresh_score_packet",
    )
    selection_band = _score_band(selection_packet, "selection_score_packet")
    entry_band = _score_band(entry_packet, "entry_refresh_score_packet")
    selection_bucket = _mapping(
        selection_packet.get("bucket_key"),
        "selection_score_packet.bucket_key",
    )
    selection_result = _mapping(
        selection_packet.get("result"),
        "selection_score_packet.result",
    )
    selection_tte_band_id = _text(
        selection_bucket.get("tte_band_id"),
        "selection_score_packet.bucket_key.tte_band_id",
    )
    selection_option_type = _text(
        selection_bucket.get("option_type"),
        "selection_score_packet.bucket_key.option_type",
    )
    if selection_option_type not in {"call", "put"}:
        raise V2CaseReportError("selection packet option_type is invalid")
    selection_delta_bucket = _text(
        selection_bucket.get("delta_bucket"),
        "selection_score_packet.bucket_key.delta_bucket",
    )
    selection_score_coverage = _text(
        selection_result.get("coverage"),
        "selection_score_packet.result.coverage",
    )
    if selection_score_coverage not in {"COMPLETE", "PARTIAL"}:
        raise V2CaseReportError("selection packet score coverage is invalid")
    underwriting = _mapping(opened.get("underwriting"), "underwriting")
    refreshed_economic_action = _text(
        underwriting.get("action"),
        "underwriting.action",
    )
    selected_decision = opened.get("selected_underwriting_decision")
    if selected_decision is None:
        if enrollment_kind != "ADMITTED_SHADOW_TRADE":
            raise V2CaseReportError("Control Case lacks its selected decision")
        selected_economic_action = "CANDIDATE"
    else:
        selected_economic_action = _text(
            _mapping(selected_decision, "selected_underwriting_decision").get(
                "selected_economic_action"
            ),
            "selected_underwriting_decision.selected_economic_action",
        )
    for action in (selected_economic_action, refreshed_economic_action):
        if action not in {"CANDIDATE", "WATCH", "ABSTAIN"}:
            raise V2CaseReportError("Case carries an invalid Underwriting action")
    sampling_kind, inclusion_numerator, inclusion_denominator = _sampling_projection(
        selection_packet
    )
    observation_quality = _observation_quality(case, enrollment_kind=enrollment_kind)
    outcome = case.outcome
    terminal_state = _terminal_state(case)
    stressed: Decimal | None = None
    raw: Decimal | None = None
    known_terminal_states = {"MATURE_KNOWN", "EXITED_KNOWN", "SETTLED_KNOWN"}
    if terminal_state in known_terminal_states:
        if outcome is None:
            raise V2CaseReportError("known mature Case lacks its Outcome")
        payoff_cap = _positive_decimal(
            _mapping(opened.get("entry_economics"), "entry_economics").get(
                "contractual_payoff_cap_usd"
            ),
            "contractual_payoff_cap_usd",
        )
        stressed = (
            _decimal(
                _mapping(
                    outcome.get("native_outcome_economics"),
                    "native_outcome_economics",
                ).get("boundary_valued_net_pnl_usd"),
                "boundary_valued_net_pnl_usd",
            )
            / payoff_cap
        )
        if terminal_state in {"MATURE_KNOWN", "EXITED_KNOWN"}:
            raw = (
                _raw_vwap_boundary_net_pnl(
                    opened=opened,
                    outcome=outcome,
                    product=product,
                    entry_fee_rate=policies.underwriting.fee_rate_index_fraction,
                    close_fee_rate=policies.position.fee_rate_index_fraction,
                )
                / payoff_cap
            )
    elif terminal_state not in {
        "MATURE_UNKNOWN",
        "TERMINAL_UNKNOWN",
        "CENSORED_AT_STOP",
        "CENSORED_AT_FAILURE",
        "RIGHT_CENSORED",
        "INCOMPLETE_UNCLEAN_EXIT",
        "PENDING_OPEN",
    }:
        raise V2CaseReportError("Case Outcome terminal state is outside the V2 report contract")
    terminal_sample_integrity_eligible = _terminal_sample_integrity(case)
    exit_acquisition_window_status = _exit_acquisition_window_status(
        case,
        terminal_sample_integrity_eligible=terminal_sample_integrity_eligible,
    )
    natural_terminal_states = {
        "MATURE_KNOWN",
        "MATURE_UNKNOWN",
        "EXITED_KNOWN",
        "SETTLED_KNOWN",
        "TERMINAL_UNKNOWN",
    }
    return _CaseOutcomeRow(
        case_id=case_id,
        enrollment_kind=enrollment_kind,
        observation_quality=observation_quality,
        terminal_state=terminal_state,
        expiry_ms=expiry_ms,
        selection_tte_band_id=selection_tte_band_id,
        selection_option_type=selection_option_type,
        selection_delta_bucket=selection_delta_bucket,
        selection_score_band=selection_band,
        selection_score_coverage=selection_score_coverage,
        entry_refresh_score_band=entry_band,
        selected_economic_action=selected_economic_action,
        refreshed_economic_action=refreshed_economic_action,
        sampling_kind=sampling_kind,
        inclusion_numerator=inclusion_numerator,
        inclusion_denominator=inclusion_denominator,
        stressed_normalized_net_pnl=stressed,
        raw_vwap_normalized_net_pnl=raw,
        terminal_method=(
            _text(outcome.get("terminal_method"), "terminal_method")
            if outcome is not None and outcome.get("terminal_method") is not None
            else "MARKET_EXIT"
            if terminal_state == "MATURE_KNOWN"
            else None
        ),
        terminal_economics_eligible=terminal_state in known_terminal_states,
        continuous_path_eligible=(
            terminal_state in natural_terminal_states and observation_quality == "CONTINUOUS"
        ),
        terminal_sample_integrity_eligible=terminal_sample_integrity_eligible,
        exit_acquisition_eligible=(exit_acquisition_window_status == "COMPLETE"),
        exit_acquisition_window_status=exit_acquisition_window_status,
    )


def _view_object(
    rows: Sequence[_CaseOutcomeRow],
    *,
    include_enrollment_breakdown: bool = True,
) -> dict[str, object]:
    terminal_counts = Counter(row.terminal_state for row in rows)
    censored = sum(
        terminal_counts[state]
        for state in ("RIGHT_CENSORED", "CENSORED_AT_STOP", "CENSORED_AT_FAILURE")
    )
    stressed = tuple(
        row.stressed_normalized_net_pnl
        for row in rows
        if row.stressed_normalized_net_pnl is not None
    )
    raw = tuple(
        row.raw_vwap_normalized_net_pnl
        for row in rows
        if row.raw_vwap_normalized_net_pnl is not None
    )
    expiry_counts = Counter(row.expiry_ms for row in rows)
    selection_bands = Counter(row.selection_score_band for row in rows)
    entry_bands = Counter(row.entry_refresh_score_band for row in rows)
    score_band_pairs = Counter(
        f"{row.selection_score_band}->{row.entry_refresh_score_band}" for row in rows
    )
    result: dict[str, object] = {
        "denominators": {
            "opened": len(rows),
            "mature_known": sum(
                terminal_counts[state]
                for state in ("MATURE_KNOWN", "EXITED_KNOWN", "SETTLED_KNOWN")
            ),
            "mature_unknown": terminal_counts["MATURE_UNKNOWN"]
            + terminal_counts["TERMINAL_UNKNOWN"],
            "censored": censored,
            "right_censored_without_outcome": terminal_counts["RIGHT_CENSORED"],
            "pending_open": terminal_counts["PENDING_OPEN"],
            "incomplete_unclean_exit": terminal_counts["INCOMPLETE_UNCLEAN_EXIT"],
        },
        "terminal_method_counts": {
            "market_exit": sum(1 for row in rows if row.terminal_method == "MARKET_EXIT"),
            "contract_settlement": sum(
                1 for row in rows if row.terminal_method == "CONTRACT_SETTLEMENT"
            ),
            "terminal_unknown": terminal_counts["TERMINAL_UNKNOWN"],
        },
        "score_band_counts": {
            "selection": dict(sorted(selection_bands.items())),
            "entry_refresh": dict(sorted(entry_bands.items())),
        },
        "selection_to_entry_score_band_pairs": dict(sorted(score_band_pairs.items())),
        "expiry_cluster_count": len(expiry_counts),
        "expiry_cluster_opened_counts": {
            str(expiry): count for expiry, count in sorted(expiry_counts.items())
        },
        "stressed_normalized_outcome": _tail_summary(stressed),
        "raw_vwap_fee_recomputed_sensitivity": _tail_summary(raw),
        "case_rows": [row.as_object() for row in rows],
    }
    result["by_selection_score_band"] = {
        band: _band_view_object(tuple(row for row in rows if row.selection_score_band == band))
        for band in ("LOW", "MID", "HIGH", "REVIEW")
    }
    if include_enrollment_breakdown:
        result["by_enrollment_kind"] = {
            kind: _view_object(
                tuple(row for row in rows if row.enrollment_kind == kind),
                include_enrollment_breakdown=False,
            )
            for kind in (
                "ADMITTED_SHADOW_TRADE",
                "SELECTED_UNDERWRITING_DECISION_CONTROL",
                "RADAR_SCORE_BAND_NO_TRADE_CONTROL",
            )
        }
    return result


def _band_view_object(rows: Sequence[_CaseOutcomeRow]) -> dict[str, object]:
    terminal_counts = Counter(row.terminal_state for row in rows)
    censored = sum(
        terminal_counts[state]
        for state in ("RIGHT_CENSORED", "CENSORED_AT_STOP", "CENSORED_AT_FAILURE")
    )
    stressed = tuple(
        row.stressed_normalized_net_pnl
        for row in rows
        if row.stressed_normalized_net_pnl is not None
    )
    raw = tuple(
        row.raw_vwap_normalized_net_pnl
        for row in rows
        if row.raw_vwap_normalized_net_pnl is not None
    )
    return {
        "denominators": {
            "opened": len(rows),
            "mature_known": sum(
                terminal_counts[state]
                for state in ("MATURE_KNOWN", "EXITED_KNOWN", "SETTLED_KNOWN")
            ),
            "mature_unknown": terminal_counts["MATURE_UNKNOWN"]
            + terminal_counts["TERMINAL_UNKNOWN"],
            "censored": censored,
            "right_censored_without_outcome": terminal_counts["RIGHT_CENSORED"],
            "pending_open": terminal_counts["PENDING_OPEN"],
            "incomplete_unclean_exit": terminal_counts["INCOMPLETE_UNCLEAN_EXIT"],
        },
        "terminal_method_counts": {
            "market_exit": sum(1 for row in rows if row.terminal_method == "MARKET_EXIT"),
            "contract_settlement": sum(
                1 for row in rows if row.terminal_method == "CONTRACT_SETTLEMENT"
            ),
            "terminal_unknown": terminal_counts["TERMINAL_UNKNOWN"],
        },
        "expiry_cluster_count": len({row.expiry_ms for row in rows}),
        "stressed_normalized_outcome": _tail_summary(stressed),
        "raw_vwap_fee_recomputed_sensitivity": _tail_summary(raw),
        "case_rows": [row.as_object() for row in rows],
    }


def _raw_vwap_boundary_net_pnl(
    *,
    opened: Mapping[str, object],
    outcome: Mapping[str, object],
    product: OptionProductSpec,
    entry_fee_rate: Decimal,
    close_fee_rate: Decimal,
) -> Decimal:
    structure = _mapping(opened.get("structure"), "structure")
    quantity = _positive_decimal(structure.get("full_quantity_btc"), "full_quantity_btc")
    entry_native, entry_index = _raw_native_cashflow(
        structure.get("entry_component_legs"),
        quantity=quantity,
        product=product,
        fee_rate=entry_fee_rate,
        field="entry_component_legs",
    )
    close_native, close_index = _raw_native_cashflow(
        outcome.get("close_component_legs"),
        quantity=quantity,
        product=product,
        fee_rate=close_fee_rate,
        field="close_component_legs",
    )
    return product.valuation(entry_native, index_price=entry_index) + product.valuation(
        close_native,
        index_price=close_index,
    )


def _raw_native_cashflow(
    value: object,
    *,
    quantity: Decimal,
    product: OptionProductSpec,
    fee_rate: Decimal,
    field: str,
) -> tuple[Decimal, Decimal]:
    if not isinstance(value, list) or len(value) != 2:
        raise V2CaseReportError(f"{field} must contain exactly two legs")
    gross = Decimal(0)
    fees = Decimal(0)
    valuation_index: Decimal | None = None
    for index, raw_leg in enumerate(value):
        leg = _mapping(raw_leg, f"{field}[{index}]")
        action = _text(leg.get("action"), f"{field}[{index}].action")
        if action not in {"BUY", "SELL"}:
            raise V2CaseReportError(f"{field}[{index}] has an invalid action")
        raw_vwap = _positive_decimal(
            leg.get("raw_vwap_native"),
            f"{field}[{index}].raw_vwap_native",
        )
        leg_index = _positive_decimal(
            leg.get("valuation_index_price"),
            f"{field}[{index}].valuation_index_price",
        )
        if valuation_index is None:
            valuation_index = leg_index
        elif valuation_index != leg_index:
            raise V2CaseReportError(f"{field} legs do not share one valuation boundary")
        gross += raw_vwap * quantity * (Decimal(1) if action == "SELL" else Decimal(-1))
        fees += product.native_option_fee(
            native_option_price=raw_vwap,
            index_price=leg_index,
            quantity_btc=quantity,
            fee_rate=fee_rate,
        )
    if valuation_index is None:
        raise V2CaseReportError(f"{field} lacks a valuation boundary")
    return gross - fees, valuation_index


def _tail_summary(values: Sequence[Decimal]) -> dict[str, object]:
    if not values:
        return {
            "known_count": 0,
            "mean": None,
            "p05": None,
            "p50": None,
            "minimum": None,
            "maximum": None,
            "loss_count": 0,
            "loss_fraction": None,
        }
    ordered = tuple(sorted(values))
    loss_count = sum(value < 0 for value in ordered)
    return {
        "known_count": len(ordered),
        "mean": _decimal_text(sum(ordered, Decimal(0)) / Decimal(len(ordered))),
        "p05": _decimal_text(_nearest_rank(ordered, Decimal("0.05"))),
        "p50": _decimal_text(_nearest_rank(ordered, Decimal("0.50"))),
        "minimum": _decimal_text(ordered[0]),
        "maximum": _decimal_text(ordered[-1]),
        "loss_count": loss_count,
        "loss_fraction": {
            "numerator": loss_count,
            "denominator": len(ordered),
        },
    }


def _nearest_rank(values: Sequence[Decimal], probability: Decimal) -> Decimal:
    rank = int((probability * Decimal(len(values))).to_integral_value(rounding=ROUND_CEILING))
    return values[max(1, rank) - 1]


def _terminal_state(case: ShadowCaseRead) -> str:
    if case.outcome is not None:
        return _text(case.outcome.get("terminal_state"), "terminal_state")
    case_status = getattr(case.status, "value", case.status)
    latest_segment_status = (
        getattr(case.segments[-1].status, "value", case.segments[-1].status)
        if case.segments
        else None
    )
    if (
        case_status == "INCOMPLETE_UNCLEAN_EXIT"
        or latest_segment_status == "INCOMPLETE_UNCLEAN_EXIT"
    ):
        return "INCOMPLETE_UNCLEAN_EXIT"
    if case_status == "OPEN":
        return "PENDING_OPEN"
    return "RIGHT_CENSORED"


def _observation_quality(
    case: ShadowCaseRead,
    *,
    enrollment_kind: str,
) -> str:
    del enrollment_kind
    observed = {segment.opened.get("observation_quality") for segment in case.segments}
    if case.outcome is not None and case.outcome.get("observation_quality") is not None:
        observed.add(case.outcome.get("observation_quality"))
    observed.discard(None)
    if any(value not in {"CONTINUOUS", "GAPPED"} for value in observed):
        raise V2CaseReportError("Case carries an invalid observation quality")
    if "GAPPED" in observed:
        return "GAPPED"
    if observed == {"CONTINUOUS"}:
        return "CONTINUOUS"
    return "NOT_AVAILABLE"


def _terminal_sample_integrity(case: ShadowCaseRead) -> bool:
    outcome = case.outcome
    if outcome is None or outcome.get("outcome_contract_version") != 3:
        return False
    terminal_state = outcome.get("terminal_state")
    if terminal_state == "EXITED_KNOWN":
        refs = outcome.get("close_component_quote_source_refs")
        legs = outcome.get("close_component_legs")
        return (
            _is_identity(outcome.get("selected_exit_identity"))
            and _is_identity(outcome.get("exit_acquisition_sample_identity"))
            and _is_identity(outcome.get("close_component_pair_identity"))
            and isinstance(outcome.get("close_component_pair_timing"), Mapping)
            and isinstance(outcome.get("close_component_pair_limits"), Mapping)
            and isinstance(refs, Sequence)
            and not isinstance(refs, (str, bytes))
            and len(refs) == 2
            and isinstance(legs, Sequence)
            and not isinstance(legs, (str, bytes))
            and len(legs) == 2
        )
    if terminal_state == "SETTLED_KNOWN":
        source = outcome.get("official_delivery_price_source_ref")
        return (
            isinstance(source, Mapping)
            and {
                "source_identity",
                "response_source_identity",
                "receipt_fact_boundary",
                "request_id",
                "index_name",
                "delivery_date",
                "records_total",
                "owner_origin_boundary",
                "sent_boundary",
            }.issubset(source)
            and _is_identity(source.get("source_identity"))
            and _is_identity(source.get("response_source_identity"))
            and _is_identity(outcome.get("contract_settlement_rule_identity"))
            and outcome.get("delivery_price_usdc_per_btc") is not None
            and outcome.get("delivery_fee_rate_fraction") is not None
        )
    return False


def _exit_acquisition_window_status(
    case: ShadowCaseRead,
    *,
    terminal_sample_integrity_eligible: bool,
) -> str:
    outcome = case.outcome
    if outcome is None or outcome.get("terminal_state") != "EXITED_KNOWN":
        return "NOT_MARKET_EXIT"
    if outcome.get("outcome_contract_version") != 3:
        return "LEGACY_TERMINAL_SAMPLE"
    if not terminal_sample_integrity_eligible:
        return "TERMINAL_SAMPLE_INCOMPLETE"
    first_close = case.first_close
    if first_close is None:
        return "FIRST_CLOSE_MISSING"
    profile = first_close.get("exit_acquisition_profile")
    if not isinstance(profile, Mapping) or not _is_identity(profile.get("profile_identity")):
        return "PROFILE_UNDECLARED"
    if outcome.get("exit_acquisition_profile") != profile:
        return "PROFILE_MISMATCH"
    first_close_segment = first_close.get("segment_sequence")
    outcome_segment = outcome.get("segment_sequence")
    if (
        isinstance(first_close_segment, bool)
        or not isinstance(first_close_segment, int)
        or isinstance(outcome_segment, bool)
        or not isinstance(outcome_segment, int)
    ):
        return "SEGMENT_BINDING_MISSING"
    if first_close_segment != outcome_segment:
        return "GAPPED_AFTER_FIRST_CLOSE"
    truth_vector = first_close.get("predicate_truth_vector")
    if not isinstance(truth_vector, Sequence) or isinstance(truth_vector, (str, bytes)):
        return "FIRST_CLOSE_PREDICATE_VECTOR_MISSING"
    discontinuity_index = POSITION_CLOSE_REASONS.index("PLATFORM_OR_SOURCE_DISCONTINUITY")
    if len(truth_vector) != len(POSITION_CLOSE_REASONS):
        return "FIRST_CLOSE_PREDICATE_VECTOR_MISSING"
    discontinuity = truth_vector[discontinuity_index]
    if discontinuity == "TRUE":
        return "SOURCE_DISCONTINUITY_AT_FIRST_CLOSE"
    if discontinuity != "FALSE":
        return "SOURCE_CONTINUITY_UNKNOWN_AT_FIRST_CLOSE"
    return "COMPLETE"


def _is_identity(value: object) -> bool:
    try:
        require_identity(value, "identity")
    except ValueError:
        return False
    return True


def _sampling_projection(
    packet: Mapping[str, object],
) -> tuple[str | None, int | None, int | None]:
    value = packet.get("sampling_metadata")
    if value is None:
        return None, None, None
    metadata = _mapping(value, "selection_score_packet.sampling_metadata")
    kind = _text(metadata.get("kind"), "sampling_metadata.kind")
    numerator = metadata.get("inclusion_numerator")
    denominator = metadata.get("inclusion_denominator")
    if numerator is not None:
        numerator = _non_negative_integer(numerator, "inclusion_numerator")
    if denominator is not None:
        denominator = _non_negative_integer(denominator, "inclusion_denominator")
        if denominator == 0:
            raise V2CaseReportError("inclusion_denominator must be positive")
    if (numerator is None) != (denominator is None):
        raise V2CaseReportError("sampling inclusion ratio must be atomic")
    return kind, numerator, denominator


def _score_band(packet: Mapping[str, object], field: str) -> str:
    result = _mapping(packet.get("result"), f"{field}.result")
    value = result.get("band")
    if value not in {"LOW", "MID", "HIGH", "REVIEW"}:
        raise V2CaseReportError(f"{field}.result.band is invalid")
    return str(value)


def _existing_absolute_directory(path: Path) -> Path:
    if not path.is_absolute():
        raise V2CaseReportError("cases directory must be absolute")
    if path.is_symlink() or not path.is_dir():
        raise V2CaseReportError("cases directory must be one existing non-symlink directory")
    return path.resolve()


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise V2CaseReportError(f"{field} must be an object")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise V2CaseReportError(f"{field} must be non-empty text")
    return value


def _identity(value: object, field: str) -> str:
    try:
        return require_identity(value, field)
    except ValueError as exc:
        raise V2CaseReportError(str(exc)) from exc


def _non_negative_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise V2CaseReportError(f"{field} must be a non-negative integer")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise V2CaseReportError(f"{field} must be a Decimal")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise V2CaseReportError(f"{field} must be a Decimal") from exc
    if not parsed.is_finite():
        raise V2CaseReportError(f"{field} must be finite")
    return parsed


def _positive_decimal(value: object, field: str) -> Decimal:
    parsed = _decimal(value, field)
    if parsed <= 0:
        raise V2CaseReportError(f"{field} must be positive")
    return parsed


def _decimal_text(value: Decimal | None) -> str | None:
    return canonical_decimal(value) if value is not None else None
