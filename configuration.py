"""Read explicitly requested business secrets from the project's private .env.

Values are literals: no shell evaluation, variable expansion, process-environment
loading, or fallback credential source. Callers receive only their named fields.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat

GREEKS_FIELDS = frozenset({"GREEKS_LIVE_AUTH_TOKEN", "GREEKS_LIVE_DATA_API_KEY"})
TESTNET_FIELDS = frozenset({"DERIBIT_TESTNET_CLIENT_ID", "DERIBIT_TESTNET_CLIENT_SECRET"})
SECRET_FIELDS = GREEKS_FIELDS | TESTNET_FIELDS
MAX_CONFIG_BYTES = 65536
MAX_VALUE_CHARS = 16384
_ASSIGNMENT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)")


class ConfigurationError(Exception):
    """Deliberately contains no input, filename detail, or underlying exception."""

    def __init__(self):
        super().__init__("本机 .env 配置格式或权限无效；需为本人持有的 0600 常规文件")


def _value(text):
    text = text.strip()
    if not text:
        return ""
    if text[0] in "\"'":
        quote = text[0]
        end = text.find(quote, 1)
        if end < 0:
            raise ConfigurationError()
        tail = text[end + 1:]
        if tail and (not tail[0].isspace() or (tail.strip() and not tail.lstrip().startswith("#"))):
            raise ConfigurationError()
        value = text[1:end]
    else:
        # A hash within a token is literal; whitespace followed by # is a comment.
        value = re.split(r"\s+#", text, maxsplit=1)[0].rstrip()
        if value.startswith("#"):
            value = ""
        if any(char in "\"'" for char in value):
            raise ConfigurationError()
    if len(value) > MAX_VALUE_CHARS or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ConfigurationError()
    return value


def _parse(text, requested):
    result, seen = {}, set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = _ASSIGNMENT.fullmatch(line)
        if match is None:
            raise ConfigurationError()
        name, raw = match.groups()
        if name in seen:
            raise ConfigurationError()
        seen.add(name)
        value = _value(raw)
        if name in requested and value:
            result[name] = value
    return result


def read_secrets(root, allowed_names):
    """Return requested configured fields only; an absent .env returns {}.

    A malformed or insecure existing file fails closed. Reading does not mutate
    os.environ, and neither environment variables nor legacy JSON are consulted.
    """
    requested = frozenset(allowed_names)
    if not requested <= SECRET_FIELDS:
        raise ConfigurationError()
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
        try:
            fd = os.open(Path(root) / ".env", flags)
        except FileNotFoundError:
            return {}
        with os.fdopen(fd, "rb") as source:
            before = os.fstat(source.fileno())
            if (not stat.S_ISREG(before.st_mode) or stat.S_IMODE(before.st_mode) != 0o600
                    or before.st_uid != os.getuid() or before.st_nlink != 1
                    or before.st_size > MAX_CONFIG_BYTES):
                raise ConfigurationError()
            content = source.read(MAX_CONFIG_BYTES + 1)
            after = os.fstat(source.fileno())
            identity = ("st_dev", "st_ino", "st_size", "st_mode", "st_uid", "st_nlink", "st_mtime_ns", "st_ctime_ns")
            if (len(content) > MAX_CONFIG_BYTES or before.st_size != len(content)
                    or any(getattr(before, field) != getattr(after, field) for field in identity)):
                raise ConfigurationError()
        return _parse(content.decode("utf-8"), requested)
    except (OSError, UnicodeError, ValueError):
        raise ConfigurationError() from None
