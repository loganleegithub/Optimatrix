from pathlib import Path

path = Path('.github/r4_apply.py')
text = path.read_text(encoding='utf-8')
replacements = (
    (
        '    ps_states = iter(("123\\n", "123\\n", ""))',
        '    ps_states = iter(("123\\\\n", "123\\\\n", ""))',
    ),
    (
        '''_PRODUCTION_PROBE_PLIST = Path(
    "/Users/logan/Library/LaunchAgents/com.optimatrix.public-shadow.r3.probe.plist"
)
_LIFECYCLE_WAIT_MS = 30_000''',
        '''_PRODUCTION_PROBE_PLIST = Path(
    "/Users/logan/Library/LaunchAgents/com.optimatrix.public-shadow.r3.probe.plist"
)
_PRODUCTION_ENVELOPE = _PRODUCTION_ROOT / "deployment/deployment-envelope.json"
_LIFECYCLE_WAIT_MS = 30_000''',
    ),
    (
        '''_PRODUCTION_PROBE_PLIST = Path(
    "/Users/logan/Library/LaunchAgents/com.optimatrix.public-shadow.r4.probe.plist"
)
_LIFECYCLE_WAIT_MS = 30_000''',
        '''_PRODUCTION_PROBE_PLIST = Path(
    "/Users/logan/Library/LaunchAgents/com.optimatrix.public-shadow.r4.probe.plist"
)
_PRODUCTION_ENVELOPE = _PRODUCTION_ROOT / "deployment/deployment-envelope.json"
_LIFECYCLE_WAIT_MS = 30_000''',
    ),
)
for old, new in replacements:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'patcher hotfix expected one match, found {count}: {old[:80]!r}')
    text = text.replace(old, new)
path.write_text(text, encoding='utf-8')
