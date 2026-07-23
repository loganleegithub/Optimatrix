"""Durable file bundle for one bounded Decision Truth evidence run."""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

BUNDLE_FORMAT_ID = "OPTIMATRIX_DECISION_TRUTH_EVIDENCE_BUNDLE"


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


def _require_equal(label: str, *values: object) -> object:
    if not values or any(type(item) is not type(values[0]) or item != values[0] for item in values):
        raise ValueError(f"evidence bundle {label} binding disagrees")
    return values[0]


def _validate_evidence(
    live: dict[str, object],
    decision: dict[str, object],
    inspect: dict[str, object],
    replay: dict[str, object],
) -> None:
    if live.get("environment") != "production_public":
        raise ValueError("evidence bundle requires production_public evidence")
    duration = live.get("duration_seconds")
    if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 3_600:
        raise ValueError("evidence bundle requires a capture strictly longer than 3600 seconds")
    _require_equal(
        "capture digest",
        live.get("capture_digest"),
        decision.get("capture_digest"),
        inspect.get("capture_digest"),
        replay.get("capture_digest"),
    )
    _require_equal(
        "Decision receipt digest",
        live.get("decision_receipt_digest"),
        decision.get("receipt_digest"),
        inspect.get("decision_receipt_digest"),
        replay.get("decision_receipt_digest"),
    )
    _require_equal(
        "runtime source digest",
        live.get("runtime_source_digest"),
        decision.get("runtime_source_digest"),
        inspect.get("runtime_source_digest"),
        replay.get("runtime_source_digest"),
    )
    if replay.get("decision_receipt_binding_verified") is not True:
        raise ValueError("evidence bundle replay did not verify the Decision receipt")
    if replay.get("decision_drift_count") != 0 or replay.get("decision_drift_fields") != []:
        raise ValueError("evidence bundle replay contains Decision drift")
    if replay.get("runtime_source_digest_match") is not True:
        raise ValueError("evidence bundle runtime source identity did not match")


def _format_counts(value: object) -> str:
    if not isinstance(value, list):
        return "[]"
    return (
        ", ".join(
            f"{item[0]}={item[1]}" for item in value if isinstance(item, list) and len(item) == 2
        )
        or "无"
    )


def _chinese_report(
    live: dict[str, object],
    inspect: dict[str, object],
    replay: dict[str, object],
) -> str:
    coverage = inspect.get("required_window_coverage")
    coverage_lines: list[str] = []
    if isinstance(coverage, list):
        for raw in coverage:
            if not isinstance(raw, dict):
                continue
            coverage_lines.append(
                "| {seconds} | {price} | {trade} | {reasons} |".format(
                    seconds=raw.get("requested_seconds"),
                    price=raw.get("price_complete"),
                    trade=raw.get("trade_complete"),
                    reasons=raw.get("incomplete_reasons"),
                )
            )
    unknowns = inspect.get("unknown_reasons")
    unknown_text = "、".join(str(item) for item in unknowns) if isinstance(unknowns, list) else ""
    readiness = inspect.get("decision_readiness")
    readiness_object = readiness if isinstance(readiness, dict) else {}
    return "\n".join(
        (
            "# DECISION_TRUTH 业务验收报告 (待人类验收)",
            "",
            f"- 生成时间: {datetime.now(UTC).isoformat()}",
            f"- 环境: `{live.get('environment')}`",
            f"- Capture 时长: `{live.get('duration_seconds')}s`",
            f"- 总 records: `{inspect.get('records')}`",
            f"- Actual public trades: `{inspect.get('actual_trades')}`",
            f"- Trade batch records: `{inspect.get('trade_batch_records')}`",
            f"- Record breakdown (instrument/ticker/heartbeat/platform/subscription/catalog/schedule): "
            f"`{inspect.get('instrument_records')}` / `{inspect.get('ticker_records')}` / "
            f"`{inspect.get('heartbeat_records')}` / `{inspect.get('platform_state_records')}` / "
            f"`{inspect.get('subscription_start_records')}` / "
            f"`{inspect.get('catalog_snapshot_records')}` / "
            f"`{inspect.get('scheduled_block_state_records')}`",
            f"- Action / reason: `{inspect.get('decision_action')}` / `{inspect.get('decision_reason')}`",
            f"- UNKNOWN: `{unknown_text or '无'}`",
            f"- Final event / frame seq: `{inspect.get('final_event_capture_seq')}` / `{inspect.get('frame_capture_seq')}`",
            f"- Frame complete / reasons: `{inspect.get('frame_complete')}` / `{inspect.get('unknown_reasons')}`",
            "",
            "## Required-window readiness",
            "",
            "| seconds | price complete | trade complete | incomplete reasons |",
            "|---:|---|---|---|",
            *coverage_lines,
            "",
            "## Opportunity 与评估",
            "",
            f"- Executable structures: `{inspect.get('executable_structure_count')}`",
            f"- Assessment opportunities: `{inspect.get('assessment_opportunity_count')}`",
            f"- Assessment unavailable: `{inspect.get('assessment_unavailable_count')}`",
            "- Unavailable reasons: `"
            + _format_counts(inspect.get("assessment_unavailable_reason_counts"))
            + "`",
            f"- Assessments / passed: `{inspect.get('assessment_count')}` / `{inspect.get('passed_assessment_count')}`",
            "- Predicate failures: `"
            + _format_counts(inspect.get("predicate_failure_counts"))
            + "`",
            f"- Research candidates / entries / Outcomes: `{inspect.get('research_candidate_count')}` / `{inspect.get('entry_count')}` / `{inspect.get('outcome_count')}`",
            "",
            "## Coverage、gap 与控制事实",
            "",
            f"- Trade gaps / reconnects: `{inspect.get('trade_gap_records')}` / `{inspect.get('reconnect_records')}`",
            f"- Book observed / book gaps: `{inspect.get('book_stream_observed')}` / `{inspect.get('book_gap_records')}`",
            f"- Catalog generation complete: `{inspect.get('catalog_generation_complete')}`",
            f"- Catalog generation: `{inspect.get('catalog_generation_id')}`",
            f"- Catalog metadata digest: `{inspect.get('catalog_metadata_set_digest')}`",
            f"- Scheduled source/current: `{inspect.get('scheduled_block_source_id')}` / `{inspect.get('scheduled_block_current')}`",
            "- Quote readiness: `"
            + json.dumps(readiness_object.get("quotes"), ensure_ascii=False, sort_keys=True)
            + "`",
            f"- Collector elapsed/wall regressions: `{inspect.get('collector_elapsed_regressions')}` / `{inspect.get('collector_wall_regressions')}`",
            f"- Trade/ticker source regressions: `{inspect.get('trade_source_regressions')}` / `{inspect.get('ticker_source_regressions')}`",
            f"- Exchange-ahead records and min/median/max ms: `{inspect.get('exchange_ahead_records')}` / `{inspect.get('exchange_minus_collector_min_ms')}` / `{inspect.get('exchange_minus_collector_median_ms')}` / `{inspect.get('exchange_minus_collector_max_ms')}`",
            "",
            "## 身份与重建",
            "",
            f"- Git commit (审计): `{live.get('git_commit_sha')}`",
            f"- Runtime source digest: `{live.get('runtime_source_digest')}`",
            f"- Capture digest: `{inspect.get('capture_digest')}`",
            f"- Frame digest: `{inspect.get('frame_digest')}`",
            f"- Frame lineage digest: `{inspect.get('frame_lineage_digest')}`",
            f"- Input contract: `{inspect.get('input_contract_id')}` / `{inspect.get('input_contract_digest')}`",
            f"- Policy: `{inspect.get('policy_id')}` / `{inspect.get('policy_digest')}`",
            f"- Structure set: `{inspect.get('structure_set_digest')}`",
            f"- Option quote set: `{inspect.get('option_quote_set_digest')}`",
            f"- Assessment set: `{inspect.get('assessment_set_digest')}`",
            f"- Decision evaluation: `{inspect.get('decision_evaluation_digest')}`",
            f"- Decision: `{inspect.get('decision_digest')}`",
            f"- Receipt: `{inspect.get('decision_receipt_digest')}`",
            f"- Replay runtime digest match: `{replay.get('runtime_source_digest_match')}`",
            f"- Decision drift: `{replay.get('decision_drift_count')}` / `{replay.get('decision_drift_fields')}`",
            "",
            "## 验收边界",
            "",
            "本 bundle 只证明一次密封 production-public 输入上的严格 as-of Decision truth、",
            "Receipt 完整性和独立确定性重建。它不证明数据连续采集、Policy 质量、收益、",
            "真实 fill、Outcome、Shadow qualification、Promotion、执行或资本权限。",
            "public trades 是公共市场成交, 不是账户成交。零 candidate、零 entry 和 UNKNOWN",
            "均可为有效 fail-closed 结果。最终接受或拒绝必须由人类业务验收决定。",
            "",
        )
    )


def _write_deterministic_archive(bundle: Path, archive: Path) -> None:
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


def create_evidence_bundle(
    *,
    capture_output: Path,
    inspect_path: Path,
    replay_path: Path,
    output: Path,
) -> dict[str, object]:
    if output.exists() or output.with_suffix(".tar.gz").exists():
        raise ValueError("evidence bundle output already exists")
    source_paths = {
        "capture/capture.jsonl": capture_output / "capture" / "capture.jsonl",
        "capture/manifest.json": capture_output / "capture" / "manifest.json",
        "decision.json": capture_output / "decision.json",
        "live.json": capture_output / "live.json",
        "inspect.json": inspect_path,
        "replay.json": replay_path,
    }
    missing = tuple(str(path) for path in source_paths.values() if not path.is_file())
    if missing:
        raise ValueError("evidence bundle input is missing: " + ",".join(missing))
    live = _json_object(source_paths["live.json"], "live result")
    decision = _json_object(source_paths["decision.json"], "Decision receipt")
    inspect = _json_object(source_paths["inspect.json"], "inspect result")
    replay = _json_object(source_paths["replay.json"], "replay result")
    _validate_evidence(live, decision, inspect, replay)

    output.mkdir(parents=True)
    for relative, source in source_paths.items():
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    artifact_records = tuple(
        {
            "path": relative,
            "bytes": (output / relative).stat().st_size,
            "sha256": _sha256(output / relative),
        }
        for relative in sorted(source_paths)
    )
    manifest = {
        "bundle_format": BUNDLE_FORMAT_ID,
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": live["environment"],
        "duration_seconds": live["duration_seconds"],
        "capture_digest": live["capture_digest"],
        "decision_receipt_digest": decision["receipt_digest"],
        "git_commit_sha": decision["git_commit_sha"],
        "runtime_source_id": decision["runtime_source_id"],
        "runtime_source_digest": decision["runtime_source_digest"],
        "artifacts": artifact_records,
    }
    (output / "BUNDLE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (output / "ACCEPTANCE.zh-CN.md").write_text(
        _chinese_report(live, inspect, replay),
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
    verification = verify_evidence_bundle(output)
    archive = output.with_suffix(".tar.gz")
    _write_deterministic_archive(output, archive)
    archive_sha256 = _sha256(archive)
    sidecar = Path(str(archive) + ".sha256")
    sidecar.write_text(f"{archive_sha256}  {archive.name}\n", encoding="utf-8")
    return {
        **verification,
        "bundle_path": str(output),
        "archive_path": str(archive),
        "archive_sha256": archive_sha256,
        "archive_bytes": archive.stat().st_size,
        "archive_sha256_path": str(sidecar),
    }


def verify_evidence_bundle(bundle: Path, *, archive: Path | None = None) -> dict[str, object]:
    checksum_file = bundle / "SHA256SUMS"
    if not checksum_file.is_file():
        raise ValueError("evidence bundle has no SHA256SUMS")
    entries: list[tuple[str, str]] = []
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        digest, separator, relative = line.partition("  ")
        if not separator or len(digest) != 64 or not relative:
            raise ValueError("evidence bundle checksum line is invalid")
        target = bundle / relative
        if (
            target.resolve().parent != bundle.resolve()
            and bundle.resolve() not in target.resolve().parents
        ):
            raise ValueError("evidence bundle checksum path escapes its root")
        if not target.is_file() or _sha256(target) != digest:
            raise ValueError(f"evidence bundle checksum mismatch: {relative}")
        entries.append((relative, digest))
    if len(entries) != len({relative for relative, _digest in entries}):
        raise ValueError("evidence bundle checksum paths contain duplicates")
    expected = {
        item.relative_to(bundle).as_posix()
        for item in bundle.rglob("*")
        if item.is_file() and item.name != "SHA256SUMS"
    }
    if {item[0] for item in entries} != expected:
        raise ValueError("evidence bundle checksum coverage is incomplete")
    manifest = _json_object(bundle / "BUNDLE_MANIFEST.json", "bundle manifest")
    if manifest.get("bundle_format") != BUNDLE_FORMAT_ID:
        raise ValueError("evidence bundle format is invalid")
    result: dict[str, object] = {
        "bundle_format": BUNDLE_FORMAT_ID,
        "bundle_verified": True,
        "checksum_entries": len(entries),
        "sha256sums_sha256": _sha256(checksum_file),
        "decision_receipt_digest": manifest.get("decision_receipt_digest"),
        "runtime_source_digest": manifest.get("runtime_source_digest"),
    }
    if archive is not None:
        if not archive.is_file():
            raise ValueError("evidence bundle archive is missing")
        result["archive_path"] = str(archive)
        result["archive_sha256"] = _sha256(archive)
    return result
