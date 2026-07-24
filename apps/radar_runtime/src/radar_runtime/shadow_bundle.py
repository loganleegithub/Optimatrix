"""Durable evidence bundle for one Fixed-Policy public-Shadow closure."""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import tarfile
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from pathlib import Path, PurePosixPath
from typing import cast

from market_tape import canonical_digest, canonical_value

from radar_runtime.shadow_identity import RUN_RUNTIME_SOURCE_ID
from radar_runtime.shadow_report_identity import (
    RUN_REPORT_SOURCE_ID,
    run_report_source_identity,
)
from radar_runtime.shadow_runtime import (
    HISTORICAL_SEMANTIC_RECEIPT_TYPE,
    RECEIPTS_DIRECTORY,
    RUN_RECEIPT_PATH,
    replay_shadow,
)

BUNDLE_FORMAT_ID = "OPTIMATRIX_FIXED_POLICY_PUBLIC_SHADOW_EVIDENCE_BUNDLE"
UNKNOWN_DENOMINATOR_AUDIT_TYPE = "UNKNOWN_DENOMINATOR_AUDIT"
UNKNOWN_DENOMINATOR_AUDIT_PATH = "UNKNOWN_DENOMINATOR_AUDIT.json"
BUSINESS_FUNNEL_REPORT_TYPE = "FIXED_POLICY_PUBLIC_SHADOW_BUSINESS_FUNNEL_REPORT"
BUSINESS_FUNNEL_BUNDLE_REPORT_TYPE = "FIXED_POLICY_PUBLIC_SHADOW_BUSINESS_FUNNEL_BUNDLE_REPORT"
BUSINESS_FUNNEL_PATH = "BUSINESS_FUNNEL.json"
RATE_DECIMAL_PRECISION = 28
_ADMISSION_PARTITION = (
    "OPPORTUNITY_UNKNOWN",
    "NO_ENTRY",
    "ADMITTED",
    "CONCURRENCY_BLOCKED",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _json_object(path: Path) -> dict[str, object]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return cast(dict[str, object], value)


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(
            canonical_value(value),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _copy_tree(source: Path, target: Path) -> None:
    if not source.is_dir():
        raise ValueError(f"evidence directory is missing: {source}")
    for path in sorted(item for item in source.rglob("*") if item.is_file()):
        destination = target / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return cast(dict[str, object], value)


def _nonnegative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer")
    return value


def _audit_rate(
    numerator: int | None,
    denominator: int | None,
) -> dict[str, object]:
    if denominator is None:
        return {
            "numerator": numerator,
            "denominator": None,
            "rate": None,
            "status": "UNKNOWN_DENOMINATOR",
        }
    if denominator == 0:
        if numerator not in {None, 0}:
            raise ValueError("zero denominator has a nonzero numerator")
        return {
            "numerator": numerator,
            "denominator": 0,
            "rate": None,
            "status": "UNDEFINED_ZERO_DENOMINATOR",
        }
    if numerator is None:
        return {
            "numerator": None,
            "denominator": denominator,
            "rate": None,
            "status": "UNKNOWN_NUMERATOR",
        }
    if numerator > denominator:
        raise ValueError("rate numerator exceeds its denominator")
    with localcontext(Context(prec=34, rounding=ROUND_HALF_EVEN)):
        rendered = format((Decimal(numerator) / Decimal(denominator)).normalize(), "f")
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": rendered,
        "status": "DEFINED",
    }


def _reason_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{label} must contain exact nonempty reasons")
    return cast(list[str], value)


def _build_unknown_denominator_audit(
    run_receipt: dict[str, object],
    decision_receipts: dict[int, dict[str, object]],
) -> dict[str, object]:
    summaries = run_receipt.get("opportunity_summaries")
    decision_digests = run_receipt.get("decision_receipt_digests")
    if not isinstance(summaries, list) or not isinstance(decision_digests, list):
        raise ValueError("Run receipt lacks its opportunity denominator")
    if len(summaries) != len(decision_digests):
        raise ValueError("opportunity and Decision receipt denominators disagree")

    expected_receipt_slots: set[int] = set()
    available_slot_count = 0
    slots: list[dict[str, object]] = []
    for expected_slot, raw_summary in enumerate(summaries):
        summary = _object(raw_summary, "opportunity summary")
        if summary.get("slot_index") != expected_slot:
            raise ValueError("opportunity slots are not exact and ordered")
        event_backed = summary.get("event_backed")
        if type(event_backed) is not bool:
            raise ValueError("opportunity event-backed state is invalid")
        decision_digest = decision_digests[expected_slot]
        if event_backed != isinstance(decision_digest, str):
            raise ValueError("opportunity and Decision receipt presence disagree")

        blockers: set[str]
        quote_coverage: dict[str, object]
        assessment_availability: dict[str, object]
        if not event_backed:
            reason = summary.get("admission_reason")
            if not isinstance(reason, str) or not reason:
                raise ValueError("no-event opportunity lacks its exact reason")
            blockers = {reason}
            availability = "UNAVAILABLE"
            quote_coverage = _audit_rate(None, None)
            assessment_availability = _audit_rate(None, None)
        else:
            expected_receipt_slots.add(expected_slot)
            receipt = decision_receipts.get(expected_slot)
            if receipt is None:
                raise ValueError("event-backed opportunity lacks its Decision receipt")
            recorded_digest = receipt.get("receipt_digest")
            if not isinstance(recorded_digest, str) or recorded_digest != decision_digest:
                raise ValueError("Decision receipt digest and Run receipt disagree")
            readiness = _object(receipt.get("readiness"), "Decision readiness")
            evaluation = _object(receipt.get("evaluation"), "Decision evaluation")
            frame_complete = readiness.get("frame_complete")
            if type(frame_complete) is not bool:
                raise ValueError("Decision frame availability is invalid")
            frame_reasons = _reason_list(
                readiness.get("frame_incomplete_reasons"),
                "frame incomplete reasons",
            )
            if frame_complete == bool(frame_reasons):
                raise ValueError("Decision availability and blocker set disagree")
            blockers = set(frame_reasons)
            unavailable_reason_counts = evaluation.get("assessment_unavailable_reason_counts")
            if not isinstance(unavailable_reason_counts, list):
                raise ValueError("assessment unavailable reasons are invalid")
            for raw_reason_count in unavailable_reason_counts:
                if (
                    not isinstance(raw_reason_count, list)
                    or len(raw_reason_count) != 2
                    or not isinstance(raw_reason_count[0], str)
                    or not raw_reason_count[0]
                ):
                    raise ValueError("assessment unavailable reason is invalid")
                _nonnegative_int(raw_reason_count[1], "assessment unavailable reason count")
                if raw_reason_count[1] == 0:
                    raise ValueError("assessment unavailable reason count must be positive")
                blockers.add(raw_reason_count[0])

            catalog = _object(readiness.get("catalog"), "catalog readiness")
            quotes = _object(readiness.get("quotes"), "quote readiness")
            catalog_count_raw = catalog.get("instrument_count")
            catalog_count = (
                None
                if catalog_count_raw is None
                else _nonnegative_int(catalog_count_raw, "catalog instrument count")
            )
            catalog_option_count = None if catalog_count is None else max(catalog_count - 1, 0)
            option_quote_count = _nonnegative_int(
                quotes.get("option_quote_count"),
                "option quote count",
            )
            quote_coverage = _audit_rate(option_quote_count, catalog_option_count)

            assessment_count = _nonnegative_int(
                evaluation.get("assessment_count"),
                "assessment count",
            )
            assessment_opportunity_count = _nonnegative_int(
                evaluation.get("assessment_opportunity_count"),
                "assessment opportunity count",
            )
            assessment_unavailable_count = _nonnegative_int(
                evaluation.get("assessment_unavailable_count"),
                "assessment unavailable count",
            )
            if assessment_count + assessment_unavailable_count != assessment_opportunity_count:
                raise ValueError("assessment denominator is not completely partitioned")
            assessment_availability = _audit_rate(
                assessment_count,
                assessment_opportunity_count,
            )
            availability = "AVAILABLE" if frame_complete else "UNAVAILABLE"
            available_slot_count += int(frame_complete)

        ordered_blockers = sorted(blockers)
        slots.append(
            {
                "slot_index": expected_slot,
                "event_backed": event_backed,
                "decision_receipt_digest": decision_digest,
                "availability": availability,
                "blocker_count": len(ordered_blockers),
                "blockers": ordered_blockers,
                "sole_blocker": (ordered_blockers[0] if len(ordered_blockers) == 1 else None),
                "co_blockers": ordered_blockers if len(ordered_blockers) > 1 else [],
                "quote_coverage": quote_coverage,
                "assessment_availability": assessment_availability,
            }
        )
    if set(decision_receipts) != expected_receipt_slots:
        raise ValueError("Decision receipt set does not match event-backed slots")

    audit: dict[str, object] = {
        "audit_type": UNKNOWN_DENOMINATOR_AUDIT_TYPE,
        "run_id": run_receipt.get("run_id"),
        "source_run_receipt_digest": run_receipt.get("run_receipt_digest"),
        "due_slot_count": len(summaries),
        "available_slot_count": available_slot_count,
        "availability_rate": _audit_rate(available_slot_count, len(summaries)),
        "quote_coverage_definition": (
            "option_quote_count / max(catalog.instrument_count - "
            "one_required_reference_instrument, 0)"
        ),
        "assessment_availability_definition": ("assessment_count / assessment_opportunity_count"),
        "rate_rendering": (
            "numerator and denominator are the exact ratio; rate is a deterministic "
            "34-significant-digit ROUND_HALF_EVEN decimal rendering"
        ),
        "slots": slots,
        "authoritative_decision_or_outcome": False,
        "non_claims": [
            "MISSING_EVIDENCE_IS_NOT_ZERO",
            "PREDICATE_FAILURE_IS_NOT_AN_AVAILABILITY_BLOCKER",
            "REPORT_DOES_NOT_CHANGE_DECISION_POLICY_OUTCOME_OR_STAGE",
        ],
    }
    audit["audit_digest"] = canonical_digest(audit)
    return audit


def _unknown_denominator_audit(run_root: Path) -> dict[str, object]:
    run_receipt = _json_object(run_root / RUN_RECEIPT_PATH)
    raw_decision_digests = run_receipt.get("decision_receipt_digests")
    if not isinstance(raw_decision_digests, list):
        raise ValueError("Run receipt Decision denominator is invalid")
    receipts = {
        slot: _json_object(run_root / RECEIPTS_DIRECTORY / f"decision-slot-{slot:02d}.json")
        for slot, digest in enumerate(raw_decision_digests)
        if isinstance(digest, str)
    }
    return _build_unknown_denominator_audit(run_receipt, receipts)


def _funnel_rate(numerator: int, denominator: int) -> str | None:
    if denominator == 0:
        return None
    with localcontext(Context(prec=RATE_DECIMAL_PRECISION, rounding=ROUND_HALF_EVEN)):
        return str(Decimal(numerator) / Decimal(denominator))


def business_funnel_report(accounting: object) -> dict[str, object]:
    """Derive descriptive candidate rates without changing the sealed Run accounting."""

    if not isinstance(accounting, dict):
        raise ValueError("business Funnel accounting must be an object")
    due_count = _nonnegative_int(
        accounting.get("due_opportunity_count"),
        "due opportunity count",
    )
    raw_admissions = accounting.get("admission_counts")
    raw_actions = accounting.get("action_counts")
    if not isinstance(raw_admissions, dict) or not isinstance(raw_actions, dict):
        raise ValueError("business Funnel partitions are missing")
    admissions = {
        name: _nonnegative_int(raw_admissions.get(name), f"{name} count")
        for name in _ADMISSION_PARTITION
    }
    if sum(admissions.values()) != due_count:
        raise ValueError("business Funnel opportunity partition changed")
    candidate_count = _nonnegative_int(
        raw_actions.get("RESEARCH_CANDIDATE"),
        "candidate count",
    )
    complete_decision_count = due_count - admissions["OPPORTUNITY_UNKNOWN"]
    if candidate_count != (admissions["ADMITTED"] + admissions["CONCURRENCY_BLOCKED"]):
        raise ValueError("business Funnel candidate partition changed")
    if candidate_count > complete_decision_count:
        raise ValueError("business Funnel candidate count exceeds complete Decisions")
    return {
        "report_type": BUSINESS_FUNNEL_REPORT_TYPE,
        "due_opportunity_count": due_count,
        "complete_decision_count": complete_decision_count,
        "candidate_count": candidate_count,
        "opportunity_partition": admissions,
        "raw_candidate_rate": _funnel_rate(candidate_count, due_count),
        "candidate_rate_given_complete": _funnel_rate(
            candidate_count,
            complete_decision_count,
        ),
        "rate_semantics": "COUNTS_AUTHORITATIVE_DECIMAL_RENDERING_ONLY",
        "decimal_rendering": {
            "precision": RATE_DECIMAL_PRECISION,
            "rounding": ROUND_HALF_EVEN,
        },
        "interpretation": "DESCRIPTIVE_ONLY_NOT_QUALIFICATION",
    }


def _bundle_business_funnel(
    synthetic: dict[str, object],
    public: dict[str, object],
) -> dict[str, object]:
    return {
        "report_type": BUSINESS_FUNNEL_BUNDLE_REPORT_TYPE,
        "synthetic": business_funnel_report(synthetic.get("accounting")),
        "production_public": business_funnel_report(public.get("accounting")),
    }


def _validate_replay(replay: dict[str, object], label: str) -> None:
    anomalies = replay.get("operational_anomaly_counts")
    if (
        replay.get("replay_verified") is not True
        or replay.get("computation_reconstructed") is not True
        or replay.get("prefix_causality_verified") is not True
        or replay.get("online_persistence_process_witness_verified") is not True
        or replay.get("external_source_attested") is not False
        or replay.get("attempt_selection_attested") is not False
        or replay.get("online_persistence_external_attested") is not False
        or not isinstance(anomalies, dict)
        or any(type(value) is not int or value < 0 for value in anomalies.values())
    ):
        raise ValueError(f"{label} replay trust boundary is invalid")
    for layer in (
        "schedule",
        "fact",
        "decision",
        "admission",
        "entry",
        "outcome",
        "maturity",
        "no_trade",
        "aggregate",
        "run_receipt",
    ):
        value = replay.get(f"{layer}_drift_count")
        if type(value) is not int or value != 0:
            raise ValueError(f"{label} replay has nonzero {layer} drift")


def _report(
    *,
    generated_at: str,
    synthetic: dict[str, object],
    synthetic_replay: dict[str, object],
    public: dict[str, object],
    public_replay: dict[str, object],
    semantic: dict[str, object],
    synthetic_audit: dict[str, object],
    public_audit: dict[str, object],
) -> str:
    funnel = _bundle_business_funnel(synthetic, public)
    lines = [
        "# Fixed-Policy Public Shadow 验收报告",
        "",
        f"- 报告生成时间: `{generated_at}`",
        f"- 合成 Run: complete=`{synthetic.get('complete')}`, "
        f"records=`{synthetic.get('records')}`, "
        f"operational anomalies=`{json.dumps(synthetic.get('operational_anomaly_counts'), sort_keys=True)}`",
        f"- 合成会计: `{json.dumps(synthetic.get('accounting'), sort_keys=True, ensure_ascii=False)}`",
        f"- 生产公开 Run: complete=`{public.get('complete')}`, "
        f"records=`{public.get('records')}`, "
        f"operational anomalies=`{json.dumps(public.get('operational_anomaly_counts'), sort_keys=True)}`",
        f"- 生产公开会计: `{json.dumps(public.get('accounting'), sort_keys=True, ensure_ascii=False)}`",
        f"- 合成业务 Funnel: `{json.dumps(funnel['synthetic'], sort_keys=True, ensure_ascii=False)}`",
        f"- 生产公开业务 Funnel: `{json.dumps(funnel['production_public'], sort_keys=True, ensure_ascii=False)}`",
        f"- 合成 replay: verified=`{synthetic_replay.get('replay_verified')}`, "
        f"prefix_causality=`{synthetic_replay.get('prefix_causality_verified')}`",
        f"- 生产 replay: verified=`{public_replay.get('replay_verified')}`, "
        f"collector_witness=`{public_replay.get('collector_witness_verified')}`",
        f"- 历史语义回归: authoritative=`{semantic.get('authoritative_replay')}`, "
        f"Decision drift=`{semantic.get('decision_semantic_drift_count')}`, "
        f"Outcome drift=`{semantic.get('outcome_semantic_drift_count')}`",
        "",
        "## UNKNOWN denominator audit",
        "",
        "- availability rate 的零是“可用槽计数”, 不是缺失市场事实的数值替代。",
        "- quote coverage = observed option quotes / catalog option instruments; "
        "assessment availability = assessed / assessment opportunities。",
        f"- 合成 availability: `{json.dumps(synthetic_audit.get('availability_rate'), sort_keys=True, ensure_ascii=False)}`",
        f"- 生产公开 availability: `{json.dumps(public_audit.get('availability_rate'), sort_keys=True, ensure_ascii=False)}`",
        "",
    ]
    for label, audit in (("合成", synthetic_audit), ("生产公开", public_audit)):
        slots = audit.get("slots")
        if not isinstance(slots, list):
            raise ValueError(f"{label} UNKNOWN denominator audit lacks slots")
        for raw_slot in slots:
            slot = _object(raw_slot, "UNKNOWN denominator slot")
            lines.append(
                f"- {label} slot `{slot.get('slot_index')}`: "
                f"availability=`{slot.get('availability')}`, "
                f"sole=`{slot.get('sole_blocker')}`, "
                f"co=`{json.dumps(slot.get('co_blockers'), sort_keys=True, ensure_ascii=False)}`, "
                f"quote=`{json.dumps(slot.get('quote_coverage'), sort_keys=True, ensure_ascii=False)}`, "
                f"assessment=`{json.dumps(slot.get('assessment_availability'), sort_keys=True, ensure_ascii=False)}`"
            )
    lines.extend(
        (
            "",
            "## 边界",
            "",
            "- public quotes 不是 fills; 本证据不证明账户、订单、成交或执行。",
            "- `NO_TRADE=0` 是无持仓定义值, 不是资格赛、Policy 质量或盈利证明。",
            "- replay 相等只证明封存输入的确定性重建, 不证明第三方来源或物理 fsync 时刻。",
            "- `attempt_selection_attested=false`; 证据不能证明外部操作者未丢弃另一尝试。",
            "- 两个 candidate rate 都是描述性 Funnel 指标, 不是 qualification 或 Policy 质量结论。",
            "- 不授权 Challenger、qualification、promotion、private API、execution 或 capital。",
            "",
        )
    )
    return "\n".join(lines)


def _write_archive(bundle: Path, archive: Path) -> None:
    with archive.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|") as tar:
                for path in sorted(item for item in bundle.rglob("*") if item.is_file()):
                    relative = path.relative_to(bundle)
                    info = tarfile.TarInfo(f"{bundle.name}/{relative.as_posix()}")
                    info.size = path.stat().st_size
                    info.mode = 0o644
                    info.mtime = 0
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    with path.open("rb") as source:
                        tar.addfile(info, source)


def create_shadow_evidence_bundle(
    *,
    synthetic_run: Path,
    synthetic_replay: Path,
    public_run: Path,
    public_replay: Path,
    semantic_regression: Path,
    output: Path,
) -> dict[str, object]:
    archive = output.with_suffix(".tar.gz")
    sidecar = Path(str(archive) + ".sha256")
    if output.exists() or archive.exists() or sidecar.exists():
        raise ValueError("Shadow evidence bundle output already exists")
    synthetic = _json_object(synthetic_run / "result.json")
    synthetic_replayed = _json_object(synthetic_replay / "replay.json")
    public = _json_object(public_run / "result.json")
    public_replayed = _json_object(public_replay / "replay.json")
    semantic = _json_object(semantic_regression / "semantic-regression.json")
    report_identity = run_report_source_identity(require_clean=True)
    synthetic_audit = _unknown_denominator_audit(synthetic_run)
    public_audit = _unknown_denominator_audit(public_run)
    if synthetic.get("complete") is not True or public.get("complete") is not True:
        raise ValueError("Shadow evidence bundle requires two complete Runs")
    _validate_replay(synthetic_replayed, "synthetic")
    _validate_replay(public_replayed, "production-public")
    if (
        semantic.get("receipt_type") != HISTORICAL_SEMANTIC_RECEIPT_TYPE
        or semantic.get("authoritative_replay") is not False
        or type(semantic.get("decision_semantic_drift_count")) is not int
        or semantic.get("decision_semantic_drift_count") != 0
        or type(semantic.get("outcome_semantic_drift_count")) is not int
        or semantic.get("outcome_semantic_drift_count") != 0
    ):
        raise ValueError("historical semantic regression is not accepted")
    _copy_tree(synthetic_run, output / "synthetic/run")
    _copy_tree(synthetic_replay, output / "synthetic/replay")
    _copy_tree(public_run, output / "production-public/run")
    _copy_tree(public_replay, output / "production-public/replay")
    _copy_tree(semantic_regression, output / "historical-semantic-regression")
    _write_json(
        output / "synthetic" / UNKNOWN_DENOMINATOR_AUDIT_PATH,
        synthetic_audit,
    )
    _write_json(
        output / "production-public" / UNKNOWN_DENOMINATOR_AUDIT_PATH,
        public_audit,
    )
    funnel = _bundle_business_funnel(synthetic, public)
    _write_json(output / BUSINESS_FUNNEL_PATH, funnel)
    invocation = _json_object(public_run / "invocation-witness.json")
    generated_at = cast(str, invocation["invocation_finished_at"])
    report = _report(
        generated_at=generated_at,
        synthetic=synthetic,
        synthetic_replay=synthetic_replayed,
        public=public,
        public_replay=public_replayed,
        semantic=semantic,
        synthetic_audit=synthetic_audit,
        public_audit=public_audit,
    )
    (output / "ACCEPTANCE.zh-CN.md").write_text(report, encoding="utf-8")
    artifacts = [
        {
            "path": path.relative_to(output).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(item for item in output.rglob("*") if item.is_file())
    ]
    manifest: dict[str, object] = {
        "bundle_format": BUNDLE_FORMAT_ID,
        "generated_at": generated_at,
        "synthetic_result_digest": synthetic["result_digest"],
        "synthetic_replay_digest": synthetic_replayed["replay_digest"],
        "public_result_digest": public["result_digest"],
        "public_replay_digest": public_replayed["replay_digest"],
        "semantic_regression_digest": semantic["receipt_digest"],
        "report_source_id": report_identity.report_source_id,
        "report_source_digest": report_identity.report_source_digest,
        "report_source_git_commit_sha": report_identity.git_commit_sha,
        "report_source_file_hashes": canonical_value(report_identity.file_hashes),
        "online_runtime_source_id": report_identity.online_runtime_source_id,
        "online_runtime_source_digest": report_identity.online_runtime_source_digest,
        "synthetic_unknown_denominator_audit_digest": synthetic_audit["audit_digest"],
        "public_unknown_denominator_audit_digest": public_audit["audit_digest"],
        "business_funnel_digest": canonical_digest(funnel),
        "artifacts": artifacts,
    }
    manifest["bundle_manifest_digest"] = canonical_digest(manifest)
    _write_json(output / "BUNDLE_MANIFEST.json", manifest)
    checksum_targets = sorted(item for item in output.rglob("*") if item.is_file())
    (output / "SHA256SUMS").write_text(
        "".join(
            f"{_sha256(path)}  {path.relative_to(output).as_posix()}\n" for path in checksum_targets
        ),
        encoding="utf-8",
    )
    verify_shadow_evidence_bundle(output)
    _write_archive(output, archive)
    archive_digest = _sha256(archive)
    sidecar.write_text(f"{archive_digest}  {archive.name}\n", encoding="utf-8")
    return {
        "bundle_format": BUNDLE_FORMAT_ID,
        "bundle_path": str(output),
        "bundle_manifest_digest": manifest["bundle_manifest_digest"],
        "archive_path": str(archive),
        "archive_sha256": archive_digest,
        "archive_sha256_path": str(sidecar),
    }


def verify_shadow_evidence_bundle(
    bundle: Path,
    *,
    archive: Path | None = None,
    authoritative_replay: bool = True,
) -> dict[str, object]:
    checksum_path = bundle / "SHA256SUMS"
    checksum_paths: set[str] = set()
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        digest, separator, relative = line.partition("  ")
        target = bundle / relative
        if (
            not separator
            or relative in checksum_paths
            or bundle.resolve() not in target.resolve().parents
            or not target.is_file()
            or _sha256(target) != digest
        ):
            raise ValueError("Shadow evidence checksum changed")
        checksum_paths.add(relative)
    expected = {
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    }
    if checksum_paths != expected:
        raise ValueError("Shadow evidence checksum coverage is incomplete")
    manifest = _json_object(bundle / "BUNDLE_MANIFEST.json")
    manifest_digest = manifest.get("bundle_manifest_digest")
    report_source_files = manifest.get("report_source_file_hashes")
    recorded_report_source_digest = canonical_digest(
        {
            "report_source_id": manifest.get("report_source_id"),
            "online_runtime_source_id": manifest.get("online_runtime_source_id"),
            "online_runtime_source_digest": manifest.get("online_runtime_source_digest"),
            "files": report_source_files,
        }
    )
    if (
        manifest.get("bundle_format") != BUNDLE_FORMAT_ID
        or not isinstance(manifest_digest, str)
        or manifest.get("report_source_id") != RUN_REPORT_SOURCE_ID
        or manifest.get("online_runtime_source_id") != RUN_RUNTIME_SOURCE_ID
        or not isinstance(report_source_files, list)
        or manifest.get("report_source_digest") != recorded_report_source_digest
        or canonical_digest(
            {key: value for key, value in manifest.items() if key != "bundle_manifest_digest"}
        )
        != manifest_digest
    ):
        raise ValueError("Shadow evidence manifest changed")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("Shadow evidence artifact manifest is invalid")
    artifact_paths: set[str] = set()
    for raw in artifacts:
        if not isinstance(raw, dict):
            raise ValueError("Shadow evidence artifact is invalid")
        artifact = cast(dict[str, object], raw)
        relative_path = artifact.get("path")
        if not isinstance(relative_path, str) or relative_path in artifact_paths:
            raise ValueError("Shadow evidence artifact path changed")
        target = bundle / relative_path
        if artifact.get("bytes") != target.stat().st_size or artifact.get("sha256") != _sha256(
            target
        ):
            raise ValueError("Shadow evidence artifact bytes changed")
        artifact_paths.add(relative_path)
    if artifact_paths != expected - {"BUNDLE_MANIFEST.json"}:
        raise ValueError("Shadow evidence artifact coverage changed")
    synthetic = _json_object(bundle / "synthetic/run/result.json")
    synthetic_replayed = _json_object(bundle / "synthetic/replay/replay.json")
    public = _json_object(bundle / "production-public/run/result.json")
    public_replayed = _json_object(bundle / "production-public/replay/replay.json")
    semantic = _json_object(bundle / "historical-semantic-regression/semantic-regression.json")
    synthetic_audit = _json_object(bundle / "synthetic" / UNKNOWN_DENOMINATOR_AUDIT_PATH)
    public_audit = _json_object(bundle / "production-public" / UNKNOWN_DENOMINATOR_AUDIT_PATH)
    funnel = _json_object(bundle / BUSINESS_FUNNEL_PATH)
    report_identity = run_report_source_identity(require_clean=authoritative_replay)
    report_source_match = (
        manifest.get("report_source_id") == report_identity.report_source_id
        and manifest.get("report_source_digest") == report_identity.report_source_digest
        and manifest.get("online_runtime_source_id") == report_identity.online_runtime_source_id
        and manifest.get("online_runtime_source_digest")
        == report_identity.online_runtime_source_digest
        and report_source_files == canonical_value(report_identity.file_hashes)
    )
    if authoritative_replay and not report_source_match:
        raise ValueError("Shadow evidence offline report source identity changed")
    _validate_replay(synthetic_replayed, "synthetic")
    _validate_replay(public_replayed, "production-public")
    if (
        manifest.get("synthetic_result_digest") != synthetic.get("result_digest")
        or manifest.get("synthetic_replay_digest") != synthetic_replayed.get("replay_digest")
        or manifest.get("public_result_digest") != public.get("result_digest")
        or manifest.get("public_replay_digest") != public_replayed.get("replay_digest")
        or manifest.get("semantic_regression_digest") != semantic.get("receipt_digest")
        or manifest.get("synthetic_unknown_denominator_audit_digest")
        != synthetic_audit.get("audit_digest")
        or manifest.get("public_unknown_denominator_audit_digest")
        != public_audit.get("audit_digest")
        or manifest.get("business_funnel_digest") != canonical_digest(funnel)
    ):
        raise ValueError("Shadow evidence manifest bindings changed")
    if report_source_match:
        reconstructed_synthetic_audit = _unknown_denominator_audit(bundle / "synthetic/run")
        reconstructed_public_audit = _unknown_denominator_audit(bundle / "production-public/run")
        if canonical_digest(synthetic_audit) != canonical_digest(
            reconstructed_synthetic_audit
        ) or canonical_digest(public_audit) != canonical_digest(reconstructed_public_audit):
            raise ValueError("UNKNOWN denominator audit changed")
        expected_funnel = _bundle_business_funnel(synthetic, public)
        if canonical_digest(funnel) != canonical_digest(expected_funnel):
            raise ValueError("Shadow business Funnel reconstruction changed")
        expected_report = _report(
            generated_at=cast(str, manifest["generated_at"]),
            synthetic=synthetic,
            synthetic_replay=synthetic_replayed,
            public=public,
            public_replay=public_replayed,
            semantic=semantic,
            synthetic_audit=synthetic_audit,
            public_audit=public_audit,
        )
        if (bundle / "ACCEPTANCE.zh-CN.md").read_text(encoding="utf-8") != expected_report:
            raise ValueError("Shadow evidence canonical report changed")
    temporary = bundle.parent / f".{bundle.name}-verification-replay"
    if authoritative_replay:
        if temporary.exists():
            shutil.rmtree(temporary)
        try:
            replay_shadow(bundle / "synthetic/run", temporary / "synthetic")
            replay_shadow(bundle / "production-public/run", temporary / "public")
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    if archive is not None:
        if not archive.is_file():
            raise ValueError("Shadow evidence archive is missing")
        archived: dict[str, tuple[int, str]] = {}
        with tarfile.open(archive, mode="r:gz") as source:
            for member in source.getmembers():
                path = PurePosixPath(member.name)
                if (
                    not member.isfile()
                    or path.is_absolute()
                    or ".." in path.parts
                    or member.name in archived
                ):
                    raise ValueError("Shadow evidence archive member is unsafe")
                handle = source.extractfile(member)
                if handle is None:
                    raise ValueError("Shadow evidence archive member is unreadable")
                data = handle.read()
                archived[member.name] = (len(data), hashlib.sha256(data).hexdigest())
        expected_archive = {
            f"{bundle.name}/{path.relative_to(bundle).as_posix()}": (
                path.stat().st_size,
                _sha256(path),
            )
            for path in bundle.rglob("*")
            if path.is_file()
        }
        if archived != expected_archive:
            raise ValueError("Shadow evidence archive contents changed")
        sidecar = Path(str(archive) + ".sha256")
        if (
            not sidecar.is_file()
            or sidecar.read_text(encoding="utf-8").strip() != f"{_sha256(archive)}  {archive.name}"
        ):
            raise ValueError("Shadow evidence archive sidecar changed")
    return {
        "bundle_format": BUNDLE_FORMAT_ID,
        "bundle_verified": True,
        "authoritative_replay_verified": authoritative_replay,
        "report_source_match": report_source_match,
        "report_reconstructed": report_source_match,
        "report_source_digest": manifest["report_source_digest"],
        "checksum_entries": len(checksum_paths),
        "bundle_manifest_digest": manifest_digest,
        "archive_sha256": _sha256(archive) if archive is not None else None,
    }
