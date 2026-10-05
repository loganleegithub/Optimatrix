(function () {
  "use strict";
  function observerState(data, error, now=Date.now(), elapsed=0) {
    if(error)return {kind:"error",label:"读取失败 · 保留旧记录",reason:error};
    if(!data)return {kind:"neutral",label:"尚未取得",reason:"尚未取得公共观察数据。"};
    if(data.authority!=="public_observation_only")return {kind:"error",label:"权限口径未确认",reason:"响应没有确认只读公共观察身份；不将其显示为有效信号。"};
    if(data.error||["blocked","error","failed","unavailable"].includes(data.status))return {kind:"error",label:"观察受阻 · 保留旧记录",reason:typeof data.error==="string"?data.error:"公共数据或计算校验失败；已有记录只供核对。"};
    if(!["ready","observing","live","ok","current"].includes(data.status))return {kind:"neutral",label:"观察状态未确认",reason:"服务尚未确认有效数据；等待下一次公共行情检查。"};
    const observed=Date.parse(data.observed_at||""),success=Date.parse(data.last_success_at||""),next=Date.parse(data.next_check_at||"");
    if(!Number.isFinite(observed)||!Number.isFinite(success)||!Number.isFinite(next))return {kind:"warning",label:"时效未知",reason:"观察时间、成功时间或下次检查时间缺失。"};
    if(observed-now>5000||success-now>5000)return {kind:"warning",label:"时间异常",reason:"服务记录时间晚于当前时间，暂不确认时效。"};
    if(elapsed>60000||now>next+120000||now-success>180000)return {kind:"warning",label:"数据过时 · 保留旧记录",reason:"公共观察未在约定检查周期内更新，以下信号不能当作当前状态。"};
    return {kind:"live",label:"公共观察已更新",reason:"已取得最新检查记录；条件成立仅用于研究观察。"};
  }
  function barState(latest, now=Date.now()) {
    if(!latest)return {valid:false,label:"尚未取得完整 K 线"};
    const start=Date.parse(latest.bar_time||""),end=Date.parse(latest.bar_end_time||"");
    if(!Number.isFinite(start)||!Number.isFinite(end))return {valid:false,label:"K 线起止时间待核对"};
    if(end-start!==14400000||start%14400000!==0)return {valid:false,label:"K 线未对齐固定 UTC 4 小时边界"};
    if(end>now)return {valid:false,label:"尚未收盘，禁止作为观察信号"};
    if(now-end>14400000+180000)return {valid:false,label:"最新完整 K 线已落后，保留旧信号"};
    return {valid:true,label:"已完成的 4 小时 K 线"};
  }
  function numeric(value){return (typeof value==="string"||typeof value==="number")&&String(value).trim()!==""&&Number.isFinite(Number(value));}
  function percent(value){return numeric(value)?`${(Number(value)*100).toFixed(2)}%`:"未知";}
  function condition(value){return value===true?"成立":value===false?"未成立":"未知";}
  function assessmentRows(assessment){
    if(!assessment||assessment.status!=="not_supported")return null;
    return [["未计成本的标的回报",percent(assessment.initial_gross_return)],
      ["每边 10 bp 成本下",percent(assessment.initial_cost_10bps_return)]];
  }
  function replayState(replay){
    if(!replay||replay.evidence_type!=="underlying_price_diagnostic")return {valid:false,label:"尚未取得可核对的标的价格诊断"};
    if(!Number.isInteger(replay.closed_trades)||replay.closed_trades<0)return {valid:false,label:"回放交易段计数未知"};
    return {valid:true,label:replay.closed_trades===0?"尚无已闭合假设交易":"标的价格诊断 · 非真实成交"};
  }
  if(typeof module!=="undefined"&&module.exports){module.exports={observerState,barState,replayState,percent,condition,assessmentRows};return;}
  const $=id=>document.getElementById(id),state={data:null,error:null,receivedPerf:null,fetching:false};
  function node(tag,text,cls){const el=document.createElement(tag);if(text!==undefined)el.textContent=String(text);if(cls)el.className=cls;return el;}
  function text(value,fallback="未知"){if(value===undefined||value===null||value==="")return fallback;if(typeof value==="boolean")return value?"是":"否";return typeof value==="object"?JSON.stringify(value):String(value);}
  function time(value){const stamp=Date.parse(value||"");return Number.isFinite(stamp)?new Date(stamp).toISOString().replace("T"," ").replace(/\.\d{3}Z$/," UTC"):"时间未取得";}
  function paragraph(value,cls=""){return node("p",value,cls);}
  function facts(rows,cls="facts"){const dl=node("dl",undefined,cls);for(const [name,value] of rows){const row=node("div");row.append(node("dt",name),node("dd",text(value)));dl.append(row);}return dl;}
  function badge(label,kind="neutral"){return node("span",label,`badge badge-${kind}`);}
  function list(values){const ul=node("ul",undefined,"plain-list");for(const value of Array.isArray(values)?values:[])ul.append(node("li",text(value)));return ul;}
  function details(label,value,key){const box=node("details");box.dataset.stateKey=key;box.append(node("summary",label),node("pre",JSON.stringify(value,null,2)));return box;}
  function safeLink(label,url){if(typeof url!=="string"||!/^https?:\/\//i.test(url))return null;try{const parsed=new URL(url);if(!["http:","https:"].includes(parsed.protocol))return null;}catch(_){return null;}const a=node("a",label);a.href=url;a.target="_blank";a.rel="noopener noreferrer";return a;}
  function sources(input){const box=node("div",undefined,"source-links"),rows=Array.isArray(input)?input:input?[input]:[];for(const row of rows){const url=typeof row==="string"?row:row?.url,label=typeof row==="string"?row:row?.title||row?.label||row?.name||url,a=safeLink(label,url);if(a){box.append(a);if(row?.status||row?.content_status)box.append(paragraph(`来源状态：${text(row.content_status||row.status)}`,"fineprint"));}}return box;}
  function preserved(id,nodes){const host=$(id),opened=new Set([...host.querySelectorAll("details[data-state-key]")].filter(el=>el.open).map(el=>el.dataset.stateKey));host.replaceChildren(...nodes);for(const el of host.querySelectorAll("details[data-state-key]"))if(opened.has(el.dataset.stateKey))el.open=true;}
  const directionNames={up:"向上",bullish:"向上",bull:"向上",long:"向上",down:"向下",bearish:"向下",bear:"向下",short:"向下",neutral:"中性",flat:"中性",1:"向上","-1":"向下",0:"中性"};
  const indicatorNames={ready:"计算样本足够",line:"趋势参考线",direction:"趋势方向",basis:"20 根均价",squeeze:"波动区间状态",previous_momentum:"上一根动量",entry_event:"入场观察事件",exit_event:"退出观察事件",event:"本根条件变化",atr:"平均波幅 ATR",atr10:"10 根平均波幅",supertrend:"Supertrend 参考线",trend:"趋势状态",upper_band:"上边界",lower_band:"下边界",final_upper:"最终上边界",final_lower:"最终下边界",momentum:"动量",momentum_previous:"上一根动量",squeeze_on:"处于收缩",squeeze_off:"已释放收缩",no_squeeze:"无收缩状态",bb_upper:"布林带上沿",bb_lower:"布林带下沿",kc_upper:"Keltner 上沿",kc_lower:"Keltner 下沿",slope:"动量变化",signal:"条件状态"};
  function indicatorValue(name,value){
    if(value===null||value===undefined)return "未知";
    if(name==="direction")return directionNames[value]||text(value);
    if(name==="squeeze")return {on:"收缩",off:"释放",neutral:"中间状态"}[value]||text(value);
    if(name==="event")return {entry:"入场条件",exit:"退出条件",none:"无新条件"}[value]||text(value);
    return numeric(value)?Number(value).toLocaleString("zh-CN",{maximumFractionDigits:4}):text(value);
  }
  function diagnostic(replay,key){
    const result=replayState(replay),box=node("details");box.dataset.stateKey=`replay-${key}`;box.append(node("summary","历史价格回放诊断 · 不是期权收益"));
    if(!result.valid){box.append(paragraph(result.label,"muted"));return box;}
    box.append(paragraph(result.label),facts([["历史区间",`${time(replay.start_at)} — ${time(replay.end_at)}`],["已闭合假设交易",replay.closed_trades],["假设交易胜率",replay.closed_trades?percent(replay.win_rate):"无已闭合交易，不计算"],["未计成本的标的复利回报",replay.closed_trades?percent(replay.gross_compound_return):"无已闭合交易，不计算"]]));
    if(Array.isArray(replay.cost_scenarios)&&replay.cost_scenarios.length){const table=node("table",undefined,"replay-table"),head=node("thead"),tr=node("tr");tr.append(node("th","每边假设成本"),node("th","标的复利回报"));head.append(tr);table.append(head);const body=node("tbody");for(const scenario of replay.cost_scenarios){const row=node("tr");row.append(node("td",numeric(scenario.per_side_bps)?`${scenario.per_side_bps} bp`:"未知"),node("td",replay.closed_trades?percent(scenario.compound_return):"无已闭合交易"));body.append(row);}table.append(body);box.append(table);}
    if(replay.open_position)box.append(paragraph("历史区间结束时仍有未闭合的假设仓位；未当作已完成交易。","warning-copy"));
    box.append(paragraph("这里回放的是标的价格规则，使用历史已看过区间。成本是情景假设；没有期权选择、权利金、盘口容量或真实成交，不能作为主网或测试网盈亏。","fineprint"),list(replay.limitations),details("查看本次诊断完整字段",replay,`replay-raw-${key}`));return box;
  }
  function assessmentPanel(assessment){
    const rows=assessmentRows(assessment);if(!rows)return null;const box=node("section",undefined,"assessment-banner");box.append(node("h4","固定 4h 参数：初步价格筛选未通过"),paragraph(text(assessment.summary,"不接入测试网下单；仅保留固定参数的公共观察基线。")));
    const count=Number.isInteger(assessment.initial_closed_trades)&&assessment.initial_closed_trades>=0?String(assessment.initial_closed_trades):"数量未知的";
    box.append(paragraph(`首次诊断中 ${count} 笔已闭合假设标的价格交易；不含未平仓部分。`,"assessment-basis"),facts(rows,"assessment-metrics"),paragraph("以上不是期权盈亏或真实成交收益。结论只针对这组固定 4h 参数和首次诊断区间，不代表其他参数或全部变体。","fineprint"),paragraph(`初次评估：${time(assessment.assessed_at)}`,"fineprint"));return box;
  }
  function candidateCard(candidate,index,status){
    const key=text(candidate.key,String(index)),latest=candidate.latest,bar=barState(latest),card=node("article",undefined,"signal-card panel"),top=node("div",undefined,"signal-topline");
    top.append(node("h3",text(candidate.name,"候选名称未取得")),badge(status.kind==="live"&&bar.valid?"只读观察":bar.label,status.kind==="live"&&bar.valid?"neutral":"warning"));card.append(top,paragraph(text(candidate.rule_summary,"冻结规则说明尚未取得。"),"rule-summary"));const assessment=assessmentPanel(candidate.assessment);if(assessment)card.append(assessment);
    if(candidate.strategy_id&&candidate.version_id){const a=node("a","查看已保存的策略与版本 →","version-link");a.href=`/strategies?strategy_id=${encodeURIComponent(candidate.strategy_id)}&version_id=${encodeURIComponent(candidate.version_id)}`;card.append(a);}else card.append(paragraph("策略 / 版本关联未取得。","warning-copy"));
    const usable=status.kind==="live"&&bar.valid&&!candidate.error&&latest?.ready!==false&&latest?.indicators?.ready!==false;
    card.append(node("div",latest?`方向：${directionNames[latest.direction]||text(latest.direction)}`:"尚无完整 K 线信号","signal-state"));
    if(!usable)card.append(paragraph("以下保留最近取得的计算记录；当前有效性未确认。","warning-copy"));if(candidate.error)card.append(paragraph(text(candidate.error),"error-copy"));
    card.append(facts([["K 线开始",time(latest?.bar_time)],["K 线收盘",time(latest?.bar_end_time)],["收盘价",numeric(latest?.close)?`${Number(latest.close).toLocaleString("zh-CN",{minimumFractionDigits:2,maximumFractionDigits:2})} USD`:"未知"],["入场观察条件",condition(latest?.entry)],["退出观察条件",condition(latest?.exit)]]));
    card.append(paragraph(usable&&latest?.fresh_event===true?`新完成 K 线的观察事件 · ${time(latest.signal_at)}；仅记录，不下单。`:"当前为状态展示；没有已确认的新观察事件，不补发历史条件。","event-note"));
    if(latest?.indicators&&typeof latest.indicators==="object"){const values=node("div",undefined,"indicator-values");values.append(facts(Object.entries(latest.indicators).filter(([,value])=>value===null||typeof value!=="object").map(([name,value])=>[indicatorNames[name]||name,indicatorValue(name,value)])));values.append(paragraph("指标最多显示 4 位小数；完整精度保留在下方信号记录中。","fineprint"));card.append(values);}
    if(Array.isArray(candidate.limitations)&&candidate.limitations.length)card.append(list(candidate.limitations));
    card.append(paragraph("固定 4h 条件观察；没有账户、订单或期权收益。","boundary-note"),diagnostic(candidate.replay,key),sources(candidate.sources||candidate.source_urls));
    card.append(details("核对冻结身份及完整信号字段",{strategy_id:candidate.strategy_id,version_id:candidate.version_id,rules_sha256:candidate.rules_sha256,latest:candidate.latest,source:candidate.source,sources:candidate.sources},`candidate-${key}`));return card;
  }
  function render(){
    const status=observerState(state.data,state.error,Date.now(),state.receivedPerf===null?Infinity:performance.now()-state.receivedPerf),data=state.data||{};
    $("study-status").textContent=status.label;$("study-status").className=`badge badge-${status.kind}`;$("connection-notice").textContent=status.reason;$("connection-notice").className="connection-notice"+(status.kind==="error"?" is-error":status.kind==="warning"?" is-warning":"");
    $("study-times").replaceChildren(...facts([["公开数据源",data.source||"来源尚未取得"],["最近检查",time(data.observed_at)],["最近成功取得",time(data.last_success_at)],["下次后台检查",time(data.next_check_at)]],"context-facts").children);
    const candidates=Array.isArray(data.candidates)?data.candidates:[];preserved("candidate-list",candidates.length?[...(candidates.length!==2?[paragraph("候选数量与本轮两套规则不符，需核对服务记录。","candidate-notice")]:[]),...candidates.slice(0,2).map((c,i)=>candidateCard(c,i,status))]:[paragraph(state.error?"本次读取失败，尚无可展示的已保存候选。":"尚未取得两套候选的公共观察结果。","empty-state study-empty")]);
    const catalog=Array.isArray(data.catalog)?data.catalog:[];$("catalog-count").textContent=catalog.length?`${catalog.length} / 12 项已取得`:"目录待取得";
    const rows=catalog.map(item=>{const row=node("tr"),name=node("td",text(item.name));const a=safeLink("核对来源 ↗",item.url||item.source_url);if(a){a.className="source-link";name.append(a);}row.append(name,node("td",text(item.plain_meaning)),node("td",text(item.loss_case)),node("td",text(item.verdict)));return row;});
    if(!rows.length){const row=node("tr"),cell=node("td","指标目录尚未取得；不填入占位结果。","empty-state");cell.colSpan=4;row.append(cell);rows.push(row);}$("catalog-rows").replaceChildren(...rows);
    const sourceBox=sources(data.sources||data.source_urls);$("study-sources").replaceChildren(sourceBox.childNodes.length?sourceBox:paragraph("来源记录尚未取得。","fineprint"));$("raw-study-content").textContent=state.data?JSON.stringify(state.data,null,2):"尚未取得";
  }
  async function poll(){
    if(state.fetching)return;state.fetching=true;const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),12000);
    try{const response=await fetch("/api/signal-studies",{cache:"no-store",signal:controller.signal}),data=await response.json();if(!response.ok)throw new Error(typeof data.error==="string"?data.error:`读取失败 (${response.status})`);if(!data||typeof data!=="object"||Array.isArray(data))throw new Error("公共观察响应格式无效");state.data=data;state.error=null;state.receivedPerf=performance.now();}
    catch(error){state.error=error.name==="AbortError"?"公共观察读取超时；未确认更新。":error.message||"公共观察读取失败。";}
    finally{clearTimeout(timer);state.fetching=false;render();}
  }
  render();poll();setInterval(poll,15000);setInterval(render,15000);
})();
