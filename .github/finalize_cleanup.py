from __future__ import annotations

import base64
import gzip
import hashlib
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def require_sha(path: Path, expected: str) -> None:
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit(f"SHA-256 mismatch for {path}: {actual}")


def replace_once(path_name: str, old: str, new: str) -> None:
    path = Path(path_name)
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"unexpected replacement boundary: {path_name} count={count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


part00 = Path(".github/cleanup.patch.part00")
part01 = Path(".github/cleanup.patch.part01")
part02 = Path(".github/cleanup.patch.part02")

value = part01.read_bytes()
polluted = b"kweeted0k6"
exact = b"ketted0k6"
if value.count(polluted) != 1 or exact in value:
    raise SystemExit("unexpected cleanup part01 transport shape")
part01.write_bytes(value.replace(polluted, exact, 1))

require_sha(part00, "2432f70a9e4c422b36f4c8bac3731ea6b2e7cc4227776327059661e0ff8ead2b")
require_sha(part01, "e2f550168a3952e5199c424e387809bbc18eb06088cf4ac84d90dd88b5f11ece")
require_sha(part02, "e101bccc9a8c7cc76d0fdd83d391770e2b2aaec1cee7d3e432cfd4b7c2159ea0")

encoded = part00.read_bytes() + part01.read_bytes() + part02.read_bytes()
if hashlib.sha256(encoded).hexdigest() != "8aea83f53a5f23362699dd27283700a2a1c7bbb6d4a1ab34bfdcb927106824ad":
    raise SystemExit("combined cleanup transport digest mismatch")
patch_bytes = gzip.decompress(base64.b64decode(encoded, validate=True))
if hashlib.sha256(patch_bytes).hexdigest() != "fa7a904e581ccd31d1a17e7d33ecb6abef96100f207db9607a593d5e1778eb8e":
    raise SystemExit("cleanup patch digest mismatch")
patch_path = Path("/tmp/optimatrix-cleanup.patch")
patch_path.write_bytes(patch_bytes)
run("git", "apply", "--check", str(patch_path))
run("git", "apply", "--index", str(patch_path))

# Add the one missing test type import.
test_file = Path("tests/test_short_vol_underwriting.py")
text = test_file.read_text(encoding="utf-8")
future = "from __future__ import annotations\n\n"
mapping_import = "from collections.abc import Mapping\n"
if mapping_import in text or text.count(future) != 1:
    raise SystemExit("unexpected Mapping import boundary")
test_file.write_text(text.replace(future, future + mapping_import + "\n", 1), encoding="utf-8")

# Narrow Optional current-state identities before returning them.
evidence = "packages/short_vol_underwriting/src/short_vol_underwriting/evidence.py"
replace_once(
    evidence,
    '            scope = self._scope_by_availability.get(availability)\n'
    '            if scope is None:\n'
    '                raise ShadowStateError("Underwriting action lacks its current availability scope")\n'
    '            return "scope", scope\n',
    '            owning_scope = self._scope_by_availability.get(availability)\n'
    '            if owning_scope is None:\n'
    '                raise ShadowStateError("Underwriting action lacks its current availability scope")\n'
    '            return "scope", owning_scope\n',
)
replace_once(
    evidence,
    '            entry = self._entry_by_post_close_attempt.get(scheduled)\n'
    '            if entry is None:\n'
    '                raise ShadowStateError("post-CLOSE terminal lacks its current Case")\n'
    '            return "entry", entry\n',
    '            owning_entry = self._entry_by_post_close_attempt.get(scheduled)\n'
    '            if owning_entry is None:\n'
    '                raise ShadowStateError("post-CLOSE terminal lacks its current Case")\n'
    '            return "entry", owning_entry\n',
)
replace_once(
    evidence,
    '            entry = self._entry_by_observation.get(observation)\n'
    '            if entry is None:\n'
    '                raise ShadowStateError("selected exit lacks its current Case observation")\n'
    '            return "entry", entry\n',
    '            owning_entry = self._entry_by_observation.get(observation)\n'
    '            if owning_entry is None:\n'
    '                raise ShadowStateError("selected exit lacks its current Case observation")\n'
    '            return "entry", owning_entry\n',
)

# Funnel maps only retain concrete active episode and Case identities.
funnel = "apps/radar_runtime/src/radar_runtime/funnel.py"
replace_once(
    funnel,
    '                if candidate is not None:\n'
    '                    if not state.candidate:\n'
    '                        state.candidate = True\n'
    '                        self._candidate_episode_count += 1\n'
    '                    self._candidate_episode_by_identity[candidate] = episode\n',
    '                if candidate is not None and episode is not None:\n'
    '                    if not state.candidate:\n'
    '                        state.candidate = True\n'
    '                        self._candidate_episode_count += 1\n'
    '                    self._candidate_episode_by_identity[candidate] = episode\n',
)
replace_once(
    funnel,
    '                if entry is not None:\n'
    '                    if not state.case_opened:\n'
    '                        state.case_opened = True\n'
    '                        self._case_opened_count += 1\n'
    '                    state.entry_identity = entry\n'
    '                    self._entry_episode_by_identity[entry] = episode\n',
    '                if entry is not None and episode is not None:\n'
    '                    if not state.case_opened:\n'
    '                        state.case_opened = True\n'
    '                        self._case_opened_count += 1\n'
    '                    state.entry_identity = entry\n'
    '                    self._entry_episode_by_identity[entry] = episode\n',
)
replace_once(
    funnel,
    '                outcome_episode = self._entry_episode_by_identity.pop(entry or "", None)\n',
    '                if entry is None:\n'
    '                    outcome_episode = None\n'
    '                else:\n'
    '                    outcome_episode = self._entry_episode_by_identity.pop(entry, None)\n',
)
replace_once(
    funnel,
    '                if outcome_state is not None and not outcome_state.outcome:\n'
    '                    outcome_state.outcome = True\n'
    '                    self._outcome_count += 1\n'
    '                    self._episodes.pop(outcome_episode, None)\n',
    '                if (\n'
    '                    outcome_episode is not None\n'
    '                    and outcome_state is not None\n'
    '                    and not outcome_state.outcome\n'
    '                ):\n'
    '                    outcome_state.outcome = True\n'
    '                    self._outcome_count += 1\n'
    '                    self._episodes.pop(outcome_episode, None)\n',
)
replace_once(
    funnel,
    '            if state.entry_identity is not None:\n'
    '                self._entry_episode_by_identity.pop(state.entry_identity, None)\n',
    '            entry_identity = state.entry_identity\n'
    '            if entry_identity is not None:\n'
    '                self._entry_episode_by_identity.pop(entry_identity, None)\n',
)

# Workbench expiry aggregation accepts only actual integer expiry values.
workbench = "apps/radar_runtime/src/radar_runtime/workbench.py"
replace_once(
    workbench,
    '        if expiry_ms is None and isinstance(leg_ids, list):\n'
    '            expiries = {\n'
    '                expiry_by_leg.get(str(identity))\n'
    '                for identity in leg_ids\n'
    '                if expiry_by_leg.get(str(identity)) is not None\n'
    '            }\n'
    '            if len(expiries) == 1:\n'
    '                expiry_ms = next(iter(expiries))\n',
    '        if expiry_ms is None and isinstance(leg_ids, list):\n'
    '            expiries: set[int] = set()\n'
    '            for identity in leg_ids:\n'
    '                leg_expiry = expiry_by_leg.get(str(identity))\n'
    '                if isinstance(leg_expiry, int):\n'
    '                    expiries.add(leg_expiry)\n'
    '            if len(expiries) == 1:\n'
    '                expiry_ms = next(iter(expiries))\n',
)

# Express empty immutable views without a non-overlapping tuple equality.
fact_test = Path("tests/test_fact_boundary_business.py")
text = fact_test.read_text(encoding="utf-8")
old_assertion = "    assert reducer.event_sink.anomalies == ()\n"
if text.count(old_assertion) != 3:
    raise SystemExit(f"unexpected anomaly assertion count: {text.count(old_assertion)}")
fact_test.write_text(text.replace(old_assertion, "    assert not reducer.event_sink.anomalies\n"), encoding="utf-8")

# Let the repository-pinned Ruff own import order, unused-local deletion, and formatting.
run(
    ".venv/bin/python",
    "-m",
    "ruff",
    "check",
    "--fix",
    "--unsafe-fixes",
    "apps/radar_runtime/src/radar_runtime/workbench.py",
    "packages/short_vol_underwriting/src/short_vol_underwriting/owner.py",
    "tests/test_short_vol_underwriting.py",
)
changed_files = (
    "apps/radar_runtime/src/radar_runtime/fixed_contract_shadow.py",
    "apps/radar_runtime/src/radar_runtime/funnel.py",
    "apps/radar_runtime/src/radar_runtime/workbench.py",
    "packages/short_vol_underwriting/src/short_vol_underwriting/evidence.py",
    "packages/short_vol_underwriting/src/short_vol_underwriting/owner.py",
    "tests/test_fact_boundary_business.py",
    "tests/test_fixed_contract_shadow.py",
    "tests/test_short_vol_underwriting.py",
)
run(".venv/bin/python", "-m", "ruff", "format", *changed_files)
run("git", "add", *changed_files)

# Remove every transport helper from the final tree. The patch already deletes export-sandbox-source.yml.
run(
    "git",
    "rm",
    ".github/cleanup.patch.part00",
    ".github/cleanup.patch.part02",
    ".github/workflows/apply-bounded-cleanup.yml",
    ".github/finalize_cleanup.py",
    ".github/workflows/finalize-cleanup.yml",
)
run("git", "rm", "-f", ".github/cleanup.patch.part01")
if Path(".github/workflows/export-sandbox-source.yml").exists():
    raise SystemExit("export workflow survived cleanup patch")
