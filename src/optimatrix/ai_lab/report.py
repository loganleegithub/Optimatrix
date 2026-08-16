# ruff: noqa: RUF001 -- Chinese trader-facing reports intentionally use Chinese punctuation.

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

from optimatrix.ai_lab.canonical import (
    AI_LAB_DURABLE_ROOT,
    JsonObject,
    ValidationError,
    canonical_bytes,
    content_id,
    isolated_path,
)
from optimatrix.ai_lab.memory import LEGACY_POLICY_QUALITY_STATUS, MemoryDigest
from optimatrix.ai_lab.session_review import SessionReview, SessionVerdict

REPORT_SCHEMA = "optimatrix.ai-lab.policy-quality-report.v1"
REPORT_NAMESPACE = "OptimatrixAiLabPolicyQualityReportV1"
ANALYSIS_REPORT_SCHEMA = "optimatrix.ai-lab.codex-analysis-report.v1"
ANALYSIS_REPORT_NAMESPACE = "OptimatrixAiLabCodexAnalysisReportV1"


def write_session_report(
    *,
    review: SessionReview,
    memory: MemoryDigest,
    root: Path = AI_LAB_DURABLE_ROOT,
) -> tuple[Path, Path]:
    """Write the deterministic report before any optional Codex subprocess."""

    lab_root = isolated_path(root)
    projection: JsonObject = {
        "schema_version": REPORT_SCHEMA,
        "review": review.as_object(),
        "prior_memory": memory.as_object(),
        "optional_codex_analysis": "SEPARATE_SUPPLEMENT_NOT_REQUIRED_FOR_VERDICT",
    }
    projection["report_id"] = content_id(REPORT_NAMESPACE, projection)
    report_dir = _report_dir(lab_root, review)
    json_path = report_dir / "policy-quality-review.json"
    markdown_path = report_dir / "policy-quality-review.md"
    _write_idempotent(json_path, canonical_bytes(projection) + b"\n")
    _write_idempotent(
        markdown_path,
        render_session_report(review=review, memory=memory).encode("utf-8"),
    )
    return json_path, markdown_path


def write_analysis_report(
    *,
    review: SessionReview,
    analysis: Mapping[str, object],
    root: Path = AI_LAB_DURABLE_ROOT,
) -> tuple[Path, Path]:
    analysis_id = analysis.get("analysis_id")
    if not isinstance(analysis_id, str) or analysis.get("review_id") != review.identity:
        raise ValidationError("analysis supplement does not bind the Policy-quality review")
    projection: JsonObject = {
        "schema_version": ANALYSIS_REPORT_SCHEMA,
        "review_id": review.identity,
        "analysis": dict(analysis),
    }
    projection["analysis_report_id"] = content_id(ANALYSIS_REPORT_NAMESPACE, projection)
    directory = _report_dir(isolated_path(root), review) / "codex" / analysis_id[-16:]
    json_path = directory / "codex-analysis.json"
    markdown_path = directory / "codex-analysis.md"
    _write_idempotent(json_path, canonical_bytes(projection) + b"\n")
    _write_idempotent(markdown_path, _render_analysis(analysis).encode("utf-8"))
    return json_path, markdown_path


def render_session_report(*, review: SessionReview, memory: MemoryDigest) -> str:
    lines = [
        f"# AI Lab Policy Quality Review — {review.session_id}",
        "",
        "## 交易员结论",
        "",
        f"**{_verdict_label(review.verdict)}** — {review.verdict_reason}",
        "",
        "| 事后对照 | Window 数 |",
        "|---|---:|",
        f"| Base 抓对机会 | {review.captured_opportunity_window_count} |",
        f"| Base 正确避开 | {review.correct_avoidance_window_count} |",
        f"| Base 漏掉机会 | {review.missed_opportunity_window_count} |",
        f"| Base 选择过度风险 | {review.over_risk_window_count} |",
        f"| 证据不足 | {review.unknown_window_count} |",
        "",
        "Challenger 比较："
        + (
            "`ELIGIBLE`（只允许另行冻结实验，不代表规则长期更好）"
            if review.challenger_comparison_eligible
            else "`NOT ELIGIBLE`"
        ),
        "",
        "## 事后 Oracle 怎么判",
        "",
        "事前规则与 Base DecisionRecord 保持原样；AI Lab 不再检查规则有没有照着执行。"
        "Session 结束后，每个 Window 只有同时满足以下条件才算事后短波机会：当时四腿"
        "能够按完整数量计价且通过成本和硬风险上限；入场 IV proxy 高于随后实际 RV proxy；"
        "连续路径没有穿任何短腿；官方结算后的费用后结果为正。最终盈利只是其中一项，"
        "不能单独证明漏掉机会。",
        "",
        f"Oracle identity：`{review.opportunity_definition_id}`",
        "",
        "## 分母和证据覆盖",
        "",
        "| 证据层 | 数量 |",
        "|---|---:|",
        f"| 预登记 DecisionWindow | {review.expected_window_count} |",
        f"| 已有 DecisionRecord | {review.recorded_decision_count} |",
        f"| 已有 WindowOutcome | {review.recorded_outcome_count} |",
        f"| 完整 IV/RV 曲线点 | {review.curve_observation_count} |",
        f"| 可完成四象限判定 Window | {review.auditable_window_count} |",
        f"| 合法四腿结构 | {review.legal_structure_count} |",
        f"| 完整数量可报价结构 | {review.price_evaluable_count} |",
        f"| 保留费用与硬风险约束后的控制结构 | {review.control_candidate_count} |",
        f"| 同时通过 IV/RV、路径和结算的结构 | {review.hindsight_opportunity_structure_count} |",
        "",
    ]
    if review.evidence_reason_counts:
        lines.extend(
            [
                "### 证据缺口",
                "",
                "| 原因 | Window 数 |",
                "|---|---:|",
                *[
                    f"| `{_cell(reason)}` | {count} |"
                    for reason, count in review.evidence_reason_counts
                ],
                "",
            ]
        )
    lines.extend(_curve_section(review))
    lines.extend(_avoidance_section(review))
    lines.extend(_miss_section(review))
    lines.extend(_over_risk_section(review))
    lines.extend(_window_table(review))
    lines.extend(_memory_section(memory))
    lines.extend(
        [
            "## Codex 研究解释",
            "",
            "Codex 是可选的独立补充。确定性报告已经先落盘；Codex 失败不会删除或阻止本报告。",
            "",
            "## 证据边界",
            "",
            review.evidence_boundary,
            "",
            f"Review identity: `{review.identity}`",
            "",
        ]
    )
    return "\n".join(lines)


def _curve_section(review: SessionReview) -> list[str]:
    lines = [
        "## 单日 IV / RV 曲线",
        "",
        "| UTC | Index | IV proxy | trailing RV proxy | 事前 VRP proxy |",
        "|---|---:|---:|---:|---:|",
    ]
    for point in review.curve:
        lines.append(
            f"| {point.observed_at.strftime('%H:%M:%S')} | {point.index_price_usd} | "
            f"{point.implied_variance_proxy} | {point.trailing_realized_variance_proxy} | "
            f"{point.ex_ante_vrp_proxy_ratio} |"
        )
    if not review.curve:
        lines.append("| — | — | — | — | — |")
    lines.extend(
        [
            "",
            "这条曲线是事后审计证据；它不能倒灌进原 DecisionRecord。少一个预登记切点，"
            "整个 Session 的‘规则很好’结论就保持 UNKNOWN。",
            "",
        ]
    )
    return lines


def _miss_section(review: SessionReview) -> list[str]:
    missed_ids = {
        item.decision_window_id
        for item in review.windows
        if item.classification.value == "MISSED_OPPORTUNITY"
    }
    findings = [item for item in review.opportunities if item.decision_window_id in missed_ids]
    if not findings:
        return []
    blocker_counts = Counter(gate.code for item in findings for gate in item.gate_distances)
    lines = [
        "## Base 漏掉的机会",
        "",
        "| Window | 费用后 USD | IV - 事后 RV | Base 门槛 | Candidate |",
        "|---|---:|---:|---|---|",
    ]
    for item in findings[:50]:
        gates = ", ".join(gate.code for gate in item.gate_distances) or "未量化的选择差异"
        lines.append(
            f"| `{item.decision_window_id[-12:]}` | {item.settlement_reference_result_usd} | "
            f"{item.implied_minus_hindsight_realized_variance} | {_cell(gates)} | "
            f"`{item.candidate_id[-12:]}` |"
        )
    if blocker_counts:
        lines.extend(
            [
                "",
                "Base 门槛归因："
                + "、".join(
                    f"`{code}`={count}"
                    for code, count in sorted(
                        blocker_counts.items(), key=lambda item: (-item[1], item[0])
                    )
                )
                + "。只有真实负 signed margin 或明确类别门槛会进入这里。",
            ]
        )
    lines.append("")
    return lines


def _avoidance_section(review: SessionReview) -> list[str]:
    windows = [item for item in review.windows if item.classification.value == "CORRECT_AVOIDANCE"]
    if not windows:
        return []
    reasons: Counter[str] = Counter()
    for window in windows:
        reasons.update(dict(window.hindsight_rejection_counts))
    lines = [
        "## 为什么这些 Window 应该避开",
        "",
        "下面统计所有通过 decision-time 成本与硬风险控制的结构，最终没有成为事后机会的"
        "确切原因；同一结构可以同时触发多项。",
        "",
        "| 事后否决原因 | 结构-Window 次数 |",
        "|---|---:|",
    ]
    if reasons:
        lines.extend(
            f"| `{_cell(reason)}` | {count} |"
            for reason, count in sorted(reasons.items(), key=lambda item: (-item[1], item[0]))
        )
    else:
        lines.append("| `NO_CONTROL_CANDIDATE_AFTER_HARD_CONSTRAINTS` | 0 |")
    lines.append("")
    return lines


def _over_risk_section(review: SessionReview) -> list[str]:
    windows = [
        item for item in review.windows if item.classification.value == "OVER_RISK_SELECTION"
    ]
    if not windows:
        return []
    lines = [
        "## Base 选择的过度风险",
        "",
        "| UTC | 费用后 USD | IV−事后 RV | 路径 min/max | 短 Put/Call | 风险事实 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for item in windows:
        lines.append(
            f"| {item.starts_at.strftime('%H:%M')} | {item.selected_settlement_result_usd} | "
            f"{item.selected_implied_minus_hindsight_rv} | "
            f"{item.selected_path_minimum_index_usd}/{item.selected_path_maximum_index_usd} | "
            f"{item.selected_short_put_strike_usd}/{item.selected_short_call_strike_usd} | "
            f"{_cell(', '.join(item.selected_candidate_hindsight_reasons))} |"
        )
    lines.append("")
    return lines


def _window_table(review: SessionReview) -> list[str]:
    lines = [
        "## 每个 Window 的规则质量对照",
        "",
        "| UTC | 证据 | Base | 事后分类 | 合法 / 可报价 / 控制 / 机会 | 原因 |",
        "|---|---|---|---|---:|---|",
    ]
    for item in review.windows:
        funnel = (
            f"{item.legal_structure_count} / {item.price_evaluable_count} / "
            f"{item.control_candidate_count} / {item.hindsight_opportunity_count}"
        )
        hindsight_rejections = tuple(
            f"{reason}={count}" for reason, count in item.hindsight_rejection_counts
        )
        reasons = (
            ", ".join(
                item.evidence_reasons
                or item.selected_candidate_hindsight_reasons
                or hindsight_rejections
                or item.base_blockers
            )
            or "—"
        )
        lines.append(
            f"| {item.starts_at.strftime('%H:%M')} | {item.evidence_status.value} | "
            f"{item.base_result} | {item.classification.value} | {funnel} | {_cell(reasons)} |"
        )
    lines.append("")
    return lines


def _memory_section(memory: MemoryDigest) -> list[str]:
    lines = [
        "## 累积记忆",
        "",
        f"当前 Session 前已有 `{memory.prior_review_count}` 个有效 Policy-quality Review。",
        f"另有 `{memory.invalid_legacy_review_count}` 个旧终值筛选 Review，统一标记 "
        f"`{LEGACY_POLICY_QUALITY_STATUS}`，不进入规则质量统计或 Codex 事实。",
        "",
    ]
    if memory.verdict_counts:
        lines.append(
            "有效 verdict 分布："
            + "、".join(f"`{key}`={value}" for key, value in memory.verdict_counts)
            + "。"
        )
        lines.append("")
    if memory.recurring_base_blockers:
        lines.append(
            "高频 Base blocker："
            + "、".join(f"`{key}`={value}" for key, value in memory.recurring_base_blockers[:8])
            + "。"
        )
        lines.append("")
    if memory.hypothesis_counts:
        lines.append(
            "重复研究假设："
            + "、".join(f"`{key}`={value}" for key, value in memory.hypothesis_counts[:8])
            + "。"
        )
        lines.append("")
    return lines


def _render_analysis(analysis: Mapping[str, object]) -> str:
    model_output = analysis.get("model_output")
    if not isinstance(model_output, dict):
        raise ValidationError("analysis report received malformed model output")
    lines = ["# AI Lab Codex Research Supplement", "", str(model_output.get("summary")), ""]
    diagnoses = model_output.get("diagnoses")
    if isinstance(diagnoses, list) and diagnoses:
        lines.extend(["## 诊断", ""])
        for item in diagnoses:
            if isinstance(item, dict):
                lines.append(
                    f"- {item.get('claim')}（facts: {', '.join(item.get('fact_ids', []))}）"
                )
        lines.append("")
    hypotheses = model_output.get("hypotheses")
    if isinstance(hypotheses, list) and hypotheses:
        lines.extend(["## 待证伪假设", ""])
        for item in hypotheses:
            if isinstance(item, dict):
                lines.append(
                    f"- `{item.get('hypothesis_key')}`：{item.get('claim')}；下一测试："
                    f"{item.get('next_test')}"
                )
        lines.append("")
    proposal = model_output.get("challenger_proposal")
    if isinstance(proposal, dict):
        lines.extend(
            [
                "## Challenger",
                "",
                f"`{proposal.get('action')}` — {proposal.get('reason')}",
                "",
            ]
        )
    return "\n".join(lines)


def _report_dir(root: Path, review: SessionReview) -> Path:
    session_slug = review.session_id.replace("-", "").replace(":", "").replace("+", "")
    return root / "reports" / session_slug / review.identity.removeprefix("sha256:")[:16]


def _write_idempotent(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise ValidationError(f"refusing to overwrite a different AI Lab report: {path}")
        return
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ValidationError(f"AI Lab report appeared concurrently: {path}") from exc


def _verdict_label(verdict: SessionVerdict) -> str:
    return {
        SessionVerdict.UNKNOWN: "证据不足，不能评价规则",
        SessionVerdict.NO_OPPORTUNITY_CORRECTLY_AVOIDED: "本 Session 没有机会，Base 避险正确",
        SessionVerdict.RULE_WELL_CALIBRATED: "本 Session 的规则取舍很好",
        SessionVerdict.RULE_TOO_CONSERVATIVE: "规则偏保守，漏掉了机会",
        SessionVerdict.RULE_TOO_AGGRESSIVE: "规则偏激进，承担了不合格风险",
        SessionVerdict.MIXED_RULE_ERROR: "规则同时存在漏单和冒险",
    }[verdict]


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
