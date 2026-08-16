# ruff: noqa: RUF001 -- Chinese trader-facing prompts intentionally use Chinese punctuation.

from __future__ import annotations

import json
import re
import subprocess
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from optimatrix.ai_lab.canonical import (
    JsonObject,
    ValidationError,
    canonical_bytes,
    decimal_text,
    require_bool,
    require_content_id,
    require_text,
    require_text_list,
    seal_object,
    strict_fields,
    verify_seal,
)
from optimatrix.ai_lab.memory import MemoryDigest
from optimatrix.ai_lab.session_review import HindsightFinding, SessionReview, SessionVerdict

CODEX_ANALYSIS_SCHEMA = "optimatrix.ai-lab.codex-analysis.v1"
CODEX_ANALYSIS_NAMESPACE = "OptimatrixAiLabCodexAnalysisV1"
HYPOTHESIS_KEY = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
MAX_REPRESENTATIVE_OPPORTUNITIES = 48

MODEL_OUTPUT_JSON_SCHEMA: JsonObject = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "diagnoses", "hypotheses", "challenger_proposal"],
    "properties": {
        "summary": {"type": "string", "minLength": 1},
        "diagnoses": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["claim", "fact_ids", "quantifiable", "metric"],
                "properties": {
                    "claim": {"type": "string", "minLength": 1},
                    "fact_ids": {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
                    },
                    "quantifiable": {"type": "boolean"},
                    "metric": {"type": ["string", "null"]},
                },
            },
        },
        "hypotheses": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "hypothesis_key",
                    "claim",
                    "fact_ids",
                    "next_test",
                    "status",
                ],
                "properties": {
                    "hypothesis_key": {
                        "type": "string",
                        "pattern": "^[A-Z][A-Z0-9_]{2,63}$",
                    },
                    "claim": {"type": "string", "minLength": 1},
                    "fact_ids": {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
                    },
                    "next_test": {"type": "string", "minLength": 1},
                    "status": {"const": "HYPOTHESIS_ONLY"},
                },
            },
        },
        "challenger_proposal": {
            "type": "object",
            "additionalProperties": False,
            "required": ["action", "reason", "fact_ids"],
            "properties": {
                "action": {"enum": ["NOT_ELIGIBLE", "NO_CHALLENGER", "PROPOSE_CHALLENGER"]},
                "reason": {"type": "string", "minLength": 1},
                "fact_ids": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
                },
            },
        },
    },
}

CommandRunner = Callable[
    [Sequence[str], str, int],
    subprocess.CompletedProcess[str],
]


class CodexCliAnalyzer:
    def __init__(
        self,
        *,
        codex_binary: str = "codex",
        timeout_seconds: int = 300,
        runner: CommandRunner | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Codex timeout must be positive")
        self.codex_binary = codex_binary
        self.timeout_seconds = timeout_seconds
        self.runner = runner or _run_command

    def analyze(self, *, review: SessionReview, memory: MemoryDigest) -> JsonObject:
        if review.verdict in {
            SessionVerdict.UNKNOWN,
            SessionVerdict.PARTIALLY_IDENTIFIED_NO_KNOWN_RULE_ERROR,
            SessionVerdict.NO_OPPORTUNITY_CORRECTLY_AVOIDED,
        }:
            raise ValidationError(
                "unknown, partially identified without known error, and correct no-opportunity "
                "conclusions stop before Codex analysis"
            )
        bundle = _analysis_bundle(review=review, memory=memory)
        raw_fact_ids = bundle["supplied_fact_ids"]
        assert isinstance(raw_fact_ids, list)
        supplied_fact_ids = tuple(str(item) for item in raw_fact_ids)
        prompt = json.dumps(bundle, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True)
        with TemporaryDirectory(prefix="optimatrix-ai-lab-codex-") as directory:
            root = Path(directory)
            schema_path = root / "output-schema.json"
            output_path = root / "last-message.json"
            schema_path.write_bytes(canonical_bytes(MODEL_OUTPUT_JSON_SCHEMA))
            command = (
                self.codex_binary,
                "exec",
                "--ignore-user-config",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--color",
                "never",
                "--cd",
                str(root),
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "-",
            )
            completed = self.runner(command, prompt, self.timeout_seconds)
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout).strip()
                raise ValidationError(
                    f"Codex analysis failed with exit {completed.returncode}: {detail[:500]}"
                )
            if not output_path.is_file():
                raise ValidationError("Codex did not write its schema-bound final response")
            try:
                raw: Any = json.loads(output_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValidationError(f"Codex final response is not valid JSON: {exc}") from exc
        model_output = _validate_model_output(
            raw,
            review=review,
            supplied_fact_ids=set(supplied_fact_ids),
        )
        draft: JsonObject = {
            "schema_version": CODEX_ANALYSIS_SCHEMA,
            "review_id": review.identity,
            "memory_digest_id": memory.identity,
            "supplied_fact_ids": list(supplied_fact_ids),
            "model_output": model_output,
            "boundary": (
                "Codex explains deterministic facts and proposes falsifiable offline hypotheses. "
                "It does not own the Session verdict, Policy, code changes, execution, or promotion."
            ),
        }
        analysis = seal_object(
            draft,
            id_field="analysis_id",
            namespace=CODEX_ANALYSIS_NAMESPACE,
        )
        return validate_analysis(analysis)


def validate_analysis(value: Mapping[str, object] | object) -> JsonObject:
    item = strict_fields(
        value,
        {
            "schema_version",
            "analysis_id",
            "review_id",
            "memory_digest_id",
            "supplied_fact_ids",
            "model_output",
            "boundary",
        },
        "codex_analysis",
    )
    if item["schema_version"] != CODEX_ANALYSIS_SCHEMA:
        raise ValidationError("unsupported Codex analysis schema")
    verify_seal(item, id_field="analysis_id", namespace=CODEX_ANALYSIS_NAMESPACE)
    require_content_id(item["review_id"], "codex_analysis.review_id")
    require_content_id(item["memory_digest_id"], "codex_analysis.memory_digest_id")
    facts = require_text_list(item["supplied_fact_ids"], "codex_analysis.supplied_fact_ids")
    for fact in facts:
        require_content_id(fact, "codex_analysis.supplied_fact_id")
    require_text(item["boundary"], "codex_analysis.boundary")
    if not isinstance(item["model_output"], dict):
        raise ValidationError("Codex analysis model_output must be an object")
    _validate_stored_model_output(item["model_output"], supplied_fact_ids=set(facts))
    return item


def _analysis_prompt(*, review: SessionReview, memory: MemoryDigest) -> str:
    return json.dumps(
        _analysis_bundle(review=review, memory=memory),
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def _analysis_bundle(*, review: SessionReview, memory: MemoryDigest) -> JsonObject:
    workflow = (
        "你是 Optimatrix AI Lab 的离线期权研究员。确定性程序已按 Window 使用决策时事实、"
        "事后 RV/路径、费用和结算给出规则质量 verdict 与缺失数据上下界；你无权修改 verdict、"
        "Policy、代码或交易权限。只引用 supplied_fact_ids 中的 sha256 事实。保守、激进或混合"
        "错误 verdict 只诊断已经观察到的错误；OBSERVED 前缀表示未知 Window 仍可能扩大或改变"
        "整日错误组合。这些 verdict 都不得跳到 Challenger。只有 challenger_comparison_eligible=true"
        "时 challenger_proposal.action 才能是 PROPOSE_CHALLENGER。不要把单 Session 或 public "
        "Shadow 写成 Edge、订单、成交或真实 PnL。输出必须严格符合 JSON Schema。"
    )
    representatives = _representative_opportunities(review)
    supplied_fact_ids = [
        review.identity,
        review.opportunity_definition_id,
        *(window.identity for window in review.windows),
        *(opportunity.identity for opportunity in representatives),
        *(gate.identity for opportunity in representatives for gate in opportunity.gate_distances),
        memory.identity,
        *memory.fact_ids,
    ]
    bundle: JsonObject = {
        "workflow": workflow,
        "session_review": {
            "review_id": review.identity,
            "session_id": review.session_id,
            "policy_id": review.policy_id,
            "opportunity_definition_id": review.opportunity_definition_id,
            "verdict": review.verdict.value,
            "verdict_reason": review.verdict_reason,
            "challenger_comparison_eligible": review.challenger_comparison_eligible,
            "expected_window_count": review.expected_window_count,
            "recorded_decision_count": review.recorded_decision_count,
            "recorded_outcome_count": review.recorded_outcome_count,
            "curve_observation_count": review.curve_observation_count,
            "auditable_window_count": review.auditable_window_count,
            "unknown_window_count": review.unknown_window_count,
            "coverage_fraction": decimal_text(review.coverage_fraction),
            "miss_rate_bounds": [
                decimal_text(review.miss_rate_lower_bound),
                decimal_text(review.miss_rate_upper_bound),
            ],
            "over_risk_rate_bounds": [
                decimal_text(review.over_risk_rate_lower_bound),
                decimal_text(review.over_risk_rate_upper_bound),
            ],
            "opportunity_rate_bounds": [
                decimal_text(review.opportunity_rate_lower_bound),
                decimal_text(review.opportunity_rate_upper_bound),
            ],
            "base_candidate_window_count": review.base_candidate_window_count,
            "captured_opportunity_window_count": review.captured_opportunity_window_count,
            "correct_avoidance_window_count": review.correct_avoidance_window_count,
            "missed_opportunity_window_count": review.missed_opportunity_window_count,
            "over_risk_window_count": review.over_risk_window_count,
            "legal_structure_count": review.legal_structure_count,
            "price_evaluable_count": review.price_evaluable_count,
            "control_candidate_count": review.control_candidate_count,
            "hindsight_opportunity_structure_count": (review.hindsight_opportunity_structure_count),
            "evidence_reason_counts": dict(review.evidence_reason_counts),
            "base_blocker_counts": dict(review.base_blocker_counts),
            "gate_attribution_summary": _gate_attribution_summary(review),
            "iv_rv_curve": [point.as_object() for point in review.curve],
            "windows": [window.as_object() for window in review.windows],
            "representative_opportunities": [
                opportunity.as_object() for opportunity in representatives
            ],
            "representative_opportunity_limit": MAX_REPRESENTATIVE_OPPORTUNITIES,
            "omitted_opportunity_count": len(review.opportunities) - len(representatives),
            "representative_selection": (
                "highest low-path-risk hindsight USD results plus closest and furthest failing "
                "Base-gate examples; the sealed Review/report retains the complete population"
            ),
            "evidence_boundary": review.evidence_boundary,
        },
        "prior_memory": memory.as_object(),
        "supplied_fact_ids": list(dict.fromkeys(supplied_fact_ids)),
    }
    return bundle


def _representative_opportunities(review: SessionReview) -> tuple[HindsightFinding, ...]:
    by_identity = {item.identity: item for item in review.opportunities}
    selected = {
        item.identity
        for item in sorted(
            review.opportunities,
            key=lambda item: (-item.settlement_reference_result_usd, item.identity),
        )[:24]
    }
    by_gate: dict[str, list[tuple[Decimal, str]]] = defaultdict(list)
    for opportunity in review.opportunities:
        for gate in opportunity.gate_distances:
            if gate.signed_margin_to_pass is not None:
                by_gate[gate.code].append((gate.signed_margin_to_pass, opportunity.identity))
    for rows in by_gate.values():
        ordered = sorted(rows)
        selected.add(ordered[0][1])
        selected.add(ordered[-1][1])
    ordered_selected = sorted(
        (by_identity[identity] for identity in selected),
        key=lambda item: (-item.settlement_reference_result_usd, item.identity),
    )
    return tuple(ordered_selected[:MAX_REPRESENTATIVE_OPPORTUNITIES])


def _gate_attribution_summary(review: SessionReview) -> list[JsonObject]:
    counts: Counter[str] = Counter()
    quantifiable: Counter[str] = Counter()
    margins: dict[str, list[Decimal]] = defaultdict(list)
    units: dict[str, set[str]] = defaultdict(set)
    for opportunity in review.opportunities:
        if opportunity.base_selected_exact_candidate:
            continue
        for gate in opportunity.gate_distances:
            counts[gate.code] += 1
            if gate.quantifiable:
                assert gate.signed_margin_to_pass is not None
                quantifiable[gate.code] += 1
                margins[gate.code].append(gate.signed_margin_to_pass)
                if gate.unit is not None:
                    units[gate.code].add(gate.unit)
    output: list[JsonObject] = []
    for code in sorted(counts, key=lambda item: (-counts[item], item)):
        values = margins[code]
        output.append(
            {
                "code": code,
                "opportunity_count": counts[code],
                "quantifiable_count": quantifiable[code],
                "nonquantifiable_count": counts[code] - quantifiable[code],
                "minimum_signed_margin_to_pass": (decimal_text(min(values)) if values else None),
                "maximum_signed_margin_to_pass": (decimal_text(max(values)) if values else None),
                "units": sorted(units[code]),
            }
        )
    return output


def _validate_model_output(
    value: object,
    *,
    review: SessionReview,
    supplied_fact_ids: set[str],
) -> JsonObject:
    output = _validate_stored_model_output(value, supplied_fact_ids=supplied_fact_ids)
    proposal = output["challenger_proposal"]
    assert isinstance(proposal, dict)
    action = proposal["action"]
    if not review.challenger_comparison_eligible and action != "NOT_ELIGIBLE":
        raise ValidationError("Codex attempted Challenger work before deterministic eligibility")
    if review.challenger_comparison_eligible and action == "NOT_ELIGIBLE":
        raise ValidationError("Codex contradicted deterministic Challenger eligibility")
    return output


def _validate_stored_model_output(
    value: object,
    *,
    supplied_fact_ids: set[str],
) -> JsonObject:
    output = strict_fields(
        value,
        {"summary", "diagnoses", "hypotheses", "challenger_proposal"},
        "codex_model_output",
    )
    require_text(output["summary"], "codex_model_output.summary")
    diagnoses = output["diagnoses"]
    if not isinstance(diagnoses, list):
        raise ValidationError("Codex diagnoses must be an array")
    for index, raw in enumerate(diagnoses):
        item = strict_fields(
            raw,
            {"claim", "fact_ids", "quantifiable", "metric"},
            f"codex diagnosis {index}",
        )
        require_text(item["claim"], f"codex diagnosis {index}.claim")
        cited = require_text_list(item["fact_ids"], f"codex diagnosis {index}.fact_ids")
        _validate_citations(cited, supplied_fact_ids=supplied_fact_ids)
        quantifiable = require_bool(item["quantifiable"], f"codex diagnosis {index}.quantifiable")
        metric = item["metric"]
        if quantifiable:
            require_text(metric, f"codex diagnosis {index}.metric")
        elif metric is not None:
            raise ValidationError("non-quantifiable Codex diagnosis must use metric=null")
    hypotheses = output["hypotheses"]
    if not isinstance(hypotheses, list):
        raise ValidationError("Codex hypotheses must be an array")
    keys: set[str] = set()
    for index, raw in enumerate(hypotheses):
        item = strict_fields(
            raw,
            {"hypothesis_key", "claim", "fact_ids", "next_test", "status"},
            f"Codex hypothesis {index}",
        )
        key = require_text(item["hypothesis_key"], f"Codex hypothesis {index}.key")
        if HYPOTHESIS_KEY.fullmatch(key) is None or key in keys:
            raise ValidationError("Codex hypothesis keys must be unique stable uppercase slugs")
        keys.add(key)
        require_text(item["claim"], f"Codex hypothesis {index}.claim")
        require_text(item["next_test"], f"Codex hypothesis {index}.next_test")
        if item["status"] != "HYPOTHESIS_ONLY":
            raise ValidationError("Codex hypotheses cannot claim promotion or qualification")
        cited = require_text_list(item["fact_ids"], f"Codex hypothesis {index}.fact_ids")
        _validate_citations(cited, supplied_fact_ids=supplied_fact_ids)
    proposal = strict_fields(
        output["challenger_proposal"],
        {"action", "reason", "fact_ids"},
        "Codex challenger proposal",
    )
    if proposal["action"] not in {
        "NOT_ELIGIBLE",
        "NO_CHALLENGER",
        "PROPOSE_CHALLENGER",
    }:
        raise ValidationError("Codex challenger action is invalid")
    require_text(proposal["reason"], "Codex challenger proposal.reason")
    cited = require_text_list(proposal["fact_ids"], "Codex challenger proposal.fact_ids")
    _validate_citations(cited, supplied_fact_ids=supplied_fact_ids)
    return output


def _validate_citations(citations: tuple[str, ...], *, supplied_fact_ids: set[str]) -> None:
    if not citations:
        raise ValidationError("Codex claim requires at least one supplied fact citation")
    for citation in citations:
        require_content_id(citation, "Codex fact citation")
        if citation not in supplied_fact_ids:
            raise ValidationError("Codex cited a fact that was not supplied")


def _run_command(
    command: Sequence[str],
    prompt: str,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            tuple(command),
            input=prompt,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValidationError(f"cannot complete bounded Codex analysis: {exc}") from exc
