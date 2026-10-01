"use strict";
// Model ledger amounts only; these fixtures are never served as account data.
const test = require("node:test");
const assert = require("node:assert/strict");
const {trustedFeeSeries, chartDomain} = require("../static/research.js");
const comparison = {
  status: "computed_from_verified_ledger", run_id: "run-A",
  gross_pnl_btc: "0.00006482659608703263", base_net_btc: "0.00002482659608703263",
  higher_net_btc: "-0.00013517340391296737", base_fee_bp: "1", higher_fee_bp: "5"
};
function records() {
  return {
    evidence: {run_id: "run-A", fee_comparison: structuredClone(comparison)},
    metric: {run_id: "run-A", accounting: {model_ledger_verified: true}, fee_comparison: structuredClone(comparison)}
  };
}

test("fee graph preserves one run's exact fields, units and negative result", () => {
  const {evidence, metric} = records();
  const series = trustedFeeSeries(evidence, metric);
  assert.equal(series.length, 3);
  assert.equal(series[0].value, comparison.gross_pnl_btc);
  assert.equal(series[2].field, "fee_comparison.higher_net_btc");
  assert.equal(series[2].unit, "BTC");
  assert.equal(series[2].value, comparison.higher_net_btc);
  const domain = chartDomain(series);
  assert(domain.min < 0 && domain.max > 0);
});

test("graph rejects another run or amounts that disagree with the cited evidence", () => {
  for (const mutate of [
    ({metric}) => { metric.run_id = "run-B"; },
    ({metric}) => { metric.fee_comparison.run_id = "run-B"; },
    ({metric}) => { metric.fee_comparison.higher_net_btc = "0.00118729384728868433"; },
    ({metric}) => { metric.accounting.model_ledger_verified = false; },
    ({evidence}) => { delete evidence.fee_comparison; }
  ]) {
    const pair = records(); mutate(pair);
    assert.equal(trustedFeeSeries(pair.evidence, pair.metric), null);
  }
});

test("missing or invalid graph amounts do not become zero", () => {
  for (const invalid of [null, undefined, "", " ", "NaN", "Infinity", "1e999", false]) {
    const {evidence, metric} = records();
    evidence.fee_comparison.base_net_btc = invalid;
    metric.fee_comparison.base_net_btc = invalid;
    assert.equal(trustedFeeSeries(evidence, metric), null);
  }
  assert.equal(chartDomain([{value: null}]), null);
});

test("zero and scientific notation remain valid, and domains include zero", () => {
  const {evidence, metric} = records();
  for (const row of [evidence.fee_comparison, metric.fee_comparison]) {
    row.gross_pnl_btc = "1.2e-7"; row.base_net_btc = "0"; row.higher_net_btc = "-2e-7";
  }
  assert.equal(trustedFeeSeries(evidence, metric)[1].value, "0");
  assert.deepEqual(chartDomain([{value: "-2e-7"}, {value: "-1e-7"}]), {min: -2e-7, max: 0});
  assert.deepEqual(chartDomain([{value: "0"}, {value: "0"}]), {min: 0, max: 1});
});
