"use strict";
const test=require("node:test"),assert=require("node:assert/strict");
const {observerState,barState,replayState,percent,condition}=require("../static/signals.js");
const now=Date.parse("2026-10-05T10:00:00Z");
const fresh={authority:"public_observation_only",status:"observing",observed_at:"2026-10-05T09:59:40Z",last_success_at:"2026-10-05T09:59:40Z",next_check_at:"2026-10-05T10:00:40Z"};

test("public observer shows failure before cached signals and requires explicit authority",()=>{
  assert.equal(observerState(null,null,now).kind,"neutral");
  assert.equal(observerState(fresh,null,now).kind,"live");
  assert.equal(observerState(fresh,"offline request failed",now).kind,"error");
  assert.equal(observerState({...fresh,status:"blocked",error:"missing bars"},null,now).kind,"error");
  assert.equal(observerState({...fresh,authority:"testnet_execution"},null,now).kind,"error");
});
test("fresh HTTP response does not freshen stale observer evidence",()=>{
  assert.equal(observerState({...fresh,last_success_at:"2026-10-05T09:56:59Z"},null,now).kind,"warning");
  assert.equal(observerState({...fresh,next_check_at:"2026-10-05T09:57:59Z"},null,now).kind,"warning");
  assert.equal(observerState(fresh,null,now,60001).kind,"warning");
  assert.equal(observerState({...fresh,last_success_at:null},null,now).kind,"warning");
  assert.equal(observerState({...fresh,observed_at:"2026-10-05T10:00:06Z"},null,now).kind,"warning");
});
test("only completed aligned current 4h bars can present a current observation",()=>{
  const bar={bar_time:"2026-10-05T04:00:00Z",bar_end_time:"2026-10-05T08:00:00Z"};
  assert.equal(barState(bar,now).valid,true);
  assert.equal(barState({...bar,bar_end_time:"2026-10-05T12:00:00Z"},now).valid,false);
  assert.equal(barState({bar_time:"2026-10-05T08:00:00Z",bar_end_time:"2026-10-05T12:00:00Z"},now).valid,false);
  assert.equal(barState({bar_time:"2026-10-05T03:00:00Z",bar_end_time:"2026-10-05T07:00:00Z"},now).valid,false);
  assert.equal(barState({bar_time:"2026-10-05T00:00:00Z",bar_end_time:"2026-10-05T04:00:00Z"},now).valid,false);
  assert.equal(barState({bar_time:bar.bar_time},now).valid,false);
});
test("missing conditions and replay evidence never become zero returns or false signals",()=>{
  assert.equal(condition(null),"未知");assert.equal(condition(false),"未成立");assert.equal(condition("true"),"未知");
  assert.equal(percent(null),"未知");assert.equal(percent(""),"未知");assert.equal(percent(0),"0.00%");
  assert.equal(replayState({evidence_type:"testnet_execution",closed_trades:2}).valid,false);
  assert.equal(replayState({evidence_type:"underlying_price_diagnostic",closed_trades:0}).label,"尚无已闭合假设交易");
  assert.equal(replayState({evidence_type:"underlying_price_diagnostic",closed_trades:null}).valid,false);
});

test("negative fixed-baseline assessment keeps both cost bases and never fills missing returns with zero",()=>{
  const {assessmentRows}=require("../static/signals.js");
  const rows=assessmentRows({status:"not_supported",initial_gross_return:-0.1938101555,initial_cost_10bps_return:-0.2377159653});
  assert.equal(rows[0][1],"-19.38%");assert.equal(rows[1][1],"-23.77%");
  assert.equal(assessmentRows({status:"not_supported",initial_gross_return:null})[0][1],"未知");
  assert.equal(assessmentRows(null),null);
  assert.equal(assessmentRows({status:"supported",initial_gross_return:0.2}),null);
});
