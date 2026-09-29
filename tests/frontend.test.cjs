"use strict";
// Offline checks of the status rules; no browser, account, or network required.
const test = require("node:test");
const assert = require("node:assert/strict");
const { age, health, dataState, catalogState, dateText, compactNumber } = require("../static/app.js");
const fresh = { status: "live", received_at: "2026-09-29T01:00:00Z", source_age_seconds: 4, receipt_age_seconds: 2 };

test("page starts unconfirmed; only a recent successful heartbeat is reachable", () => {
  assert.equal(health({ failure: null, heartbeatPerf: null }, 500).ok, false);
  assert.equal(health({ failure: null, heartbeatPerf: 500 }, 9999).ok, true);
  assert.equal(health({ failure: null, heartbeatPerf: 500 }, 10500).ok, false);
  assert.equal(health({ failure: null, heartbeatPerf: 500, verifying: true }, 1000).ok, false);
});
test("backend failure immediately invalidates a still-fresh retained quote", () => {
  const status = health({ failure: "Failed to fetch", heartbeatPerf: 500 }, 501);
  assert.equal(status.ok, false);
  assert.equal(status.text, "服务不可达");
  assert.equal(dataState(fresh, status.ok, 0, 60).kind, "error");
});
test("both source age and receipt age expire using elapsed monotonic time", () => {
  assert.equal(dataState(fresh, true, 55999, 60).kind, "live");
  assert.equal(dataState(fresh, true, 56000, 60).kind, "warning");
  assert.equal(dataState({ ...fresh, source_age_seconds: 0, receipt_age_seconds: 59 }, true, 1000, 60).kind, "warning");
  assert.equal(age(4, 5000), 9);
  assert.equal(age(null, 5000), null);
});
test("missing, error, expired and unknown data never render healthy", () => {
  assert.equal(dataState(null, true, 0, 60).text, "未取得数据");
  for (const status of ["missing", "stale", "error", "expired", "unexpected"]) {
    assert.notEqual(dataState({ ...fresh, status }, true, 0, 60).kind, "live");
  }
  assert.notEqual(dataState({ ...fresh, source_age_seconds: null }, true, 0, 60).kind, "live");
});
test("no price is formatted as zero, and timezone conversion is explicit", () => {
  assert.equal(compactNumber(null), "未取得数据");
  assert.equal(compactNumber(0), "0");
  assert.equal(compactNumber(0.0001), "0.0001");
  assert.equal(dateText("2026-09-29T08:00:00Z", "Asia/Taipei"), "2026-09-29 16:00:00");
});
test("collection failure also states that retained prices have become stale", () => {
  assert.equal(dataState({ ...fresh, status: "error" }, true, 0, 60).text, "采集失败 · 保留值");
  assert.equal(dataState({ ...fresh, status: "error" }, true, 56000, 60).text, "采集失败 · 数据过时");
});
test("catalog ages expire at 660 seconds even if collector status stays live", () => {
  const snapshot = { server_time: "2026-09-29T01:10:00Z", catalog: { count: 12, status: "live", source_at: "2026-09-29T01:00:00Z", received_at: "2026-09-29T01:00:01Z" } };
  assert.equal(catalogState(snapshot, true, 59000), "12 个 · 已取得");
  assert.equal(catalogState(snapshot, true, 60000), "12 个 · 列表过时 · 保留值");
  const failed = { ...snapshot, catalog: { ...snapshot.catalog, status: "error" } };
  assert.equal(catalogState(failed, true, 60000), "12 个 · 更新失败 · 列表过时");
  const receiptOld = { ...snapshot, catalog: { ...snapshot.catalog, source_age_seconds: 1, receipt_age_seconds: 660 } };
  assert.equal(catalogState(receiptOld, true, 0), "12 个 · 列表过时 · 保留值");
  assert.equal(catalogState(snapshot, false, 0), "12 个 · 连接未确认 · 保留值");
});
