"""Explicit one-shot public check. Never loaded by the running web service."""
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlencode

from market import BASE_URL, PublicClient, iso, select_instruments


def capture():
    client = PublicClient()
    entries = []

    def fetch(method, **params):
        envelope = client.get(method, **params)
        entry = {"url": BASE_URL + "public/" + method + "?" + urlencode(params),
                 "received_at_utc": envelope["received_at"], "response": envelope["payload"]}
        entries.append(entry)
        return envelope["payload"]["result"]

    started = iso()
    try:
        index = fetch("get_index_price", index_name="btc_usd")
        instruments = fetch("get_instruments", currency="BTC", kind="option", expired="false")
        chosen = select_instruments(instruments, index["index_price"], time.time())[:2]
        catalog_entry = entries[-1]
        canonical = json.dumps(catalog_entry["response"], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        catalog_entry["full_response_canonical_json_sha256"] = hashlib.sha256(canonical).hexdigest()
        catalog_entry["extraction_note"] = "get_instruments 的 result 仅保留本次展示的两条原始合约记录；其余响应字段原样保留。哈希对应缩减前、排序键且无空白的 UTF-8 JSON，不是 HTTP 原始字节。"
        catalog_entry["full_result_count"] = len(instruments)
        catalog_entry["response"] = {**catalog_entry["response"], "result": chosen}
        for instrument in chosen:
            fetch("get_order_book", instrument_name=instrument["instrument_name"], depth=1)
    finally:
        client.close()
    sample = {"purpose": "真实公共接口检查样本；只作审阅，程序不读取它，不替代实时行情。",
              "started_at_utc": started, "completed_at_utc": iso(), "credentials_used": False,
              "entries": entries}
    target = Path(__file__).resolve().parent / "docs" / "samples" / "deribit-public.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(sample, ensure_ascii=False, indent=2) + "\n")
    print(f"已保存真实公共样本：{target}")


if __name__ == "__main__":
    capture()
