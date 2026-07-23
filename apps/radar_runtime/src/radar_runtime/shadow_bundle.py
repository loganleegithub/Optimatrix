"""Durable evidence bundle for one Fixed-Policy public-Shadow closure."""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import tarfile
from pathlib import Path, PurePosixPath
from typing import cast

from market_tape import canonical_digest, canonical_value

from radar_runtime.shadow_runtime import (
    HISTORICAL_SEMANTIC_RECEIPT_TYPE,
    replay_shadow,
)

BUNDLE_FORMAT_ID = "OPTIMATRIX_FIXED_POLICY_PUBLIC_SHADOW_EVIDENCE_BUNDLE"


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


def _validate_replay(replay: dict[str, object], label: str) -> None:
    if (
        replay.get("replay_verified") is not True
        or replay.get("computation_reconstructed") is not True
        or replay.get("prefix_causality_verified") is not True
        or replay.get("online_persistence_process_witness_verified") is not True
        or replay.get("external_source_attested") is not False
        or replay.get("attempt_selection_attested") is not False
        or replay.get("online_persistence_external_attested") is not False
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
) -> str:
    return "\n".join(
        (
            "# Fixed-Policy Public Shadow 验收报告",
            "",
            f"- 报告生成时间: `{generated_at}`",
            f"- 合成 Run: complete=`{synthetic.get('complete')}`, "
            f"records=`{synthetic.get('records')}`",
            f"- 合成会计: `{json.dumps(synthetic.get('accounting'), sort_keys=True, ensure_ascii=False)}`",
            f"- 生产公开 Run: complete=`{public.get('complete')}`, "
            f"records=`{public.get('records')}`",
            f"- 生产公开会计: `{json.dumps(public.get('accounting'), sort_keys=True, ensure_ascii=False)}`",
            f"- 合成 replay: verified=`{synthetic_replay.get('replay_verified')}`, "
            f"prefix_causality=`{synthetic_replay.get('prefix_causality_verified')}`",
            f"- 生产 replay: verified=`{public_replay.get('replay_verified')}`, "
            f"collector_witness=`{public_replay.get('collector_witness_verified')}`",
            f"- 历史语义回归: authoritative=`{semantic.get('authoritative_replay')}`, "
            f"Decision drift=`{semantic.get('decision_semantic_drift_count')}`, "
            f"Outcome drift=`{semantic.get('outcome_semantic_drift_count')}`",
            "",
            "## 边界",
            "",
            "- public quotes 不是 fills; 本证据不证明账户、订单、成交或执行。",
            "- `NO_TRADE=0` 是无持仓定义值, 不是资格赛、Policy 质量或盈利证明。",
            "- replay 相等只证明封存输入的确定性重建, 不证明第三方来源或物理 fsync 时刻。",
            "- `attempt_selection_attested=false`; 证据不能证明外部操作者未丢弃另一尝试。",
            "- 不授权 Challenger、qualification、promotion、private API、execution 或 capital。",
            "",
        )
    )


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
    invocation = _json_object(public_run / "invocation-witness.json")
    generated_at = cast(str, invocation["invocation_finished_at"])
    report = _report(
        generated_at=generated_at,
        synthetic=synthetic,
        synthetic_replay=synthetic_replayed,
        public=public,
        public_replay=public_replayed,
        semantic=semantic,
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
    if (
        manifest.get("bundle_format") != BUNDLE_FORMAT_ID
        or not isinstance(manifest_digest, str)
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
    _validate_replay(synthetic_replayed, "synthetic")
    _validate_replay(public_replayed, "production-public")
    if (
        manifest.get("synthetic_result_digest") != synthetic.get("result_digest")
        or manifest.get("synthetic_replay_digest") != synthetic_replayed.get("replay_digest")
        or manifest.get("public_result_digest") != public.get("result_digest")
        or manifest.get("public_replay_digest") != public_replayed.get("replay_digest")
        or manifest.get("semantic_regression_digest") != semantic.get("receipt_digest")
    ):
        raise ValueError("Shadow evidence manifest bindings changed")
    expected_report = _report(
        generated_at=cast(str, manifest["generated_at"]),
        synthetic=synthetic,
        synthetic_replay=synthetic_replayed,
        public=public,
        public_replay=public_replayed,
        semantic=semantic,
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
        "checksum_entries": len(checksum_paths),
        "bundle_manifest_digest": manifest_digest,
        "archive_sha256": _sha256(archive) if archive is not None else None,
    }
