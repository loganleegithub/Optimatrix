from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal

IDENTITY_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
GIT_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")


class IdentityError(ValueError):
    """A value cannot participate in the frozen canonical identity encoding."""


def canonical_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise IdentityError("canonical Decimal must be finite")
    if value == 0:
        return "0"
    normalized = value.normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text == "-0":
        return "0"
    return text


def canonical_value(value: object) -> object:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, Decimal):
        return canonical_decimal(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        raise IdentityError("binary floating-point is forbidden in an identity preimage")
    if isinstance(value, Mapping):
        converted: dict[str, object] = {}
        for key, member in value.items():
            if not isinstance(key, str):
                raise IdentityError("canonical object keys must be strings")
            converted[key] = canonical_value(member)
        return converted
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [canonical_value(member) for member in value]
    as_object = getattr(value, "as_object", None)
    if callable(as_object):
        return canonical_value(as_object())
    raise IdentityError(f"unsupported canonical value type: {type(value).__name__}")


def canonical_identity(label: str, *members: object) -> str:
    if not label:
        raise IdentityError("identity label must be non-empty")
    preimage = json.dumps(
        [label, *(canonical_value(member) for member in members)],
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(preimage).hexdigest()}"


def require_identity(value: object, field: str) -> str:
    if not isinstance(value, str) or IDENTITY_PATTERN.fullmatch(value) is None:
        raise IdentityError(f"{field} must be sha256:<64 lowercase hex>")
    return value


def require_code_identity(value: object, field: str = "code_identity") -> str:
    if not isinstance(value, str) or GIT_COMMIT_PATTERN.fullmatch(value) is None:
        raise IdentityError(f"{field} must be one lowercase 40-hex Git commit")
    return value
