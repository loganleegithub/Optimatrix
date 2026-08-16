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
from optimatrix.ai_lab.memory import MemoryDigest
from optimatrix.ai_lab.session_review import SessionReview, SessionVerdict

REPORT_SCHEMA = "optimatrix.ai-lab.session-report.v1"
REPORT_NAMESPACE = "OptimatrixAiLabSessionReportV1"


def write_session_report(
    *,
    review: SessionReview,
    memory: MemoryDigest,
    analysis: Mapping[str, object] | None,
    root: Path = AI_LAB_DURABLE_ROOT,
) -> tuple[Path, Path]:
    lab_root = isolated_path(root)
    projection: JsonObject = {
        "schema_version": REPORT_SCHEMA,
        "review": review.as_object(),
        "prior_memory": memory.as_object(),
        "codex_analysis": dict(analysis) if analysis is not None else None,
    }
    projection["report_id"] = content_id(REPORT_NAMESPACE, projection)
    session_slug = review.session_id.replace("-", "").replace(":", "").replace("+", "")
    report_dir = lab_root / "reports" / session_slug / review.identity.removeprefix("sha256:")[:16]
    json_path = report_dir / "session-review.json"
    markdown_path = report_dir / "session-review.md"
    _write_idempotent(json_path, canonical_bytes(projection) + b"\n")
    _write_idempotent(
        markdown_path,
        render_session_report(review=review, memory=memory, analysis=analysis).encode("utf-8"),
    )
    return json_path, markdown_path


def render_session_report(
    *,
    review: SessionReview,
    memory: MemoryDigest,
    analysis: Mapping[str, object] | None,
) -> str:
    lines = [
        f"# AI Lab Session Review — {review.session_id}",
        "",
        "## 交易员结论",
        "",
        f"**{_verdict_label(review.verdict)}** — {review.verdict_reason}",
        "",
        f"- Base Candidate Window：`{review.base_candidate_window_count}`",
        f"- 事后成功的四腿机会：`{review.successful_opportunity_count}`",
        f"- Base 精确抓到的同一四腿机会：`{review.base_confirmed_opportunity_count}`",
        "- Challenger 比较："
        + (
            "`ELIGIBLE`（只允许另行冻结实验，不代表规则更好）"
            if review.challenger_comparison_eligible
            else "`NOT ELIGIBLE`"
        ),
        "",
        "## 机会是怎么判的",
        "",
        "AI Lab 先冻结每个 Window 当时能看到的 public Shadow 事实，枚举同一到期日、"
        "同一数量、可完整报价的四腿宽跨式信用结构。控制组保留 DataHealth、四腿结构、"
        "完整数量、Combo 标准费用、USD 风险上限；暂时拿掉 Session 阶段、VRP、"
        "body distance、net Delta、最低 $10 和最低 7% 等策略筛选。随后只用匹配的连续"
        "未来路径与官方交割价计算费用后到期结果。正结果叫“事后成功机会”；这不是成交，"
        "也不是事前 Edge。",
        "",
        f"机会定义身份：`{review.opportunity_definition_id}`",
        "",
        "## 证据与机会漏斗",
        "",
        "| 层级 | 数量 |",
        "|---|---:|",
        f"| 预登记 DecisionWindow | {review.expected_window_count} |",
        f"| 已有 DecisionRecord | {review.recorded_decision_count} |",
        f"| 已有 WindowOutcome | {review.recorded_outcome_count} |",
        f"| 证据完整、可审计 Window | {review.auditable_window_count} |",
        f"| 合法四腿结构 | {review.legal_structure_count} |",
        f"| 完整数量可报价结构 | {review.price_evaluable_count} |",
        f"| 保留成本与 USD 风险约束后的控制组 | {review.control_candidate_count} |",
        f"| 费用后到期结果为正 | {review.successful_opportunity_count} |",
        "",
    ]
    if review.evidence_reason_counts:
        lines.extend(
            [
                "### 不能下结论的证据缺口",
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
    lines.extend(_opportunity_section(review))
    lines.extend(_window_table(review))
    lines.extend(_memory_section(memory))
    lines.extend(_analysis_section(analysis))
    lines.extend(
        [
            "## 证据边界",
            "",
            review.evidence_boundary,
            "",
            f"Review identity: `{review.identity}`",
            "",
        ]
    )
    return "\n".join(lines)


def _opportunity_section(review: SessionReview) -> list[str]:
    if not review.opportunities:
        if review.verdict is SessionVerdict.NO_OPPORTUNITY:
            return [
                "## 为什么可以说“这个 Session 没有机会”",
                "",
                "96 个 Window 全部有可用的 Base 决策、连续未来路径和官方结算。每个当时"
                "可完整报价且通过控制组成本/风险约束的四腿结构，费用后到期结果都不大于 0；"
                "因此本定义下直接结束，不启动 Codex，也不构造 Challenger。",
                "",
            ]
        return [
            "## 机会结论仍未闭合",
            "",
            "当前没有找到事后成功结构，但证据不允许把“没看到”写成“整个 Session 没有”。",
            "",
        ]
    blocker_counts = Counter(
        gate.code
        for opportunity in review.opportunities
        if not opportunity.base_selected_exact_candidate
        for gate in opportunity.gate_distances
    )
    lines = [
        "## 事后机会与 Base 归因",
        "",
        "| Window | Base | 事后 USD | Put/Call 短腿穿越 | Base 精确命中 | Candidate |",
        "|---|---|---:|---|---|---|",
    ]
    for item in review.opportunities[:50]:
        breach = f"{_yes(item.put_short_breached)} / {_yes(item.call_short_breached)}"
        lines.append(
            "| "
            f"`{item.decision_window_id[-12:]}` | {item.base_result} | "
            f"{item.settlement_reference_result_usd} | {breach} | "
            f"{_yes(item.base_selected_exact_candidate)} | `{item.candidate_id[-12:]}` |"
        )
    if len(review.opportunities) > 50:
        lines.append(
            f"\n完整 JSON 保留全部 {len(review.opportunities)} 个机会；Markdown 只展示前 50 个。"
        )
    lines.append("")
    if blocker_counts:
        lines.extend(
            [
                "### 原规则为什么漏掉",
                "",
                "| Base 门槛 | 影响的成功结构数 |",
                "|---|---:|",
                *[
                    f"| `{_cell(code)}` | {count} |"
                    for code, count in sorted(
                        blocker_counts.items(), key=lambda item: (-item[1], item[0])
                    )
                ],
                "",
                "每个机会的 JSON 同时保存 actual、threshold、signed_margin_to_pass。负数是"
                "“离通过还差多少”；无法诚实压成一个数字的类别门槛明确标为不可量化。",
                "",
            ]
        )
    return lines


def _window_table(review: SessionReview) -> list[str]:
    lines = [
        "## 每个 Window 的判定轨迹",
        "",
        "| UTC Window | 证据 | Base | 合法 / 可报价 / 控制组 / 成功 | 最好事后 USD | 原因 |",
        "|---|---|---|---:|---:|---|",
    ]
    for item in review.windows:
        funnel = (
            f"{item.legal_structure_count} / {item.price_evaluable_count} / "
            f"{item.control_candidate_count} / {item.successful_opportunity_count}"
        )
        best = (
            str(item.best_control_result_usd) if item.best_control_result_usd is not None else "—"
        )
        reasons = ", ".join(item.evidence_reasons or item.base_blockers) or "—"
        lines.append(
            f"| {item.starts_at.strftime('%H:%M')} | {item.evidence_status.value} | "
            f"{item.base_result} | {funnel} | {best} | {_cell(reasons)} |"
        )
    lines.append("")
    return lines


def _memory_section(memory: MemoryDigest) -> list[str]:
    lines = [
        "## 累积记忆",
        "",
        f"当前分析前已有 `{memory.prior_review_count}` 个密封 Session Review。",
        "",
    ]
    if memory.verdict_counts:
        lines.append(
            "Verdict 分布："
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


def _analysis_section(analysis: Mapping[str, object] | None) -> list[str]:
    if analysis is None:
        return [
            "## Codex 研究解释",
            "",
            "`NOT_RUN`。NO_OPPORTUNITY/UNKNOWN 会在确定性判定处停止；其他 verdict 只有显式"
            " `--with-codex` 才运行一次只读、结构化分析。",
            "",
        ]
    model_output = analysis.get("model_output")
    if not isinstance(model_output, dict):
        raise ValidationError("report received malformed Codex analysis")
    lines = [
        "## Codex 研究解释",
        "",
        str(model_output.get("summary")),
        "",
    ]
    diagnoses = model_output.get("diagnoses")
    if isinstance(diagnoses, list) and diagnoses:
        lines.extend(["### 诊断", ""])
        for item in diagnoses:
            if isinstance(item, dict):
                lines.append(
                    f"- {item.get('claim')}（facts: {', '.join(item.get('fact_ids', []))}）"
                )
        lines.append("")
    hypotheses = model_output.get("hypotheses")
    if isinstance(hypotheses, list) and hypotheses:
        lines.extend(["### 待证伪假设", ""])
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
                "### Challenger",
                "",
                f"`{proposal.get('action')}` — {proposal.get('reason')}",
                "",
            ]
        )
    return lines


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
        SessionVerdict.UNKNOWN: "证据不足，不能判断没有机会",
        SessionVerdict.NO_OPPORTUNITY: "本 Session 没有符合固定定义的事后成功机会",
        SessionVerdict.MISSED_OPPORTUNITY: "市场给过机会，Base 漏掉了",
        SessionVerdict.BASE_FOUND_OPPORTUNITY: "Base 确实抓到过机会",
    }[verdict]


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _yes(value: bool) -> str:
    return "是" if value else "否"
