"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const {capabilities, trendRuleValues, runFreshness} = require("../static/strategies.js");

test("engineering successor is displayed before stopped history without rewriting records",()=>{
  const {orderedRuns}=require("../static/strategies.js");
  const old={run_id:"old",status:"stopped",created_at:"2026-10-04T18:12:00Z"};
  const current={run_id:"new",status:"running",created_at:"2026-10-04T18:42:00Z"};
  const original=[old,current];
  assert.deepEqual(orderedRuns(original).map(r=>r.run_id),["new","old"]);
  assert.deepEqual(original,[old,current]);
});

test("testnet implementation never implies Greeks capability", () => {
  assert.deepEqual(capabilities({implementation_status:"implemented",can_run_testnet:true}), {greeks:false,testnet:true});
  assert.deepEqual(capabilities({can_validate:true,can_run_testnet:false}), {greeks:true,testnet:false});
  assert.deepEqual(capabilities({can_validate:"true",can_run_testnet:"true"}), {greeks:false,testnet:false});
});
test("trend revisions preserve every rule and decimal string without six-parameter coercion", () => {
  const rules={signal_instrument:"BTC-PERPETUAL",fast_days:20,slow_days:60,equity_fraction:"0.0100000000000000001",source_max_age_seconds:30};
  const updated=trendRuleValues(rules,{signal_instrument:"BTC-PERPETUAL",fast_days:"21",slow_days:"60",equity_fraction:"0.0099999999999999999",source_max_age_seconds:"29"});
  assert.deepEqual(updated,{signal_instrument:"BTC-PERPETUAL",fast_days:21,slow_days:60,equity_fraction:"0.0099999999999999999",source_max_age_seconds:29});
  assert.equal(rules.fast_days,20);
  assert.throws(()=>trendRuleValues(rules,{fast_days:""}));
});
test("missing and cached run records never look like current execution", () => {
  const now=Date.parse("2026-10-05T08:00:00Z");
  assert.equal(runFreshness({status:"running"},false,now),"尚未取得逐轮记录");
  assert.equal(runFreshness({last_cycle:{at:"2026-10-05T07:59:50Z"}},true,now),"连接未确认 · 保留上次状态");
  assert.equal(runFreshness({last_cycle:{at:"2026-10-05T07:58:00Z"}},false,now),"轮次已过时 · 当前运行状态未确认");
  assert.equal(runFreshness({last_cycle:{at:"2026-10-05T07:59:50Z"}},false,now),"最近轮次已取得");
});

test("notification availability never treats absent permission as delivery", () => {
  const {notificationAvailability} = require("../static/strategies.js");
  assert.match(notificationAvailability(false, null), /不支持/);
  assert.match(notificationAvailability(true, "default"), /尚未授权/);
  assert.match(notificationAvailability(true, "denied"), /未送达/);
  assert.match(notificationAvailability(true, "granted"), /不等于你已读/);
});

test("testnet ledger preserves BTC precision and distinguishes no trades from missing evidence", () => {
  const {ledgerView} = require("../static/strategies.js");
  assert.equal(ledgerView(null).state,"unavailable");
  assert.equal(ledgerView({currency:"BTC",evidence_type:"testnet_execution",trade_count:0,trade_ids:[]}).state,"no_trades");
  const ledger={currency:"BTC",evidence_type:"testnet_execution",trade_count:2,trade_ids:["1","2"],actual_fees_btc:"0.000000000000000123",realized_pnl_btc:"-0.000045600000000000001",open_premium_cost_btc:"0",open_entry_fees_btc:"0",cash_flow_btc:"-0.000045600000000000001"};
  const view=ledgerView(ledger);
  assert.equal(view.state,"available");
  assert.equal(view.rows[0][1],ledger.actual_fees_btc);
  assert.equal(view.rows[1][1],ledger.realized_pnl_btc);
  assert.equal(ledgerView({...ledger,actual_fees_btc:null}).state,"incomplete");
  assert.equal(ledgerView({...ledger,realized_pnl_btc:""}).rows[1][1],"未知");
  assert.equal(ledgerView({...ledger,currency:"USD"}).state,"unavailable");
  assert.equal(ledgerView({...ledger,evidence_type:"greeks_model"}).state,"unavailable");
  assert.equal(ledgerView({...ledger,trade_ids:[]}).state,"unavailable");
});

test("runtime signal summary shows units and explicit unknowns without changing raw evidence", () => {
  const {signalPriceRows} = require("../static/strategies.js");
  const cycle={signal:{bar_date:"2026-10-04",fast:"100000.123456789",slow:"99000.987654321",crossover:false},prices:{signal_index_usd:101000.25,testnet_bid_btc:null,testnet_ask_btc:"0.012345"}};
  const before=JSON.stringify(cycle),rows=signalPriceRows(cycle,{fast_days:20,slow_days:60});
  assert.equal(rows[1][0],"SMA20（短均线）");
  assert.equal(rows[2][0],"SMA60（长均线）");
  assert.equal(rows[3][1],"否");
  assert.match(rows[4][1],/USD$/);
  assert.equal(rows[5][1],"本轮未取得 / 0.012345 BTC");
  assert.equal(signalPriceRows({})[3][1],"未知");
  assert.equal(JSON.stringify(cycle),before);
});
