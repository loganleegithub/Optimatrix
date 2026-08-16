from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from optimatrix.ai_lab.approval import HumanApproval
from optimatrix.ai_lab.canonical import (
    AI_LAB_DURABLE_ROOT,
    ValidationError,
    load_json,
    parse_utc,
    write_new_json,
)
from optimatrix.ai_lab.codex_analysis import CodexCliAnalyzer
from optimatrix.ai_lab.demo import run_demo
from optimatrix.ai_lab.evaluation import ExperimentRunner
from optimatrix.ai_lab.hindsight_evidence import (
    fetch_official_index_evidence,
    load_official_index_evidence,
    write_official_index_evidence,
)
from optimatrix.ai_lab.memory import AiLabMemoryStore
from optimatrix.ai_lab.models import (
    DecisionWindowExport,
    ExperimentPlan,
    FrozenSpec,
    seal_document,
)
from optimatrix.ai_lab.promotion import record_promotion_decision
from optimatrix.ai_lab.report import write_analysis_report, write_session_report
from optimatrix.ai_lab.session_review import SessionVerdict, review_ledger_session
from optimatrix.ai_lab.store import AuditStore
from optimatrix.policy import DEFAULT_BTC_SHORT_VOL_POLICY_PATH, load_btc_short_vol_policy


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="optimatrix-ai-lab",
        description="Offline, fail-closed Optimatrix AI Lab",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    seal = subcommands.add_parser("seal", help="content-seal a spec, export, plan, or approval")
    seal.add_argument("--kind", choices=("spec", "export", "plan", "approval"), required=True)
    seal.add_argument("--draft", type=Path, required=True)
    seal.add_argument("--output", type=Path, required=True)

    register = subcommands.add_parser(
        "register",
        help="append a sealed Base/Challenger/plan registration to one audit store",
    )
    register.add_argument("--base", type=Path, required=True)
    register.add_argument("--challenger", type=Path, required=True)
    register.add_argument("--plan", type=Path, required=True)
    register.add_argument("--store", type=Path, required=True)

    run = subcommands.add_parser("run", help="run one frozen offline comparison")
    run.add_argument("--base", type=Path, required=True)
    run.add_argument("--challenger", type=Path, required=True)
    run.add_argument("--input", type=Path, required=True)
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--store", type=Path, required=True)
    run.add_argument("--registration-id", required=True)
    run.add_argument("--session-review-id", action="append", default=[])
    run.add_argument("--lab-root", type=Path, default=AI_LAB_DURABLE_ROOT)
    run.add_argument("--recorded-at", help="canonical UTC; defaults to current audit time")

    verify = subcommands.add_parser("verify", help="verify all append-only audit hash chains")
    verify.add_argument("--store", type=Path, required=True)

    promotion = subcommands.add_parser(
        "promotion",
        help="record a fail-closed automatic request or explicit human research decision",
    )
    promotion.add_argument("--store", type=Path, required=True)
    promotion.add_argument("--result-id", required=True)
    promotion.add_argument("--approval", type=Path)
    promotion.add_argument("--automatic", action="store_true")
    promotion.add_argument("--decided-at", help="canonical UTC; defaults to current audit time")

    demo = subcommands.add_parser("demo", help="run a loudly synthetic mechanism fixture")
    demo.add_argument("--output", type=Path, required=True)

    review = subcommands.add_parser(
        "review-session",
        help="adjudicate one ended Session before any Challenger comparison",
    )
    review.add_argument("--ledger-root", type=Path, required=True)
    review.add_argument("--session-id", required=True, help="canonical Deribit expiry UTC")
    review.add_argument("--lab-root", type=Path, default=AI_LAB_DURABLE_ROOT)
    review.add_argument("--policy", type=Path, default=DEFAULT_BTC_SHORT_VOL_POLICY_PATH)
    review.add_argument("--with-codex", action="store_true")
    review.add_argument("--codex-binary", default="codex")
    review.add_argument("--recorded-at", help="canonical UTC; defaults to local audit time")
    review.add_argument(
        "--official-index-evidence",
        type=Path,
        help="content-sealed Deribit official index evidence already stored under --lab-root",
    )

    fetch_evidence = subcommands.add_parser(
        "fetch-official-evidence",
        help="fetch one ended Session's bounded public Deribit index history",
    )
    fetch_evidence.add_argument("--session-id", required=True)
    fetch_evidence.add_argument("--lab-root", type=Path, default=AI_LAB_DURABLE_ROOT)

    verify_memory = subcommands.add_parser(
        "verify-memory",
        help="verify append-only Session reviews and Codex analyses",
    )
    verify_memory.add_argument("--lab-root", type=Path, default=AI_LAB_DURABLE_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "seal":
            draft = load_json(args.draft)
            sealed = (
                HumanApproval.seal(draft)
                if args.kind == "approval"
                else seal_document(args.kind, draft)
            )
            path = write_new_json(args.output, sealed)
            _print({"status": "SEALED_CONTENT_DOCUMENT", "path": str(path), **sealed})
            return 0
        if args.command == "register":
            base = FrozenSpec.from_object(load_json(args.base))
            challenger = FrozenSpec.from_object(load_json(args.challenger))
            plan = ExperimentPlan.from_object(load_json(args.plan))
            registration, event, appended = AuditStore(args.store).register_experiment(
                base=base,
                challenger=challenger,
                plan=plan,
                recorded_at=datetime.now(UTC),
            )
            _print(
                {
                    "status": "REGISTERED_IN_LOCAL_APPEND_ONLY_STORE",
                    "appended": appended,
                    "registration_event_id": event["event_id"],
                    "registration_event_sequence": event["sequence"],
                    **registration,
                }
            )
            return 0
        if args.command == "run":
            recorded_at = (
                parse_utc(args.recorded_at, "recorded_at")
                if args.recorded_at
                else datetime.now(UTC)
            )
            dataset = DecisionWindowExport.from_object(load_json(args.input))
            result = ExperimentRunner().run(
                base=FrozenSpec.from_object(load_json(args.base)),
                challenger=FrozenSpec.from_object(load_json(args.challenger)),
                dataset=dataset,
                plan=ExperimentPlan.from_object(load_json(args.plan)),
                store=AuditStore(args.store),
                registration_id=args.registration_id,
                recorded_at=recorded_at,
                memory=(AiLabMemoryStore(args.lab_root) if args.session_review_id else None),
                session_review_ids=tuple(args.session_review_id),
            )
            _print(result)
            return 0
        if args.command == "verify":
            _print(AuditStore(args.store).verify())
            return 0
        if args.command == "promotion":
            if args.automatic == (args.approval is not None):
                raise ValidationError("choose exactly one of --automatic or --approval")
            decided_at = (
                parse_utc(args.decided_at, "decided_at") if args.decided_at else datetime.now(UTC)
            )
            sealed_approval = load_json(args.approval) if args.approval else None
            decision = record_promotion_decision(
                store=AuditStore(args.store),
                result_id=args.result_id,
                decided_at=decided_at,
                sealed_approval=sealed_approval,
                automatic=args.automatic,
            )
            _print(decision)
            return 0
        if args.command == "demo":
            _print(run_demo(args.output))
            return 0
        if args.command == "fetch-official-evidence":
            evidence = fetch_official_index_evidence(session_id=args.session_id)
            path = write_official_index_evidence(evidence, root=args.lab_root)
            _print(
                {
                    "status": "AI_LAB_OFFICIAL_INDEX_EVIDENCE_RECORDED",
                    "session_id": evidence.session_id,
                    "evidence_id": evidence.identity,
                    "point_count": len(evidence.points),
                    "cadence_ms": evidence.cadence_ms,
                    "session_coverage_complete": evidence.session_coverage_complete,
                    "coverage_gap_count": len(evidence.coverage_gaps),
                    "path": str(path),
                }
            )
            return 0
        if args.command == "review-session":
            _require_separate_roots(args.ledger_root, args.lab_root)
            policy = load_btc_short_vol_policy(args.policy)
            memory = AiLabMemoryStore(args.lab_root)
            official_evidence = None
            if args.official_index_evidence is not None:
                _require_evidence_in_lab_root(args.official_index_evidence, args.lab_root)
                official_evidence = load_official_index_evidence(args.official_index_evidence)
            review = review_ledger_session(
                ledger_root=args.ledger_root,
                session_id=args.session_id,
                policy=policy,
                official_index_evidence=official_evidence,
                supersedes_review_id=memory.review_predecessor_id(session_id=args.session_id),
            )
            prior_memory = memory.digest(before_session_id=review.session_id)
            recorded_at = (
                parse_utc(args.recorded_at, "recorded_at")
                if args.recorded_at
                else datetime.now(UTC)
            )
            review_event, review_appended = memory.append_review(
                review,
                recorded_at=recorded_at,
            )
            json_path, markdown_path = write_session_report(
                review=review,
                memory=prior_memory,
                root=args.lab_root,
            )
            analysis = None
            codex_status = "NOT_REQUESTED"
            codex_error = None
            analysis_json_path = None
            analysis_markdown_path = None
            if args.with_codex and review.verdict not in {
                SessionVerdict.UNKNOWN,
                SessionVerdict.PARTIALLY_IDENTIFIED_NO_KNOWN_RULE_ERROR,
                SessionVerdict.NO_OPPORTUNITY_CORRECTLY_AVOIDED,
            }:
                try:
                    analysis = CodexCliAnalyzer(codex_binary=args.codex_binary).analyze(
                        review=review,
                        memory=prior_memory,
                    )
                    _analysis_event, analysis_appended = memory.append_analysis(analysis)
                    codex_status = "APPENDED" if analysis_appended else "ALREADY_RECORDED"
                    analysis_json_path, analysis_markdown_path = write_analysis_report(
                        review=review,
                        analysis=analysis,
                        root=args.lab_root,
                    )
                except ValidationError as exc:
                    codex_status = "FAILED_OPTIONAL_ANALYSIS"
                    codex_error = str(exc)[:500]
            elif args.with_codex:
                codex_status = "SKIPPED_BY_POLICY_QUALITY_WORKFLOW"
            _print(
                {
                    "status": "AI_LAB_POLICY_QUALITY_REVIEW_RECORDED",
                    "review_id": review.identity,
                    "session_id": review.session_id,
                    "verdict": review.verdict.value,
                    "verdict_reason": review.verdict_reason,
                    "challenger_comparison_eligible": (review.challenger_comparison_eligible),
                    "auditable_window_count": review.auditable_window_count,
                    "unknown_window_count": review.unknown_window_count,
                    "coverage_fraction": str(review.coverage_fraction),
                    "miss_rate_bounds": [
                        str(review.miss_rate_lower_bound),
                        str(review.miss_rate_upper_bound),
                    ],
                    "over_risk_rate_bounds": [
                        str(review.over_risk_rate_lower_bound),
                        str(review.over_risk_rate_upper_bound),
                    ],
                    "opportunity_rate_bounds": [
                        str(review.opportunity_rate_lower_bound),
                        str(review.opportunity_rate_upper_bound),
                    ],
                    "hindsight_opportunity_structure_count": (
                        review.hindsight_opportunity_structure_count
                    ),
                    "hindsight_positive_policy_reject_structure_count": (
                        review.hindsight_positive_policy_reject_structure_count
                    ),
                    "official_index_evidence_id": (
                        review.official_index_evidence.identity
                        if review.official_index_evidence is not None
                        else None
                    ),
                    "supersedes_review_id": review.supersedes_review_id,
                    "review_appended": review_appended,
                    "review_event_id": review_event["event_id"],
                    "codex_status": codex_status,
                    "codex_error": codex_error,
                    "json_report": str(json_path),
                    "markdown_report": str(markdown_path),
                    "analysis_json_report": (
                        str(analysis_json_path) if analysis_json_path is not None else None
                    ),
                    "analysis_markdown_report": (
                        str(analysis_markdown_path) if analysis_markdown_path is not None else None
                    ),
                }
            )
            return 0
        if args.command == "verify-memory":
            _print(AiLabMemoryStore(args.lab_root).verify())
            return 0
    except (OSError, ValueError) as exc:
        print(f"optimatrix-ai-lab: {exc}", file=sys.stderr)
        return 2
    raise AssertionError("argparse returned an unknown command")


def _print(value: object) -> None:
    print(json.dumps(value, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True))


def _require_separate_roots(ledger_root: Path, lab_root: Path) -> None:
    ledger = ledger_root.expanduser().resolve()
    lab = lab_root.expanduser().resolve()
    if ledger == lab or ledger.is_relative_to(lab) or lab.is_relative_to(ledger):
        raise ValidationError(
            "AI Lab memory/report root must be disjoint from the read-only ObservationLedger root"
        )


def _require_evidence_in_lab_root(path: Path, lab_root: Path) -> None:
    evidence = path.expanduser().resolve()
    root = lab_root.expanduser().resolve()
    if not evidence.is_relative_to(root):
        raise ValidationError("official index evidence must already be stored under --lab-root")
