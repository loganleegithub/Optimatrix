from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from market_tape import CanonicalEvent, EventKind
from market_tape.segmented import (
    PublicShadowJournalReader,
    PublicShadowJournalWriter,
)


def _event(capture_seq: int, elapsed_ms: int) -> CanonicalEvent:
    return CanonicalEvent(
        capture_seq=capture_seq,
        collector_received_at_ms=1_800_000_000_000 + elapsed_ms,
        collector_elapsed_ms=elapsed_ms,
        exchange_timestamp_ms=1_800_000_000_000 + elapsed_ms,
        channel="ticker.BTC_USDC-PERPETUAL.agg2",
        event_kind=EventKind.TICKER,
        instrument_name="BTC_USDC-PERPETUAL",
        raw_payload=json.dumps(
            {
                "timestamp": 1_800_000_000_000 + elapsed_ms,
                "state": "open",
                "index_price": "100000",
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
    )


def _contract() -> dict[str, object]:
    return {
        "contract_id": "FIXED_POLICY_PUBLIC_SHADOW_RUN",
        "run_id": "synthetic-run",
        "segment_duration_ms": 300_000,
        "run_runtime_source_digest": "a" * 64,
    }


def test_segmented_writer_cross_binds_facts_opportunities_and_empty_windows(
    tmp_path: Path,
) -> None:
    elapsed_ms = 0

    def clock() -> int:
        return elapsed_ms

    writer = PublicShadowJournalWriter(
        tmp_path / "run",
        run_contract=_contract(),
        elapsed_ms=clock,
    )
    writer.commit_network_open_intent(
        network_attempt_ordinal=1,
        purpose="INITIAL_SETUP",
        pending_connection_generation=1,
        due_elapsed_ms=0,
        actual_elapsed_ms=0,
        timeout_ms=10_000,
    )
    writer.commit_network_connect_result(
        network_attempt_ordinal=1,
        purpose="INITIAL_SETUP",
        pending_connection_generation=1,
        actual_elapsed_ms=10,
        result="CONNECTED",
        error=None,
    )
    elapsed_ms = 50
    writer.append_fact(_event(1, 50))
    elapsed_ms = 60
    writer.append_opportunity(
        {
            "receipt_type": "SHORT_VOL_PUBLIC_SHADOW_OPPORTUNITY_RECORD",
            "slot_index": 0,
            "cutoff_capture_seq": 1,
            "admission_class": "NO_ENTRY",
        }
    )
    elapsed_ms = 650_000
    writer.advance_segments_before(650_000)
    writer.append_fact(_event(2, 650_000))
    writer.seal(900_000, complete=True, incomplete_reasons=())

    verified = PublicShadowJournalReader(tmp_path / "run").verify()
    assert verified.complete is True
    assert verified.events == (_event(1, 50), _event(2, 650_000))
    assert [item.record_count for item in verified.segments] == [1, 0, 1]
    assert verified.opportunity_count == 1
    assert verified.prefix_causality_verified is True
    assert verified.online_persistence_external_attested is False


@pytest.mark.parametrize(
    "mutation",
    (
        "truncate_segment",
        "delete_empty_segment",
        "reorder_commits",
        "orphan_tail",
        "replace_run_id",
    ),
)
def test_segment_chain_tamper_and_orphan_tail_fail_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    root = tmp_path / mutation
    writer = PublicShadowJournalWriter(root, run_contract=_contract(), elapsed_ms=lambda: 0)
    writer.append_fact(_event(1, 0))
    writer.advance_segments_before(600_000)
    writer.seal(600_000, complete=True, incomplete_reasons=())

    if mutation == "truncate_segment":
        path = root / "segments" / "segment-00000.jsonl"
        path.write_bytes(path.read_bytes()[:-1])
    elif mutation == "delete_empty_segment":
        (root / "segments" / "segment-00001.manifest.json").unlink()
    elif mutation == "reorder_commits":
        path = root / "causal-commits.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[-2], lines[-1] = lines[-1], lines[-2]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    elif mutation == "orphan_tail":
        with (root / "segments" / "segment-00000.jsonl").open("ab") as handle:
            handle.write(b"{}\n")
    else:
        path = root / "RUN_CONTRACT.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["run_id"] = "replacement"
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError):
        PublicShadowJournalReader(root).verify()


def test_payload_without_commit_is_a_verifiable_incomplete_prefix(tmp_path: Path) -> None:
    root = tmp_path / "interrupted"
    writer = PublicShadowJournalWriter(root, run_contract=_contract(), elapsed_ms=lambda: 0)
    writer.append_fact(_event(1, 0))
    writer.write_uncommitted_fact_for_test(_event(2, 1))
    writer.interrupt(("INJECTED_AFTER_PAYLOAD_BEFORE_COMMIT",))

    verified = PublicShadowJournalReader(root).verify(allow_incomplete=True)
    assert verified.complete is False
    assert verified.events == (_event(1, 0),)
    assert verified.orphan_tail is True
    assert "ORPHAN_FACT_TAIL" in verified.incomplete_reasons


def test_fact_chain_rejects_noncontiguous_sequence_and_elapsed_regression(
    tmp_path: Path,
) -> None:
    writer = PublicShadowJournalWriter(
        tmp_path / "sequence",
        run_contract=_contract(),
        elapsed_ms=lambda: 0,
    )
    writer.append_fact(_event(1, 10))
    with pytest.raises(ValueError, match="contiguous"):
        writer.append_fact(_event(3, 11))
    with pytest.raises(ValueError, match="nondecreasing"):
        writer.append_fact(replace(_event(2, 9), capture_seq=2))


def test_network_calls_require_exact_intent_result_pairs_in_one_pending_generation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "network"
    clock = [0]
    writer = PublicShadowJournalWriter(
        root,
        run_contract=_contract(),
        elapsed_ms=lambda: clock[0],
    )
    writer.commit_network_open_intent(
        network_attempt_ordinal=1,
        purpose="INITIAL_SETUP",
        pending_connection_generation=1,
        due_elapsed_ms=0,
        actual_elapsed_ms=0,
        timeout_ms=10_000,
    )
    writer.commit_network_connect_result(
        network_attempt_ordinal=1,
        purpose="INITIAL_SETUP",
        pending_connection_generation=1,
        actual_elapsed_ms=10,
        result="FAILED",
        error="TimeoutError",
    )
    clock[0] = 1_010
    writer.commit_network_open_intent(
        network_attempt_ordinal=2,
        purpose="INITIAL_SETUP",
        pending_connection_generation=1,
        due_elapsed_ms=1_010,
        actual_elapsed_ms=1_010,
        timeout_ms=10_000,
    )
    writer.commit_network_connect_result(
        network_attempt_ordinal=2,
        purpose="INITIAL_SETUP",
        pending_connection_generation=1,
        actual_elapsed_ms=1_020,
        result="CONNECTED",
        error=None,
    )
    clock[0] = 1_021
    writer.append_fact(_event(1, 1_021))
    writer.seal(300_000, complete=True, incomplete_reasons=())
    assert PublicShadowJournalReader(root).verify().complete is True

    unresolved = tmp_path / "unresolved"
    writer = PublicShadowJournalWriter(
        unresolved,
        run_contract=_contract(),
        elapsed_ms=lambda: 0,
    )
    writer.commit_network_open_intent(
        network_attempt_ordinal=1,
        purpose="INITIAL_SETUP",
        pending_connection_generation=1,
        due_elapsed_ms=0,
        actual_elapsed_ms=0,
        timeout_ms=10_000,
    )
    with pytest.raises(ValueError, match="network call"):
        writer.seal(300_000, complete=True, incomplete_reasons=())
