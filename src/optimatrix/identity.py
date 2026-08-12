from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum


def canonical_value(value: object) -> object:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("identity datetimes must be timezone-aware")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("identity values must be finite")
        return format(value, "f")
    if isinstance(value, Enum):
        return canonical_value(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return canonical_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): canonical_value(member) for key, member in sorted(value.items())}
    if isinstance(value, tuple | list):
        return [canonical_value(member) for member in value]
    if isinstance(value, set | frozenset):
        normalized = [canonical_value(member) for member in value]
        return sorted(normalized, key=lambda member: json.dumps(member, sort_keys=True))
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        raise TypeError("float is not accepted in canonical business identities")
    raise TypeError(f"unsupported canonical value: {type(value)!r}")


def canonical_identity(kind: str, *members: object) -> str:
    if not kind:
        raise ValueError("identity kind must be non-empty")
    payload = json.dumps(
        {"kind": kind, "members": canonical_value(members)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def require_identity(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
        raise ValueError(f"{field} must be a sha256 identity")
    try:
        int(value.removeprefix("sha256:"), 16)
    except ValueError as exc:
        raise ValueError(f"{field} must contain hexadecimal digest text") from exc
    return value
