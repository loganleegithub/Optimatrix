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

zero_start = text.index("    zero_tests = '''")
zero_end = text.index("\n    text = replace_once(text, test_marker", zero_start)
zero_block = text[zero_start:zero_end]
old_zero_envelope = '''    envelope = CommissioningEnvelope.from_mapping(
        _envelope_mapping(tmp_path), allow_test_boundary=True
    )
'''
new_zero_envelope = '''    envelope_mapping = _envelope_mapping(tmp_path)
    envelope = CommissioningEnvelope.from_mapping(
        {
            key: value
            for key, value in envelope_mapping.items()
            if key in CommissioningEnvelope._KEYS
        },
        allow_test_boundary=True,
    )
'''
if zero_block.count(old_zero_envelope) != 2:
    raise SystemExit(
        f'zero-test envelope hotfix expected two matches, found '
        f'{zero_block.count(old_zero_envelope)}'
    )
zero_block = zero_block.replace(old_zero_envelope, new_zero_envelope)
text = text[:zero_start] + zero_block + text[zero_end:]

for old, new in replacements:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'patcher hotfix expected one match, found {count}: {old[:80]!r}')
    text = text.replace(old, new)
path.write_text(text, encoding='utf-8')
