from __future__ import annotations

import json
import subprocess
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from optimatrix.ai_lab.canonical import ValidationError, content_id, seal_object, utc_text
from optimatrix.ai_lab.codex_analysis import CodexCliAnalyzer
from optimatrix.ai_lab.evaluation import ExperimentRunner
from optimatrix.ai_lab.memory import (
    LEGACY_MEMORY_REVIEW_NAMESPACE,
    LEGACY_MEMORY_REVIEW_SCHEMA,
    LEGACY_SESSION_REVIEW_NAMESPACE,
    LEGACY_SESSION_REVIEW_SCHEMA,
    POLICY_QUALITY_V1_MEMORY_NAMESPACE,
    POLICY_QUALITY_V1_MEMORY_SCHEMA,
    POLICY_QUALITY_V1_REVIEW_NAMESPACE,
    POLICY_QUALITY_V1_REVIEW_SCHEMA,
    POLICY_QUALITY_V2_MEMORY_NAMESPACE,
    POLICY_QUALITY_V2_MEMORY_SCHEMA,
    POLICY_QUALITY_V2_REVIEW_NAMESPACE,
    POLICY_QUALITY_V2_REVIEW_SCHEMA,
    AiLabMemoryStore,
    MemoryDigest,
)
from optimatrix.ai_lab.models import (
    EXPORT_SCHEMA,
    PLAN_SCHEMA,
    SPEC_SCHEMA,
    DecisionWindowExport,
    ExperimentPlan,
    FrozenSpec,
)
from optimatrix.ai_lab.session_review import SessionReview, SessionVerdict
from optimatrix.ai_lab.store import AuditStore
from optimatrix.decision import DecisionResult
from tests.ai_lab.test_session_review import _population


def test_memory_is_append_once_and_tamper_evident(policy, tmp_path) -> None:
    review = _missed_review(policy)
    store = AiLabMemoryStore(tmp_path / "memory")

    recorded_at = review.windows[-1].starts_at + timedelta(hours=1)
    first, appended = store.append_review(review, recorded_at=recorded_at)
    second, repeated = store.append_review(review, recorded_at=recorded_at)

    assert appended and not repeated
    assert first == second
    assert store.verify() == {
        "status": "VALID_AI_LAB_MEMORY",
        "policy_quality_review_count": 1,
        "superseded_policy_quality_v1_review_count": 0,
        "superseded_policy_quality_v1_status": "SUPERSEDED_BY_PARTIAL_IDENTIFICATION_V2",
        "superseded_policy_quality_v2_review_count": 0,
        "superseded_policy_quality_v2_status": "SUPERSEDED_BY_RISK_QUALITY_V3",
        "legacy_session_review_count": 0,
        "legacy_policy_quality_status": "INVALID_FOR_POLICY_QUALITY",
        "codex_analysis_count": 0,
        "legacy_codex_analysis_count": 0,
    }
    digest = store.digest()
    assert digest.prior_review_count == 1
    assert digest.invalid_legacy_review_count == 0
    assert dict(digest.verdict_counts) == {"RULE_TOO_CONSERVATIVE": 1}
    path = store.reviews.path
    path.write_text(
        path.read_text(encoding="utf-8").replace("RULE_TOO_CONSERVATIVE", "RULE_TOO_AGGRESSIVE", 1),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="content identity mismatch"):
        store.verify()


def test_legacy_terminal_positive_review_is_verified_but_excluded_from_policy_memory(
    tmp_path,
) -> None:
    store = AiLabMemoryStore(tmp_path / "memory")
    session_id = "2026-08-15T08:00:00Z"
    legacy_review = seal_object(
        {
            "schema_version": LEGACY_SESSION_REVIEW_SCHEMA,
            "session_id": session_id,
            "verdict": "MISSED_OPPORTUNITY",
            "definition": "TERMINAL_POSITIVE_ONLY",
        },
        id_field="review_id",
        namespace=LEGACY_SESSION_REVIEW_NAMESPACE,
    )
    payload = seal_object(
        {
            "schema_version": LEGACY_MEMORY_REVIEW_SCHEMA,
            "session_id": session_id,
            "recorded_at": "2026-08-16T00:00:00Z",
            "review": legacy_review,
        },
        id_field="memory_review_id",
        namespace=LEGACY_MEMORY_REVIEW_NAMESPACE,
    )
    store.legacy_reviews.append(payload, identity_field="memory_review_id")

    verified = store.verify()
    digest = store.digest(before_session_id=session_id)

    assert verified["legacy_session_review_count"] == 1
    assert verified["legacy_policy_quality_status"] == "INVALID_FOR_POLICY_QUALITY"
    assert digest.invalid_legacy_review_count == 1
    assert digest.prior_review_count == 0
    assert dict(digest.verdict_counts) == {}
    assert legacy_review["review_id"] not in digest.fact_ids


def test_v3_review_supersedes_exact_v1_v2_chain_without_rewriting_history(policy, tmp_path) -> None:
    store = AiLabMemoryStore(tmp_path / "memory")
    session_id = "2026-08-15T08:00:00Z"
    v1_review = seal_object(
        {
            "schema_version": POLICY_QUALITY_V1_REVIEW_SCHEMA,
            "session_id": session_id,
            "verdict": "UNKNOWN",
        },
        id_field="review_id",
        namespace=POLICY_QUALITY_V1_REVIEW_NAMESPACE,
    )
    v1_payload = seal_object(
        {
            "schema_version": POLICY_QUALITY_V1_MEMORY_SCHEMA,
            "session_id": session_id,
            "recorded_at": "2026-08-16T00:00:00Z",
            "review": v1_review,
        },
        id_field="memory_review_id",
        namespace=POLICY_QUALITY_V1_MEMORY_NAMESPACE,
    )
    store.reviews.append(v1_payload, identity_field="memory_review_id")
    original_first_line = store.reviews.path.read_text(encoding="utf-8").splitlines()[0]
    v2_review = seal_object(
        {
            "schema_version": POLICY_QUALITY_V2_REVIEW_SCHEMA,
            "session_id": session_id,
            "supersedes_review_id": v1_review["review_id"],
            "verdict": "OBSERVED_RULE_TOO_CONSERVATIVE",
        },
        id_field="review_id",
        namespace=POLICY_QUALITY_V2_REVIEW_NAMESPACE,
    )
    v2_payload = seal_object(
        {
            "schema_version": POLICY_QUALITY_V2_MEMORY_SCHEMA,
            "session_id": session_id,
            "recorded_at": "2026-08-16T00:01:00Z",
            "supersedes_review_id": v1_review["review_id"],
            "review": v2_review,
        },
        id_field="memory_review_id",
        namespace=POLICY_QUALITY_V2_MEMORY_NAMESPACE,
    )
    store.reviews.append(v2_payload, identity_field="memory_review_id")
    original_second_line = store.reviews.path.read_text(encoding="utf-8").splitlines()[1]
    population_session_id, records, outcomes = _population(
        policy,
        implied_variance=Decimal("0.0011"),
        realized_variance=Decimal("0.0010"),
        delivery_price=Decimal("100000"),
        path_mode="SAFE_ALL",
    )
    assert population_session_id == session_id
    from optimatrix.ai_lab.session_review import review_session

    unlinked = review_session(
        session_id=session_id,
        policy=policy,
        records=records,
        outcomes=outcomes,
    )
    with pytest.raises(ValidationError, match="exact prior Review"):
        store.append_review(
            unlinked,
            recorded_at=unlinked.windows[-1].starts_at + timedelta(hours=1),
        )
    review = review_session(
        session_id=session_id,
        policy=policy,
        records=records,
        outcomes=outcomes,
        supersedes_review_id=str(v2_review["review_id"]),
    )
    store.append_review(review, recorded_at=review.windows[-1].starts_at + timedelta(hours=1))

    lines = store.reviews.path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == original_first_line
    assert lines[1] == original_second_line
    assert len(lines) == 3
    assert store.verify()["policy_quality_review_count"] == 1
    assert store.verify()["superseded_policy_quality_v1_review_count"] == 1
    assert store.verify()["superseded_policy_quality_v2_review_count"] == 1
    digest = store.digest()
    assert digest.prior_review_count == 1
    assert digest.superseded_policy_quality_v1_review_count == 1
    assert digest.superseded_policy_quality_v2_review_count == 1
    assert digest.fact_ids == (review.identity,)


def test_actual_challenger_experiment_requires_and_binds_eligible_reviews(policy, tmp_path) -> None:
    review, record = _base_found_review(policy)
    memory = AiLabMemoryStore(tmp_path / "lab")
    memory.append_review(
        review,
        recorded_at=record.window.ends_at + timedelta(days=1),
    )
    base, challenger, plan, dataset = _actual_experiment_documents(policy, record)
    audit = AuditStore(tmp_path / "audit")
    registration, _event, _appended = audit.register_experiment(
        base=base,
        challenger=challenger,
        plan=plan,
        recorded_at=dataset.exported_at + timedelta(seconds=1),
    )
    runner = ExperimentRunner()
    with pytest.raises(ValidationError, match="requires an eligible Session review"):
        runner.run(
            base=base,
            challenger=challenger,
            dataset=dataset,
            plan=plan,
            store=audit,
            registration_id=str(registration["registration_id"]),
            recorded_at=dataset.exported_at + timedelta(minutes=1),
        )

    result = runner.run(
        base=base,
        challenger=challenger,
        dataset=dataset,
        plan=plan,
        store=audit,
        registration_id=str(registration["registration_id"]),
        recorded_at=dataset.exported_at + timedelta(minutes=1),
        memory=memory,
        session_review_ids=(review.identity,),
    )

    assert result["evidence_scope"] == "EXPORTED_ACTUAL_PATH_DIAGNOSTICS_ONLY"
    manifest = audit.manifests.read()[0]["payload"]
    assert manifest["session_first_gates"][0]["review_id"] == review.identity


def test_codex_is_read_only_ephemeral_schema_bound_and_fact_cited(policy) -> None:
    review = _missed_review(policy)
    output = {
        "summary": "VRP gate blocked a later profitable synthetic structure.",
        "diagnoses": [
            {
                "claim": "The miss is measurable.",
                "fact_ids": [review.identity],
                "quantifiable": True,
                "metric": "signed_margin_to_pass",
            }
        ],
        "hypotheses": [
            {
                "hypothesis_key": "VRP_FRONTIER_RECURS",
                "claim": "The same frontier may recur.",
                "fact_ids": [review.identity],
                "next_test": "Observe ten later completed Sessions.",
                "status": "HYPOTHESIS_ONLY",
            }
        ],
        "challenger_proposal": {
            "action": "NOT_ELIGIBLE",
            "reason": "Base did not find the confirmed opportunity.",
            "fact_ids": [review.identity],
        },
    }
    runner = _FakeRunner(output)

    analysis = CodexCliAnalyzer(runner=runner).analyze(
        review=review,
        memory=_empty_memory(),
    )

    assert analysis["review_id"] == review.identity
    assert runner.command is not None
    assert "--ignore-user-config" in runner.command
    assert "--ephemeral" in runner.command
    assert ("--sandbox", "read-only") == _pair(runner.command, "--sandbox")
    assert "--output-schema" in runner.command
    assert "--output-last-message" in runner.command
    assert "RULE_TOO_CONSERVATIVE" in runner.prompt
    assert len(runner.prompt.encode("utf-8")) < 300_000
    prompt = json.loads(runner.prompt)
    assert prompt["session_review"]["omitted_opportunity_count"] >= 0
    assert len(prompt["session_review"]["representative_opportunities"]) <= 48
    assert analysis["memory_digest_id"] == _empty_memory().identity


def test_codex_rejects_unsupplied_fact_and_challenger_escalation(policy) -> None:
    review = _missed_review(policy)
    foreign = f"sha256:{'f' * 64}"
    bad_citation = {
        "summary": "unsupported",
        "diagnoses": [
            {
                "claim": "invented",
                "fact_ids": [foreign],
                "quantifiable": False,
                "metric": None,
            }
        ],
        "hypotheses": [],
        "challenger_proposal": {
            "action": "NOT_ELIGIBLE",
            "reason": "not eligible",
            "fact_ids": [review.identity],
        },
    }
    with pytest.raises(ValidationError, match="not supplied"):
        CodexCliAnalyzer(runner=_FakeRunner(bad_citation)).analyze(
            review=review,
            memory=_empty_memory(),
        )
    escalation = dict(bad_citation)
    escalation["diagnoses"] = []
    escalation["challenger_proposal"] = {
        "action": "PROPOSE_CHALLENGER",
        "reason": "skip the gate",
        "fact_ids": [review.identity],
    }
    with pytest.raises(ValidationError, match="before deterministic eligibility"):
        CodexCliAnalyzer(runner=_FakeRunner(escalation)).analyze(
            review=review,
            memory=_empty_memory(),
        )


def test_no_opportunity_never_enters_codex(policy) -> None:
    session_id, records, outcomes = _population(
        policy,
        implied_variance=Decimal("0.0010"),
        realized_variance=Decimal("0.0016"),
        delivery_price=Decimal("100000"),
        path_mode="SAFE_ALL",
    )
    from optimatrix.ai_lab.session_review import review_session

    review = review_session(
        session_id=session_id,
        policy=policy,
        records=records,
        outcomes=outcomes,
    )
    runner = _FakeRunner({})
    with pytest.raises(ValidationError, match="stop before Codex"):
        CodexCliAnalyzer(runner=runner).analyze(review=review, memory=_empty_memory())
    assert runner.command is None


class _FakeRunner:
    def __init__(self, output: object) -> None:
        self.output = output
        self.command: tuple[str, ...] | None = None
        self.prompt = ""

    def __call__(
        self,
        command,
        prompt: str,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[str]:
        self.command = tuple(command)
        self.prompt = prompt
        assert timeout_seconds == 300
        output_index = self.command.index("--output-last-message") + 1
        Path(self.command[output_index]).write_text(
            json.dumps(self.output),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(self.command, 0, stdout="", stderr="")


def _missed_review(policy) -> SessionReview:
    from optimatrix.ai_lab.session_review import review_session

    session_id, records, outcomes = _population(
        policy,
        implied_variance=Decimal("0.0011"),
        realized_variance=Decimal("0.0010"),
        delivery_price=Decimal("100000"),
        path_mode="SAFE_ALL",
    )
    review = review_session(
        session_id=session_id,
        policy=policy,
        records=records,
        outcomes=outcomes,
    )
    assert review.verdict is SessionVerdict.RULE_TOO_CONSERVATIVE
    return review


def _base_found_review(policy):
    from optimatrix.ai_lab.session_review import review_session

    session_id, records, outcomes = _population(
        policy,
        implied_variance=Decimal("0.0024"),
        realized_variance=Decimal("0.0016"),
        delivery_price=Decimal("100000"),
        path_mode="SAFE_CANDIDATES_ONLY",
    )
    review = review_session(
        session_id=session_id,
        policy=policy,
        records=records,
        outcomes=outcomes,
    )
    assert review.challenger_comparison_eligible
    record = next(item for item in records if item.result is DecisionResult.CANDIDATE)
    return review, record


def _actual_experiment_documents(policy, record):
    starts_at = record.window.starts_at
    trained_through = starts_at - timedelta(days=2)
    base = FrozenSpec.from_object(
        FrozenSpec.seal(
            {
                "schema_version": SPEC_SCHEMA,
                "status": "FROZEN",
                "role": "BASE",
                "version": "base-v1",
                "name": "Frozen Base",
                "frozen_at": utc_text(starts_at - timedelta(days=1)),
                "trained_through": utc_text(trained_through),
                "external_policy_id": policy.identity,
                "implementation_id": "OPTIMATRIX_BASE_V1",
                "limitations": ["PUBLIC_SHADOW_ONLY"],
            }
        )
    )
    challenger_policy_id = content_id("TestChallengerPolicy", {"version": 1})
    challenger = FrozenSpec.from_object(
        FrozenSpec.seal(
            {
                "schema_version": SPEC_SCHEMA,
                "status": "FROZEN",
                "role": "CHALLENGER",
                "version": "challenger-v1",
                "name": "Frozen Challenger",
                "frozen_at": utc_text(starts_at - timedelta(days=1)),
                "trained_through": utc_text(trained_through),
                "external_policy_id": challenger_policy_id,
                "implementation_id": "OPTIMATRIX_CHALLENGER_V1",
                "limitations": ["PUBLIC_SHADOW_ONLY"],
            }
        )
    )
    plan = ExperimentPlan.from_object(
        ExperimentPlan.seal(
            {
                "schema_version": PLAN_SCHEMA,
                "status": "FROZEN",
                "mode": "CHRONOLOGICAL",
                "registered_at": utc_text(starts_at - timedelta(hours=12)),
                "folds": [
                    {
                        "fold_id": "session-fold",
                        "training_ends_at": utc_text(starts_at - timedelta(days=1)),
                        "evaluation_starts_at": utc_text(starts_at),
                        "evaluation_ends_at": utc_text(record.window.ends_at),
                    }
                ],
                "evaluator_id": "INDEX_PATH_DIAGNOSTICS_V1",
                "metric_ids": ["DECISION_AGREEMENT_RATE"],
                "promotion_gate": {
                    "min_comparable_windows": 1,
                    "max_incomparable_fraction": "0",
                    "require_actual_paths": True,
                },
            }
        )
    )
    path_start = record.known_at + timedelta(seconds=1)
    path_end = path_start + timedelta(minutes=1)
    assert record.observation is not None
    dataset = DecisionWindowExport.from_object(
        DecisionWindowExport.seal(
            {
                "schema_version": EXPORT_SCHEMA,
                "exported_at": utc_text(path_end + timedelta(seconds=2)),
                "producer_id": "AI_LAB_TEST_EXPORTER",
                "source_repository_commit": "TEST_FIXTURE",
                "source_contracts": ["TEST_ACTUAL_PATH_SHAPE_ONLY"],
                "windows": [
                    {
                        "decision_window_id": record.window.identity,
                        "market_session_id": record.window.market_session_id,
                        "starts_at": utc_text(record.window.starts_at),
                        "ends_at": utc_text(record.window.ends_at),
                        "input_deadline": utc_text(record.window.input_deadline),
                        "base_decision": {
                            "spec_id": base.spec_id,
                            "decision_policy_id": base.external_policy_id,
                            "known_at": utc_text(record.known_at),
                            "causal_input_ends_at": utc_text(record.observation.known_at),
                            "result": "CANDIDATE",
                            "blockers": [],
                        },
                        "challenger_decision": {
                            "spec_id": challenger.spec_id,
                            "decision_policy_id": challenger.external_policy_id,
                            "known_at": utc_text(record.known_at),
                            "causal_input_ends_at": utc_text(record.observation.known_at),
                            "result": "ABSTAIN",
                            "blockers": ["FROZEN_CHALLENGER_ABSTAIN"],
                        },
                        "future_path": {
                            "kind": "FULL_PATH",
                            "actuality": "ACTUAL_PUBLIC_PATH",
                            "source_id": "TEST_ACTUAL_PUBLIC_PATH",
                            "method_id": "TWO_POINT_PATH",
                            "starts_at": utc_text(path_start),
                            "ends_at": utc_text(path_end),
                            "known_at": utc_text(path_end + timedelta(seconds=1)),
                            "continuous": True,
                            "points": [
                                {
                                    "observed_at": utc_text(path_start),
                                    "known_at": utc_text(path_start + timedelta(microseconds=1)),
                                    "index_price_usd": "100000",
                                },
                                {
                                    "observed_at": utc_text(path_end),
                                    "known_at": utc_text(path_end + timedelta(microseconds=1)),
                                    "index_price_usd": "100100",
                                },
                            ],
                        },
                    }
                ],
            }
        )
    )
    return base, challenger, plan, dataset


def _empty_memory() -> MemoryDigest:
    return MemoryDigest(0, 0, 0, 0, (), (), (), (), ())


def _pair(command: tuple[str, ...], option: str) -> tuple[str, str]:
    index = command.index(option)
    return command[index], command[index + 1]
