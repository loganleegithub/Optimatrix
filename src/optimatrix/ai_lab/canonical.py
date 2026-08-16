from __future__ import annotations

import json
import os
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from typing import Any

JsonObject = dict[str, Any]

PRODUCTION_REPOSITORY = Path("/Users/logan/Optimatrix")
SOURCE_REPOSITORY = Path(__file__).resolve().parents[3]
PRODUCTION_DURABLE_ROOT = Path("/Users/logan/Library/Application Support/Optimatrix")
AI_LAB_DURABLE_ROOT = PRODUCTION_DURABLE_ROOT / "ai-lab"
FORBIDDEN_ROOTS = tuple({PRODUCTION_REPOSITORY, SOURCE_REPOSITORY})


class ValidationError(ValueError):
    """An input failed a fail-closed schema or causal-boundary check."""


def canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"value is not canonical JSON: {exc}") from exc


def content_id(namespace: str, value: object) -> str:
    if not namespace:
        raise ValidationError("content identity namespace must be non-empty")
    digest = sha256(canonical_bytes({"namespace": namespace, "value": value})).hexdigest()
    return f"sha256:{digest}"


def is_content_id(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    digest = value.removeprefix("sha256:")
    return len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)


def require_content_id(value: object, name: str) -> str:
    if not is_content_id(value):
        raise ValidationError(f"{name} must be a sha256 content identity")
    return str(value)


def seal_object(value: Mapping[str, object], *, id_field: str, namespace: str) -> JsonObject:
    if id_field in value:
        raise ValidationError(f"draft {id_field} must be absent before sealing")
    sealed = deepcopy(dict(value))
    sealed[id_field] = content_id(namespace, sealed)
    return sealed


def verify_seal(value: Mapping[str, object], *, id_field: str, namespace: str) -> None:
    identifier = require_content_id(value.get(id_field), id_field)
    payload = {key: member for key, member in value.items() if key != id_field}
    if identifier != content_id(namespace, payload):
        raise ValidationError(f"{id_field} content identity mismatch")


def parse_utc(value: object, name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValidationError(f"{name} must be canonical UTC text ending in Z")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ValidationError(f"{name} is not a valid UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValidationError(f"{name} must be UTC")
    if utc_text(parsed) != value:
        raise ValidationError(f"{name} must use canonical UTC formatting")
    return parsed


def utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValidationError("datetime must be UTC-aware")
    value = value.astimezone(UTC)
    timespec = "microseconds" if value.microsecond else "seconds"
    return value.isoformat(timespec=timespec).replace("+00:00", "Z")


def parse_decimal(value: object, name: str, *, positive: bool = False) -> Decimal:
    if not isinstance(value, str):
        raise ValidationError(f"{name} must be an exact decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValidationError(f"{name} is not a decimal") from exc
    if not parsed.is_finite() or (positive and parsed <= 0):
        qualifier = "finite and positive" if positive else "finite"
        raise ValidationError(f"{name} must be {qualifier}")
    return parsed


def decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ValidationError("decimal result must be finite")
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def strict_fields(value: object, expected: set[str], name: str) -> JsonObject:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValidationError(f"{name} must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValidationError(f"{name} fields are invalid; missing={missing}, extra={extra}")
    return value


def require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError(f"{name} must be non-empty text")
    return value


def require_bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationError(f"{name} must be boolean")
    return value


def require_int(value: object, name: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValidationError(f"{name} must be an integer >= {minimum}")
    return value


def require_text_list(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValidationError(f"{name} must be an array of non-empty strings")
    if len(set(value)) != len(value):
        raise ValidationError(f"{name} must not contain duplicates")
    return tuple(value)


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> JsonObject:
    result: JsonObject = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> JsonObject:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ValidationError(f"input must not be a symlink: {expanded}")
    resolved = isolated_path(path, must_exist=True)
    if not resolved.is_file():
        raise ValidationError(f"input must be a regular, non-symlink file: {resolved}")
    try:
        value = json.loads(
            resolved.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=lambda constant: (_ for _ in ()).throw(
                ValidationError(f"non-finite JSON constant: {constant}")
            ),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read JSON input {resolved}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError("top-level JSON input must be an object")
    return value


def isolated_path(path: Path, *, must_exist: bool = False) -> Path:
    resolved = path.expanduser().resolve(strict=must_exist)
    for forbidden in FORBIDDEN_ROOTS:
        if resolved == forbidden or resolved.is_relative_to(forbidden):
            raise ValidationError(f"production path is outside the AI Lab boundary: {resolved}")
    if (
        resolved == PRODUCTION_DURABLE_ROOT or resolved.is_relative_to(PRODUCTION_DURABLE_ROOT)
    ) and not (resolved == AI_LAB_DURABLE_ROOT or resolved.is_relative_to(AI_LAB_DURABLE_ROOT)):
        raise ValidationError(f"runtime durable path is outside the AI Lab boundary: {resolved}")
    return resolved


def write_new_json(path: Path, value: Mapping[str, object]) -> Path:
    resolved = isolated_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    try:
        with resolved.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ValidationError(f"refusing to overwrite existing file: {resolved}") from exc
    return resolved
