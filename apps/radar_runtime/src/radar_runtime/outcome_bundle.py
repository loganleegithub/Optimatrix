"""Hash-verifiable dual synthetic/public evidence for Outcome Truth."""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import tarfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import cast

from market_tape import canonical_digest

BUNDLE_FORMAT_ID = "OPTIMATRIX_OUTCOME_TRUTH_EVIDENCE_BUNDLE"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _json_object(path: Path, label: str) -> dict[str, object]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return cast(dict[str, object], value)


_REPLAY_BOUND_FIELDS = (
    "full_capture_digest",
    "full_capture_manifest_digest",
    "fact_seal_digest",
    "decision_receipt_digest",
    "entry_receipt_digest",
    "outcome_receipt_digest",
    "decision_runtime_source_digest",
    "outcome_runtime_source_digest",
    "input_contract_digest",
    "policy_digest",
    "outcome_contract_digest",
)


def _validate_replay(
    run: dict[str, object],
    payload: dict[str, object],
    label: str,
) -> None:
    if payload.get("replay_verified") is not True:
        raise ValueError(f"{label} replay is not verified")
    for field in (
        "decision_drift_count",
        "entry_drift_count",
        "outcome_drift_count",
        "strict_future_violation_count",
    ):
        if payload.get(field) != 0:
            raise ValueError(f"{label} replay has nonzero {field}")
    for field in ("decision_drift_fields", "entry_drift_fields", "outcome_drift_fields"):
        if payload.get(field) != []:
            raise ValueError(f"{label} replay has inconsistent {field}")
    if not isinstance(run.get("result_digest"), str) or (
        payload.get("source_result_digest") != run["result_digest"]
        or payload.get("reconstructed_result_digest") != run["result_digest"]
    ):
        raise ValueError(f"{label} replay is not bound to its result")
    for field in _REPLAY_BOUND_FIELDS:
        if payload.get(field) != run.get(field):
            raise ValueError(f"{label} replay disagrees on {field}")


def _validate_cases(
    synthetic: dict[str, object],
    synthetic_replay: dict[str, object],
    public: dict[str, object],
    public_replay: dict[str, object],
) -> None:
    if (
        synthetic.get("fact_provenance") != "synthetic"
        or synthetic.get("evidence_class") != "SYNTHETIC_LOGIC"
        or synthetic.get("capture_complete") is not True
    ):
        raise ValueError("synthetic evidence provenance is invalid")
    if (
        synthetic.get("decision_action") != "RESEARCH_CANDIDATE"
        or synthetic.get("admission_status") != "ADMITTED"
    ):
        raise ValueError("synthetic evidence requires one admitted Candidate")
    if synthetic.get("entry_count") != 1 or synthetic.get("outcome_count") != 1:
        raise ValueError("synthetic evidence requires exactly one Entry and Outcome")
    if synthetic.get("outcome_status") != "CLOSED":
        raise ValueError("synthetic evidence requires a CLOSED Outcome")
    counterfactual_count = synthetic.get("counterfactual_point_count")
    if (
        not isinstance(counterfactual_count, int)
        or isinstance(counterfactual_count, bool)
        or counterfactual_count <= 0
    ):
        raise ValueError("synthetic evidence requires a post-exit counterfactual")
    if any(
        not isinstance(synthetic.get(field), str) or synthetic.get(field) == ""
        for field in (
            "fact_seal_digest",
            "decision_receipt_digest",
            "entry_receipt_digest",
            "outcome_receipt_digest",
        )
    ):
        raise ValueError("synthetic evidence receipt binding is incomplete")
    if (
        public.get("fact_provenance") != "production_public"
        or public.get("evidence_class") != "BOUNDED_PUBLIC_CAPTURE"
        or public.get("capture_complete") is not True
    ):
        raise ValueError("public evidence provenance is invalid")
    entry_count = public.get("entry_count")
    outcome_count = public.get("outcome_count")
    admission_status = public.get("admission_status")
    valid_unknown_zero = (
        entry_count == 0
        and outcome_count == 0
        and admission_status == "UNKNOWN"
        and public.get("decision_frame_complete") is False
        and public.get("entry_receipt_digest") is None
        and public.get("outcome_receipt_digest") is None
    )
    valid_no_entry_zero = (
        entry_count == 0
        and outcome_count == 0
        and admission_status == "NO_ENTRY"
        and public.get("decision_frame_complete") is True
        and public.get("decision_action") in {"WATCH", "ABSTAIN"}
        and public.get("entry_receipt_digest") is None
        and public.get("outcome_receipt_digest") is None
    )
    valid_observed = (
        entry_count == 1
        and outcome_count == 1
        and admission_status == "ADMITTED"
        and public.get("decision_action") == "RESEARCH_CANDIDATE"
        and public.get("outcome_status") in {"UNKNOWN", "UNEXITABLE", "CLOSED"}
        and isinstance(public.get("entry_receipt_digest"), str)
        and isinstance(public.get("outcome_receipt_digest"), str)
    )
    if not valid_unknown_zero and not valid_no_entry_zero and not valid_observed:
        raise ValueError("public evidence has an invalid Entry/Outcome result")
    if public.get("duration_seconds") != 3_665:
        raise ValueError("public evidence must be the authorized 3665-second capture")
    public_elapsed_span = public.get("collector_elapsed_span_ms")
    if (
        not isinstance(public_elapsed_span, int)
        or isinstance(public_elapsed_span, bool)
        or not 3_665_000 <= public_elapsed_span <= 3_725_000
    ):
        raise ValueError("public evidence elapsed span is not the authorized bounded run")
    _validate_replay(synthetic, synthetic_replay, "synthetic")
    _validate_replay(public, public_replay, "production-public")


def _validate_receipt_files(root: Path, result: dict[str, object], label: str) -> None:
    if not (root / "decision.json").is_file() or not (root / "facts/seal.json").is_file():
        raise ValueError(f"{label} run is missing its Decision or fact seal")
    expected = {
        "shadow-entry.json": result.get("entry_count") == 1,
        "outcome.json": result.get("outcome_count") == 1,
    }
    for name, should_exist in expected.items():
        if (root / name).is_file() is not should_exist:
            raise ValueError(f"{label} receipt file presence disagrees: {name}")


def _validate_public_collector_artifacts(
    root: Path,
    result: dict[str, object],
) -> None:
    paths = {
        "live": root / "collector-live.json",
        "decision": root / "collector-decision.json",
        "inspect": root / "collector-inspect.json",
        "invocation": root / "collector-invocation.json",
    }
    if any(not path.is_file() for path in paths.values()):
        raise ValueError("production-public run is missing bounded collector artifacts")
    live = _json_object(paths["live"], "production-public collector live receipt")
    decision = _json_object(paths["decision"], "production-public collector Decision receipt")
    inspected = _json_object(paths["inspect"], "production-public collector inspect")
    invocation = _json_object(
        paths["invocation"],
        "production-public collector invocation",
    )
    from radar_runtime.deribit_public import (
        CAPTURE_RECEIPT_TYPE,
        LIVE_CAPTURE_EVIDENCE,
        WEBSOCKET_URL,
        _event_summary,
        build_decision_receipt,
        decision_receipt_payload,
        inspect_payload,
        project_events,
        projection_payload,
    )
    from radar_runtime.outcome_runtime import PUBLIC_INVOCATION_RECEIPT_TYPE
    from radar_runtime.outcome_seal import read_sealed_capture
    from radar_runtime.runtime_identity import runtime_source_identity

    _seal, manifest, events, _prefix_manifest, _prefix_events = read_sealed_capture(root / "facts")
    evidence_git_commit_sha = result.get("git_commit_sha")
    if not isinstance(evidence_git_commit_sha, str) or not evidence_git_commit_sha:
        raise ValueError("production-public evidence Git identity is invalid")
    invocation_digest = invocation.get("invocation_digest")
    unsigned_invocation = {
        key: value for key, value in invocation.items() if key != "invocation_digest"
    }
    invocation_elapsed_ms = invocation.get("invocation_elapsed_ms")
    if (
        not isinstance(invocation_digest, str)
        or canonical_digest(unsigned_invocation) != invocation_digest
        or invocation.get("receipt_type") != PUBLIC_INVOCATION_RECEIPT_TYPE
        or invocation.get("environment") != "production_public"
        or invocation.get("transport_endpoint") != WEBSOCKET_URL
        or invocation.get("requested_duration_seconds") != 3_665
        or not isinstance(invocation_elapsed_ms, int)
        or isinstance(invocation_elapsed_ms, bool)
        or invocation_elapsed_ms < 3_665_000
        or not isinstance(invocation.get("invocation_started_at"), str)
        or not isinstance(invocation.get("invocation_finished_at"), str)
        or invocation.get("records") != manifest.record_count
        or invocation.get("capture_digest") != manifest.content_sha256
        or invocation.get("capture_manifest_digest") != manifest.digest
        or invocation.get("collector_live_sha256") != _sha256(paths["live"])
        or invocation.get("collector_decision_sha256") != _sha256(paths["decision"])
        or invocation.get("collector_inspect_sha256") != _sha256(paths["inspect"])
        or invocation.get("git_commit_sha") != evidence_git_commit_sha
        or invocation.get("runtime_source_id") != result.get("decision_runtime_source_id")
        or invocation.get("runtime_source_digest") != result.get("decision_runtime_source_digest")
    ):
        raise ValueError("production-public collector invocation witness is invalid")
    current_identity = runtime_source_identity(require_clean=False)
    bound_identity = replace(current_identity, git_commit_sha=evidence_git_commit_sha)
    if bound_identity.runtime_source_id != result.get(
        "decision_runtime_source_id"
    ) or bound_identity.runtime_source_digest != result.get("decision_runtime_source_digest"):
        raise ValueError("production-public Decision runtime identity changed")
    projection = project_events(events)
    expected_decision_receipt = build_decision_receipt(
        manifest,
        projection,
        source_identity=current_identity,
        receipt_git_commit_sha=evidence_git_commit_sha,
    )
    expected_decision = decision_receipt_payload(expected_decision_receipt)
    if decision != expected_decision:
        raise ValueError("production-public collector Decision receipt is not reconstructed")
    expected_inspect = inspect_payload(manifest, events, source_identity=bound_identity)
    if inspected != expected_inspect:
        raise ValueError("production-public collector inspect is not reconstructed")
    expected_live = {
        "receipt_type": CAPTURE_RECEIPT_TYPE,
        "environment": "production_public",
        "duration_seconds": 3_665,
        **_event_summary(manifest, events),
        **projection_payload(projection),
        "decision_receipt_digest": expected_decision_receipt.digest,
        "git_commit_sha": evidence_git_commit_sha,
        "runtime_source_id": bound_identity.runtime_source_id,
        "runtime_source_digest": bound_identity.runtime_source_digest,
        "evidence_class": LIVE_CAPTURE_EVIDENCE,
    }
    if live != expected_live:
        raise ValueError("production-public collector live receipt is not reconstructed")


def _copy_tree_files(source: Path, target: Path) -> None:
    if not source.is_dir():
        raise ValueError(f"evidence directory is missing: {source}")
    for path in sorted(item for item in source.rglob("*") if item.is_file()):
        relative = path.relative_to(source)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


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


def _report_lines(
    label: str, result: dict[str, object], replay: dict[str, object]
) -> tuple[str, ...]:
    return (
        f"## {label}",
        "",
        f"- 证据类别 / provenance: `{result.get('evidence_class')}` / "
        f"`{result.get('fact_provenance')}`",
        f"- records / actual public trades: `{result.get('records')}` / "
        f"`{result.get('actual_trades')}`",
        f"- coverage / readiness: frame_complete=`{result.get('decision_frame_complete')}`, "
        f"readiness=`{result.get('decision_readiness')}`, "
        f"windows=`{result.get('required_window_coverage')}`",
        f"- gap / reconnect: trade=`{result.get('trade_gap_records')}`, "
        f"book=`{result.get('book_gap_records')}`, reconnect=`{result.get('reconnect_records')}`",
        f"- platform: state=`{result.get('platform_state')}`, "
        f"locked=`{result.get('platform_locked')}`, "
        f"sources=`{result.get('platform_source_capture_seqs')}`",
        f"- source anomalies: collector elapsed regressions="
        f"`{result.get('collector_elapsed_regressions')}`, ticker source regressions="
        f"`{result.get('ticker_source_regressions')}`, trade source regressions="
        f"`{result.get('trade_source_regressions')}`",
        f"- cutoff / prefix / suffix: `{result.get('decision_cutoff_capture_seq')}` / "
        f"`{result.get('prefix_record_count')}` / `{result.get('suffix_record_count')}` "
        f"(`{result.get('suffix_first_capture_seq')}`.."
        f"`{result.get('suffix_last_capture_seq')}`)",
        f"- action / admission: `{result.get('decision_action')}` / "
        f"`{result.get('admission_status')}`; reasons=`{result.get('admission_reasons')}`",
        f"- Entry / Outcome: `{result.get('entry_count')}` / "
        f"`{result.get('outcome_count')}`; status=`{result.get('outcome_status')}`; "
        f"UNKNOWN=`{result.get('unknown_reasons')}`",
        f"- capture / manifest / seal digests: `{result.get('full_capture_digest')}` / "
        f"`{result.get('full_capture_manifest_digest')}` / `{result.get('fact_seal_digest')}`",
        f"- Decision / Entry / Outcome digests: `{result.get('decision_receipt_digest')}` / "
        f"`{result.get('entry_receipt_digest')}` / `{result.get('outcome_receipt_digest')}`",
        f"- Decision / Outcome runtime digests: "
        f"`{result.get('decision_runtime_source_digest')}` / "
        f"`{result.get('outcome_runtime_source_digest')}`",
        f"- input / Policy / Outcome contract digests: "
        f"`{result.get('input_contract_digest')}` / `{result.get('policy_digest')}` / "
        f"`{result.get('outcome_contract_digest')}`",
        f"- fresh-process drift (Decision / Entry / Outcome / future): "
        f"`{replay.get('decision_drift_count')}` / `{replay.get('entry_drift_count')}` / "
        f"`{replay.get('outcome_drift_count')}` / "
        f"`{replay.get('strict_future_violation_count')}`; "
        f"verified=`{replay.get('replay_verified')}`",
        "",
    )


def _report(
    synthetic: dict[str, object],
    synthetic_replay: dict[str, object],
    public: dict[str, object],
    public_replay: dict[str, object],
) -> str:
    return "\n".join(
        (
            "# OUTCOME_TRUTH 业务验收报告 (待人类验收)",
            "",
            f"- 生成时间: `{datetime.now(UTC).isoformat()}`",
            "",
            *_report_lines("SYNTHETIC_LOGIC", synthetic, synthetic_replay),
            f"- 合成 post-exit counterfactual points: "
            f"`{synthetic.get('counterfactual_point_count')}`",
            "- 合成事实只验证合同逻辑, 不属于 production-public 观测。",
            "",
            *_report_lines("BOUNDED_PUBLIC_CAPTURE", public, public_replay),
            "## Hash 与限制",
            "",
            "- bundle 内每个保留文件由 `SHA256SUMS` 覆盖; 归档由相邻 `.sha256` sidecar 覆盖。",
            "- production-public collector invocation witness 绑定 3,665 秒命令、Deribit 公网端点、",
            "  monotonic elapsed、collector 文件、capture、Git 与 Decision runtime identity;",
            "  它是进程证据; 不是第三方网络来源证明。",
            "本 bundle 只证明一次固定 cutoff 的 Decision prefix、严格未来 suffix、Entry/Outcome",
            "合同和 fresh-process 确定性重建。它不证明真实 fill、连续 Shadow、Policy 质量、",
            "盈利、NO_TRADE qualification、Challenger、Promotion、执行或资本权限。",
            "公网零 Entry/Outcome 或 UNKNOWN 是有效 fail-closed 结果; 可见 quote 不是 fill,",
            "replay 相等只证明重建, 不证明数据完整、Policy 质量或经济接受。",
            "",
        )
    )


def create_outcome_evidence_bundle(
    *,
    synthetic_run: Path,
    synthetic_replay: Path,
    public_run: Path,
    public_replay: Path,
    output: Path,
) -> dict[str, object]:
    archive = output.with_suffix(".tar.gz")
    sidecar = Path(str(archive) + ".sha256")
    if output.exists() or archive.exists() or sidecar.exists():
        raise ValueError("Outcome evidence bundle output already exists")
    synthetic_result = _json_object(synthetic_run / "result.json", "synthetic result")
    synthetic_replay_result = _json_object(synthetic_replay / "replay.json", "synthetic replay")
    public_result = _json_object(public_run / "result.json", "public result")
    public_replay_result = _json_object(public_replay / "replay.json", "public replay")
    _validate_cases(
        synthetic_result,
        synthetic_replay_result,
        public_result,
        public_replay_result,
    )
    _validate_receipt_files(synthetic_run, synthetic_result, "synthetic")
    _validate_receipt_files(public_run, public_result, "production-public")
    _validate_public_collector_artifacts(public_run, public_result)
    public_invocation = _json_object(
        public_run / "collector-invocation.json",
        "public collector invocation",
    )
    output.mkdir(parents=True)
    _copy_tree_files(synthetic_run, output / "synthetic" / "run")
    _copy_tree_files(synthetic_replay, output / "synthetic" / "replay")
    _copy_tree_files(public_run, output / "production-public" / "run")
    _copy_tree_files(public_replay, output / "production-public" / "replay")
    (output / "ACCEPTANCE.zh-CN.md").write_text(
        _report(
            synthetic_result,
            synthetic_replay_result,
            public_result,
            public_replay_result,
        ),
        encoding="utf-8",
    )
    artifact_paths = tuple(
        sorted(item.relative_to(output).as_posix() for item in output.rglob("*") if item.is_file())
    )
    artifacts = tuple(
        {
            "path": relative,
            "bytes": (output / relative).stat().st_size,
            "sha256": _sha256(output / relative),
        }
        for relative in artifact_paths
    )
    manifest = {
        "bundle_format": BUNDLE_FORMAT_ID,
        "generated_at": datetime.now(UTC).isoformat(),
        "synthetic_result_digest": synthetic_result.get("result_digest"),
        "synthetic_entry_receipt_digest": synthetic_result.get("entry_receipt_digest"),
        "synthetic_outcome_receipt_digest": synthetic_result.get("outcome_receipt_digest"),
        "synthetic_outcome_runtime_source_digest": synthetic_result.get(
            "outcome_runtime_source_digest"
        ),
        "public_result_digest": public_result.get("result_digest"),
        "public_entry_count": public_result.get("entry_count"),
        "public_outcome_count": public_result.get("outcome_count"),
        "public_outcome_status": public_result.get("outcome_status"),
        "public_full_capture_digest": public_result.get("full_capture_digest"),
        "public_decision_receipt_digest": public_result.get("decision_receipt_digest"),
        "public_entry_receipt_digest": public_result.get("entry_receipt_digest"),
        "public_outcome_receipt_digest": public_result.get("outcome_receipt_digest"),
        "public_outcome_runtime_source_digest": public_result.get("outcome_runtime_source_digest"),
        "public_collector_invocation_digest": public_invocation.get("invocation_digest"),
        "artifacts": artifacts,
    }
    (output / "BUNDLE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    checksum_paths = tuple(
        sorted(
            item.relative_to(output).as_posix()
            for item in output.rglob("*")
            if item.is_file() and item.name != "SHA256SUMS"
        )
    )
    (output / "SHA256SUMS").write_text(
        "".join(f"{_sha256(output / relative)}  {relative}\n" for relative in checksum_paths),
        encoding="utf-8",
    )
    verification = verify_outcome_evidence_bundle(output)
    _write_archive(output, archive)
    archive_digest = _sha256(archive)
    sidecar.write_text(f"{archive_digest}  {archive.name}\n", encoding="utf-8")
    return {
        **verification,
        "bundle_path": str(output),
        "archive_path": str(archive),
        "archive_sha256": archive_digest,
        "archive_sha256_path": str(sidecar),
    }


def verify_outcome_evidence_bundle(
    bundle: Path,
    *,
    archive: Path | None = None,
) -> dict[str, object]:
    checksum_file = bundle / "SHA256SUMS"
    if not checksum_file.is_file():
        raise ValueError("Outcome evidence bundle has no SHA256SUMS")
    entries: list[tuple[str, str]] = []
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        digest, separator, relative = line.partition("  ")
        if not separator or len(digest) != 64 or not relative:
            raise ValueError("Outcome evidence checksum line is invalid")
        target = bundle / relative
        if bundle.resolve() not in target.resolve().parents:
            raise ValueError("Outcome evidence checksum path escapes its root")
        if not target.is_file() or _sha256(target) != digest:
            raise ValueError(f"Outcome evidence checksum mismatch: {relative}")
        entries.append((relative, digest))
    if len(entries) != len({relative for relative, _digest in entries}):
        raise ValueError("Outcome evidence checksum paths contain duplicates")
    expected = {
        item.relative_to(bundle).as_posix()
        for item in bundle.rglob("*")
        if item.is_file() and item.name != "SHA256SUMS"
    }
    if {item[0] for item in entries} != expected:
        raise ValueError("Outcome evidence checksum coverage is incomplete")
    manifest = _json_object(bundle / "BUNDLE_MANIFEST.json", "Outcome bundle manifest")
    if manifest.get("bundle_format") != BUNDLE_FORMAT_ID:
        raise ValueError("Outcome evidence bundle format is invalid")
    synthetic = _json_object(bundle / "synthetic/run/result.json", "synthetic result")
    synthetic_replay = _json_object(bundle / "synthetic/replay/replay.json", "synthetic replay")
    public = _json_object(bundle / "production-public/run/result.json", "public result")
    public_invocation = _json_object(
        bundle / "production-public/run/collector-invocation.json",
        "public collector invocation",
    )
    public_replay = _json_object(bundle / "production-public/replay/replay.json", "public replay")
    _validate_cases(synthetic, synthetic_replay, public, public_replay)
    raw_artifacts = manifest.get("artifacts")
    if not isinstance(raw_artifacts, list):
        raise ValueError("Outcome evidence manifest artifacts are invalid")
    expected_artifact_paths = expected - {"BUNDLE_MANIFEST.json"}
    manifest_artifact_paths: set[str] = set()
    for raw_artifact in raw_artifacts:
        if not isinstance(raw_artifact, dict):
            raise ValueError("Outcome evidence manifest artifact is invalid")
        artifact = cast(dict[str, object], raw_artifact)
        raw_relative = artifact.get("path")
        if not isinstance(raw_relative, str) or raw_relative in manifest_artifact_paths:
            raise ValueError("Outcome evidence manifest artifact path is invalid")
        target = bundle / raw_relative
        if (
            raw_relative not in expected_artifact_paths
            or artifact.get("bytes") != target.stat().st_size
            or artifact.get("sha256") != _sha256(target)
        ):
            raise ValueError(f"Outcome evidence manifest artifact changed: {raw_relative}")
        manifest_artifact_paths.add(raw_relative)
    if manifest_artifact_paths != expected_artifact_paths:
        raise ValueError("Outcome evidence manifest artifact coverage is incomplete")
    expected_manifest_bindings = {
        "synthetic_result_digest": synthetic.get("result_digest"),
        "synthetic_entry_receipt_digest": synthetic.get("entry_receipt_digest"),
        "synthetic_outcome_receipt_digest": synthetic.get("outcome_receipt_digest"),
        "synthetic_outcome_runtime_source_digest": synthetic.get("outcome_runtime_source_digest"),
        "public_result_digest": public.get("result_digest"),
        "public_entry_count": public.get("entry_count"),
        "public_outcome_count": public.get("outcome_count"),
        "public_outcome_status": public.get("outcome_status"),
        "public_full_capture_digest": public.get("full_capture_digest"),
        "public_decision_receipt_digest": public.get("decision_receipt_digest"),
        "public_entry_receipt_digest": public.get("entry_receipt_digest"),
        "public_outcome_receipt_digest": public.get("outcome_receipt_digest"),
        "public_outcome_runtime_source_digest": public.get("outcome_runtime_source_digest"),
        "public_collector_invocation_digest": public_invocation.get("invocation_digest"),
    }
    if any(manifest.get(key) != value for key, value in expected_manifest_bindings.items()):
        raise ValueError("Outcome evidence manifest digest binding changed")
    _validate_receipt_files(bundle / "synthetic/run", synthetic, "synthetic")
    _validate_receipt_files(
        bundle / "production-public/run",
        public,
        "production-public",
    )
    _validate_public_collector_artifacts(bundle / "production-public/run", public)
    from radar_runtime.outcome_runtime import reconstruct_outcome

    if reconstruct_outcome(bundle / "synthetic/run") != synthetic_replay:
        raise ValueError("synthetic replay is not a fresh reconstruction of its run")
    if reconstruct_outcome(bundle / "production-public/run") != public_replay:
        raise ValueError("production-public replay is not a fresh reconstruction of its run")
    result: dict[str, object] = {
        "bundle_format": BUNDLE_FORMAT_ID,
        "bundle_verified": True,
        "checksum_entries": len(entries),
        "sha256sums_sha256": _sha256(checksum_file),
        "synthetic_outcome_receipt_digest": synthetic.get("outcome_receipt_digest"),
        "public_outcome_receipt_digest": public.get("outcome_receipt_digest"),
        "outcome_runtime_source_digest": public.get("outcome_runtime_source_digest"),
        "public_collector_invocation_digest": public_invocation.get("invocation_digest"),
    }
    if archive is not None:
        if not archive.is_file():
            raise ValueError("Outcome evidence archive is missing")
        archived: dict[str, tuple[int, str]] = {}
        with tarfile.open(archive, mode="r:gz") as source:
            for member in source.getmembers():
                if not member.isfile():
                    raise ValueError("Outcome evidence archive contains a non-file member")
                member_path = PurePosixPath(member.name)
                if (
                    member_path.is_absolute()
                    or ".." in member_path.parts
                    or member.name in archived
                ):
                    raise ValueError("Outcome evidence archive member path is unsafe or duplicate")
                handle = source.extractfile(member)
                if handle is None:
                    raise ValueError("Outcome evidence archive member is unreadable")
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
            raise ValueError("Outcome evidence archive contents disagree with the bundle")
        sidecar = Path(str(archive) + ".sha256")
        if not sidecar.is_file():
            raise ValueError("Outcome evidence archive checksum sidecar is missing")
        sidecar_line = sidecar.read_text(encoding="utf-8").strip()
        expected_line = f"{_sha256(archive)}  {archive.name}"
        if sidecar_line != expected_line:
            raise ValueError("Outcome evidence archive checksum sidecar disagrees")
        result["archive_path"] = str(archive)
        result["archive_sha256"] = _sha256(archive)
    return result
