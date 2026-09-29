"""Explicit BTC cashflow arithmetic; never infer a ledger from a PnL label.

The calculator accepts already identified BTC cashflows. It is not an option
pricing model, a trade ledger, or a USD-to-BTC conversion shortcut. Service
reports remain separate until their raw cashflows and units can be verified.
"""

import csv
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path


MODEL_TOLERANCE = Decimal("1e-15")  # BTC; smaller than one satoshi by 10 million.


class LedgerGap(ValueError):
    """A known, safe explanation for withholding a model-ledger conclusion."""


def _require(condition, explanation):
    if not condition:
        raise LedgerGap(explanation)


def _number(row, field, nonnegative=False):
    value = _reported_number(row.get(field))
    _require(value is not None, f"缺少有效数值字段 {field}，无法核对模型账本。")
    value = Decimal(value)
    _require(not nonnegative or value >= 0, f"字段 {field} 不能为负数。")
    return value


def _match(left, right, description):
    _require(abs(left - right) <= MODEL_TOLERANCE, f"{description}不一致，无法可靠重建 BTC 净收益。")


def _utc(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        _require(stamp.utcoffset() == timedelta(0), "模型事件时间没有明确使用 UTC。")
        return stamp
    except (ValueError, TypeError) as error:
        raise LedgerGap("模型事件缺少有效 UTC 时间。") from error


def _csv_rows(path, description):
    _require(path is not None, f"未取得完整{description} CSV，不能完成模型账本核对。")
    try:
        _require(Path(path).stat().st_size <= 20_000_000, f"{description} CSV 超出本阶段处理范围。")
        with Path(path).open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            fields = reader.fieldnames or []
            _require(bool(fields) and len(set(fields)) == len(fields), f"{description} CSV 表头缺失或重复。")
            rows = []
            for row in reader:
                rows.append(row)
                _require(len(rows) <= 10000 and None not in row and None not in row.values(),
                         f"{description} CSV 出现过多记录、缺失或额外字段。")
    except (OSError, UnicodeError, csv.Error, TypeError) as error:
        raise LedgerGap(f"{description} CSV 无法完整读取。") from error
    _require(bool(rows), f"{description} CSV 没有完整记录。")
    return rows


def _verified_model_ledger(report, artifact_files):
    """Reconcile the observed v20 long-option surface ledger by lot and event.

    Marks contribute changes in model value, never cash receipts. Each value
    already contains quantity and is BTC at that event's own forward. Only
    completely closed, non-settlement ledgers receive a net cashflow result.
    """
    request, kpis = report.get("request"), report.get("kpis")
    _require(isinstance(request, dict) and isinstance(kpis, dict), "缺少原始请求或结果 KPI。")
    _require(all(request.get(key) == value for key, value in {
        "asset": "BTC", "numeraire": "BTC", "mode": "reopen", "hedge_mode": "none",
    }.items()), "本轮仅核对 BTC inverse、reopen、无对冲的买方模型任务。")
    legs = request.get("legs")
    _require(isinstance(legs, list) and len(legs) == 1 and isinstance(legs[0], dict), "本轮只支持一条买入期权腿。")
    leg = legs[0]
    _require(leg.get("side") == "long" and isinstance(leg.get("option_type"), str)
             and leg["option_type"] in {"call", "put"}, "本轮只支持买入 Call 或 Put。")
    quantity, delta, tenor = _number(leg, "quantity", True), _number(leg, "delta", True), _number(leg, "expiry", True)
    _require(quantity > 0 and 0 < delta < 1 and tenor > 0 and _number(leg, "close_dte") == 0,
             "请求数量、Delta、目标期限或 close_dte 不在买方核对范围。")
    rate = _number(request, "option_transaction_cost_bp", True)
    _require(_number(request, "hedge_transaction_cost_bp", True) == 0, "无对冲任务的对冲费率必须为零。")
    _require(kpis.get("calculation_version") == "backtest_v20" and kpis.get("asset") == "BTC"
             and kpis.get("numeraire") == "BTC", "模型版本或 KPI 资产/币种不在已核实范围。")
    _require(kpis.get("result_complete") is True and kpis.get("daily_statistics_complete") is True
             and _number(kpis, "unresolved_lots") == 0, "结果不完整或仍有未闭合头寸；不能核定完整闭合 BTC 收益。")
    _require(_number(kpis, "missing_daily_observations") == 0, "服务报告存在缺失每日观测。")
    skip_counts = report.get("skip_counts", {})
    _require(isinstance(skip_counts, dict), "服务跳过原因没有可核对的分类。")
    _require(all(key == "entry_weekday_filtered" or _number(skip_counts, key, True) == 0
                 for key in skip_counts), "服务报告包含计划星期过滤以外的跳过事件。")
    filtered_count = _number(skip_counts, "entry_weekday_filtered", True) if "entry_weekday_filtered" in skip_counts else Decimal(0)
    _require(filtered_count == _number(kpis, "skip_total"), "服务跳过计数不能全部对应计划入场星期过滤。")
    details = _csv_rows(artifact_files.get("csv"), "明细")
    daily = _csv_rows(artifact_files.get("daily_csv"), "每日")
    _require(_number(kpis, "valid_rows") == len(details), "完整 CSV 行数与服务有效事件数不一致。")
    start = _utc(f"{request.get('start_date')}T{request.get('session_bucket')}Z")
    end = _utc(f"{request.get('end_date')}T{request.get('session_bucket')}Z")
    _require(start < end, "请求窗口无效。")
    weekdays = request.get("entry_weekdays")
    _require(isinstance(weekdays, list) and bool(weekdays)
             and all(type(day) is int and 0 <= day <= 6 for day in weekdays), "入场星期配置不明确。")
    lots, identities, by_date, cash_rows, event_dates = {}, set(), {}, [], {}
    premium = receipt = fees = traded_nominal = Decimal(0)
    previous_time = None
    trade_count = mark_count = 0
    fields = ("total_pnl", "option_pnl", "hedge_pnl", "transaction_cost", "option_transaction_cost", "hedge_transaction_cost")
    for row in details:
        _require(all(row.get(key) == value for key, value in {
            "asset": "BTC", "numeraire": "BTC", "calculation_version": "backtest_v20",
            "mode": "reopen", "hedge_mode": "none", "side": "long", "option_type": leg["option_type"],
            "source_kind": "surface", "surface_tenor_coverage": "covered",
            "market_data_status": "scheduled", "valuation_complete": "True", "result_complete": "True",
            "valuation_status": "complete", "daily_return_valid": "True",
        }.items()), "明细资产、币种、模型、策略或估值完整性不符合已核实范围；延期、结算和缺失数据暂不核账。")
        stamp, opened_at, expiry = _utc(row.get("event_time")), _utc(row.get("open_time")), _utc(row.get("expiry_time"))
        _require(previous_time is None or stamp >= previous_time, "明细事件时间倒序。")
        previous_time = stamp
        _require(row.get("date") == stamp.date().isoformat(), "明细日期与 UTC 事件时间不一致。")
        _require(stamp.timetz() == start.timetz(), "已标 scheduled 的模型事件与请求估值时段不一致。")
        _require(_number(row, "quantity", True) == quantity and _number(row, "delta_target") == delta
                 and _number(row, "DTE") == tenor and _number(row, "close_dte") == 0,
                 "明细数量或策略参数与请求不一致。")
        _require(_number(row, "forward", True) > 0 and _number(row, "strike", True) > 0,
                 "模型远期价格或行权价无效。")
        _require(_utc(row.get("surface_source_time")) <= stamp, "曲面来源时间晚于模型事件时间。")
        _require(not row.get("skip_reason") and not row.get("entry_failure_reason"), "模型明细记录了跳过或开仓失败。")
        _require(stamp < expiry, "出现本轮未支持的到期或结算事件。")
        _match(Decimal(str((expiry - opened_at).total_seconds())), tenor * 86400, "实际开仓期限与目标期限")
        for field in ("hedge_pnl", "hedge_transaction_cost", "hedge_position", "hedge_rebalances"):
            _require(_number(row, field) == 0, "模型明细包含本轮未支持的对冲金额或事件。")
        event = row.get("event")
        _require(event in {"open", "mark", "close"}, "存在未支持的模型事件；不能推断现金流。")
        key = (row.get("lot_id"), row.get("leg_id"))
        _require(all(isinstance(value, str) and bool(value) for value in key), "模型 lot/leg 身份缺失。")
        identity = (*key, row.get("event_time"), event)
        _require(identity not in identities, "模型事件身份重复。")
        identities.add(identity)
        event_dates.setdefault(key, set()).add(row["date"])
        value, fee = _number(row, "option_value", True), _number(row, "option_transaction_cost", True)
        _match(fee, _number(row, "transaction_cost", True), "期权费与总费用")
        _match(fee, quantity * rate / 10000 if event in {"open", "close"} else Decimal(0), "逐事件 BTC 名义量费用")
        _match(_number(row, "total_pnl"), _number(row, "option_pnl"), "无对冲逐事件盈亏")
        if event == "open":
            _require(key not in lots and row.get("position_closed") == "False", "重复开仓或开仓已标平仓。")
            _require(stamp == opened_at and start <= stamp <= end and stamp.weekday() in weekdays,
                     "模型实际开仓时点不在请求窗口与允许入场星期内。")
            _require(value > 0 and not row.get("previous_mark_time"), "开仓权利金无效或带有未识别的前次估值。")
            _match(_number(row, "option_pnl"), -fee, "开仓 PnL 与开仓费用")
            lots[key] = {"opened": row, "last": row, "closed": False}
            premium += value
            cash_rows.append({"date": row["event_time"], "lot_id": key[0], "leg_id": key[1],
                              "description": "模型开仓权利金支出（已含数量）", "amount_btc": _text(-value)})
        else:
            _require(key in lots and not lots[key]["closed"], "找不到对应未闭合的 lot/leg 开仓事件。")
            lot, prior = lots[key], lots[key]["last"]
            for field in ("open_time", "expiry_time", "strike", "quantity"):
                _require(row.get(field) == lot["opened"].get(field), f"同一 lot/leg 的 {field} 不一致。")
            _require(_utc(prior["event_time"]) < stamp and _utc(row.get("previous_mark_time")) == _utc(prior["event_time"]),
                     "逐 lot/leg 前次估值时间断链或重复。")
            _match(_number(row, "previous_option_value", True), _number(prior, "option_value", True), "相邻模型价值")
            _match(_number(row, "option_pnl"), value - _number(prior, "option_value", True) - fee,
                   "逐事件模型价值变动减当次费用")
            _require(row.get("position_closed") == ("True" if event == "close" else "False"), "事件与头寸闭合状态不一致。")
            lot["last"] = row
            if event == "close":
                lot["closed"] = True
                receipt += value
                cash_rows.append({"date": row["event_time"], "lot_id": key[0], "leg_id": key[1],
                                  "description": "模型平仓收入（已含数量）", "amount_btc": _text(value)})
            else:
                mark_count += 1
        if event in {"open", "close"}:
            trade_count += 1
            traded_nominal += quantity
            cash_rows.append({"date": row["event_time"], "lot_id": key[0], "leg_id": key[1],
                              "description": "假设开仓费用" if event == "open" else "假设平仓费用", "amount_btc": _text(-fee)})
        fees += fee
        totals = by_date.setdefault(row["date"], {field: Decimal(0) for field in fields})
        for field in fields:
            totals[field] += _number(row, field)
    _require(bool(lots) and all(lot["closed"] for lot in lots.values()), "仍有未闭合 lot/leg；中间估值不能当成平仓现金收入。")
    net, daily_total, seen_dates = receipt - premium - fees, Decimal(0), set()
    detail_sum = sum(_number(row, "total_pnl") for row in details)
    _match(net, detail_sum, "现金流与逐事件盈亏合计")
    last_day, filtered_days = None, 0
    for row in daily:
        _require(all(row.get(key) == value for key, value in {
            "asset": "BTC", "numeraire": "BTC", "calculation_version": "backtest_v20", "hedge_mode": "none",
            "valuation_complete": "True", "result_complete": "True", "daily_return_valid": "True",
        }.items()), "每日记录的币种或完整性不匹配明细。")
        _require(row.get("valuation_status") in {"complete", "flat"}, "每日估值状态不是完整估值或明确空仓。")
        day = _utc(f"{row.get('date')}T00:00:00Z").date()
        _require(last_day is None or day == last_day + timedelta(days=1), "每日日期重复、倒序或中间缺失；不能补零。")
        last_day = day
        seen_dates.add(row["date"])
        active = sum(_utc(lot["opened"]["event_time"]).date() <= day
                     < _utc(lot["last"]["event_time"]).date() for lot in lots.values())
        _require(_number(row, "active_lots") == active, "每日未平仓数量与完整 lot/leg 事件不一致。")
        if row.get("valuation_status") == "flat":
            _require(active == 0 and row["date"] not in by_date and _number(row, "valid_events") == 0,
                     "flat 日期仍有头寸或事件，不能认定为已知零收益日。")
        if row.get("entry_data_status") == "filtered":
            _require(day.weekday() not in weekdays and start.date() <= day < end.date(),
                     "服务星期过滤与原始请求的入场限制不一致。")
            filtered_days += 1
        for key, lot in lots.items():
            if _utc(lot["opened"]["event_time"]).date() < day <= _utc(lot["last"]["event_time"]).date():
                _require(row["date"] in event_dates[key], "持仓日缺少对应 lot/leg 估值或平仓事件，不能当作零收益。")
        for field in fields:
            _match(_number(row, field), by_date.get(row["date"], {}).get(field, Decimal(0)), f"每日与当日明细 {field}")
        daily_total += _number(row, "total_pnl")
        _match(_number(row, "cum_pnl"), daily_total, "每日累计盈亏")
    _require(set(by_date).issubset(seen_dates), "每日表缺少模型事件日期。")
    _require(filtered_days == filtered_count, "逐日计划过滤记录与服务 skip_total 不一致。")
    _require(daily[0]["date"] == start.date().isoformat()
             and daily[-1]["date"] >= max(end.date().isoformat(), details[-1]["date"]),
             "每日表没有覆盖请求窗口和全部事件。")
    _require(_number(daily[-1], "active_lots") == 0, "每日末记录仍存在未平仓模型组合。")
    _match(daily_total, net, "每日盈亏与现金流合计")
    _match(_number(kpis, "total_pnl"), net, "服务总盈亏与模型现金流")
    _match(_number(kpis, "option_pnl"), net, "服务期权盈亏与模型现金流")
    _require(_number(kpis, "hedge_pnl") == 0 and _number(kpis, "hedge_transaction_cost") == 0,
             "汇总存在本轮未支持的对冲盈亏或费用。")
    _match(_number(kpis, "option_transaction_cost", True), fees, "服务期权费用合计")
    _match(_number(kpis, "transaction_cost", True), fees, "服务总费用合计")
    result = summarize_cashflows(premium, receipt, fees)
    result.update({
        "status": "model_ledger_verified", "model_ledger_verified": True, "position_status": "closed",
        "price_source": f"SABR/WV4 理论模型价；{tenor} 天目标期限与行权价由曲面确定，不是可成交 bid/ask。",
        "fee_assumption": f"假设每次开平仓 {rate} bp × BTC 名义数量；{trade_count} 次交易事件费用合计 {_text(fees)} BTC，已包含在服务 PnL 中。按原始模型价值重建仅扣一次，并非账户实际费率。",
        "method": "模型账本净 BTC = 各 lot/leg 平仓 option_value 合计 − 开仓 option_value 合计 − 开平仓费用。中间 mark 只核对估值变动，不计现金收入；option_value 已含 quantity，按各时点 USD 模型价值 / 当时 forward 计 BTC，不再乘数量、不用期末币价换算。已核对完整明细、每日表和 KPI。权利金回报率分母为累计模型开仓权利金（非最大资金占用），账户回报率仅以假设 0.2 BTC 为分母。",
        "gaps": [
            "模型期限和行权价来自曲面，没有实际 Deribit instrument_name，不证明有相同的可交易合约。",
            "没有真实成交、bid/ask、深度、滑点及交易所现金流水；模型收益不等于可成交收益。",
            "费用为请求中的假设费率，无真实账户或资金授权；0.2 BTC 仅是假设资金，不是账户余额。",
            "仅核对 backtest_v20 单腿买方无对冲、完整闭合的 open/mark/close 模型记录；到期结算、延期与缺失数据仍不支持。",
        ],
        "rows": cash_rows,
        "audit": {
            "calculation_version": "backtest_v20", "detail_rows": len(details), "daily_rows": len(daily),
            "absolute_tolerance_btc": _text(MODEL_TOLERANCE), "reconstructed_net_btc": _text(net),
            "detail_pnl_sum_btc": _text(detail_sum), "daily_pnl_sum_btc": _text(daily_total),
            "reported_pnl_btc": _text(_number(kpis, "total_pnl")), "reported_difference_btc": _text(net - _number(kpis, "total_pnl")),
            "fees_already_in_reported_pnl": True, "nominal_quantity_btc": _text(quantity), "value_already_includes_quantity": True,
            "open_forward_usd": details[0]["forward"], "close_forward_usd": details[-1]["forward"],
            "base_option_fee_bp": _text(rate), "traded_nominal_btc": _text(traded_nominal),
            "trade_event_count": trade_count, "mark_event_count": mark_count, "lot_count": len(lots),
            "planned_weekday_filtered_days": filtered_days,
            "checks": ["request_and_version", "closed_lot_leg_chains", "BTC_currency", "event_fee_identities",
                       "marks_are_not_cash", "detail_pnl", "daily_pnl", "service_kpis", "no_double_quantity_or_fee"],
        },
    })
    return result


def compare_fee_scenario(accounting, higher_fee_bp, *, run_id=None):
    """Bind an arithmetic fee sensitivity to a verified closed model ledger.

    This does not request another remote backtest or claim execution at either
    fee assumption. All marks, positions and price paths stay fixed.
    """
    if not isinstance(accounting, dict) or accounting.get("model_ledger_verified") is not True:
        raise ValueError("仅可对已核对并完全闭合的 BTC 模型账本比较费用。")
    audit = accounting.get("audit")
    if not isinstance(audit, dict) or accounting.get("position_status") != "closed":
        raise ValueError("缺少已闭合模型账本的费用核对依据。")
    higher = _decimal(higher_fee_bp, "higher_fee_bp")
    base = _decimal(audit.get("base_option_fee_bp"), "base_option_fee_bp")
    if higher <= base or higher > 100:
        raise ValueError("较高费用必须高于基础费率且不超过本阶段的 100 bp。")
    nominal = _decimal(audit.get("traded_nominal_btc"), "traded_nominal_btc")
    premium = _decimal(accounting.get("premium_paid_btc"), "premium_paid_btc")
    receipt = _decimal(accounting.get("exit_income_btc"), "exit_income_btc")
    base_fees = _decimal(accounting.get("fees_btc"), "fees_btc")
    if nominal <= 0 or premium <= 0:
        raise ValueError("已核对账本的交易名义量与累计开仓权利金必须为正。")
    with localcontext() as context:
        context.prec = 80
        _match(base_fees, nominal * base / 10000, "已核对账本与基础费用")
        gross = receipt - premium
        base_net = gross - base_fees
        _match(base_net, _number(accounting, "btc_net_pnl"), "基础费用与原净收益")
        higher_fees = nominal * higher / 10000
        result = {
            "status": "computed_from_verified_ledger", "run_id": run_id,
            "method": "同一原始模型记录、同一数量与全部价格路径，仅替换开平仓费用 bp；确定性费用敏感性，不是第二次远端回测。",
            "base_fee_bp": _text(base), "higher_fee_bp": _text(higher),
            "traded_nominal_btc": _text(nominal), "trade_event_count": audit.get("trade_event_count"),
            "gross_pnl_btc": _text(gross), "base_fees_btc": _text(base_fees), "higher_fees_btc": _text(higher_fees),
            "base_net_btc": _text(base_net), "higher_net_btc": _text(gross - higher_fees),
            "incremental_cost_btc": _text(higher_fees - base_fees),
            "gross_profit_consumed_base_pct": _text(base_fees / gross * 100) if gross > 0 else None,
            "gross_profit_consumed_higher_pct": _text(higher_fees / gross * 100) if gross > 0 else None,
            "base_cost_as_premium_pct": _text(base_fees / premium * 100),
            "higher_cost_as_premium_pct": _text(higher_fees / premium * 100),
            "ratio_note": "只有毛模型收益为正时才计算成本占毛收益比例；累计开仓权利金并非最大资金占用。",
            "evidence_fields": ["analysis.premium_paid_btc", "analysis.exit_income_btc", "analysis.fees_btc",
                                "analysis.btc_net_pnl", "analysis.audit.traded_nominal_btc", "analysis.audit.base_option_fee_bp"],
            "remote_backtest_created": False, "executable_edge_established": False,
        }
    return result


def _decimal(value, name):
    if value is None or isinstance(value, bool):
        raise ValueError(f"{name} must be a known finite amount")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise ValueError(f"{name} must be a known finite amount") from error
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    if amount.adjusted() > 30 or amount.as_tuple().exponent < -30:
        raise ValueError(f"{name} exceeds supported amount precision")
    return amount


def _text(amount):
    if amount == 0:
        return "0"
    result = format(amount, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def summarize_cashflows(premium_btc, exit_btc, fee_btc, fees_included=False,
                        hypothetical_capital_btc="0.2"):
    """Summarize known BTC amounts with fees deducted exactly once.

    Premium is a positive total debit; exit is a nonnegative total receipt,
    including settlement when applicable. If ``fees_included`` is true, those
    two supplied amounts already contain the documented fees, and fee_btc is
    disclosed without being subtracted again. Unknown fees are never zero.
    Returns decimal strings so JSON storage does not introduce float rounding.
    The capital denominator is explicitly hypothetical, never an account.
    """
    if not isinstance(fees_included, bool):
        raise TypeError("fees_included must be a boolean")
    premium = _decimal(premium_btc, "premium_btc")
    receipt = _decimal(exit_btc, "exit_btc")
    fees = _decimal(fee_btc, "fee_btc")
    capital = _decimal(hypothetical_capital_btc, "hypothetical_capital_btc")
    if premium == 0 or capital == 0:
        raise ValueError("premium and hypothetical capital must be positive")
    with localcontext() as context:
        context.prec = 80
        net = receipt - premium - (Decimal(0) if fees_included else fees)
        premium_return = net / premium * 100
        capital_return = net / capital * 100
    return {
        "btc_net_pnl": _text(net),
        "premium_paid_btc": _text(premium),
        "exit_income_btc": _text(receipt),
        "fees_btc": _text(fees),
        "fees_included": fees_included,
        "fees_included_scope": "仅指输入 premium/exit 现金流是否已含费用；不是服务 PnL 的费用标志。服务 PnL 是否已扣费见 audit.fees_already_in_reported_pnl。",
        "premium_return_pct": _text(premium_return),
        "hypothetical_account_return_pct": _text(capital_return),
        "hypothetical_capital_btc": _text(capital),
        "capital_is_hypothetical": True,
    }


def _reported_number(value):
    """Retain a finite signed reported number without assigning BTC semantics."""
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not amount.is_finite() or abs(amount.adjusted()) > 30:
        return None
    return _text(amount)


def analyze_report(report, artifact_files):
    """Verify the narrow observed model ledger, or preserve explicit gaps.

    Neither a BTC numeraire label, preview rows, nor a CSV filename establishes
    cashflow units and fee semantics. A known schema must independently agree
    across the submitted request, full CSV event ledger, daily CSV, and KPIs.
    """
    if not isinstance(report, dict):
        report = {}
    kpis = report.get("kpis")
    kpis = kpis if isinstance(kpis, dict) else {}
    currency = kpis.get("numeraire")
    currency = currency if isinstance(currency, str) and currency in {"BTC", "ETH", "USD", "USDC"} else None
    reported_pnl = _reported_number(kpis.get("total_pnl"))
    gaps = [
        "未核实每笔开仓权利金、平仓收入或到期结算、费用及其发生时间，未完成逐笔核账。",
        "服务 quantity 的名义数量单位，以及模型期权与 Deribit 已挂牌合约的对应关系尚未核实。",
        "尚未核实费用是否已计入服务 PnL，以及每笔费用的币种、计费基数和扣除方式。",
        "BTC numeraire 标签不能单独证明逐笔币本位现金流公式；无法可靠重建 BTC 净收益。",
    ]
    if not isinstance(artifact_files, dict) or not artifact_files.get("csv"):
        gaps.insert(0, "未取得完整明细 CSV；页面预览或汇总不能替代完整逐笔记录。")
    else:
        gaps.insert(0, "明细 CSV 已保存本地，但字段及现金流语义尚未验证，暂不据此计算净收益。")
    if currency is None:
        gaps.append("服务汇总结果未明确返回受支持的计价币种。")
    elif currency != "BTC":
        gaps.append("服务汇总结果不是 BTC 计价；不将美元盈亏除以期末币价作为 BTC 策略收益。")
    if reported_pnl is None:
        gaps.append("服务未返回有效的汇总 total_pnl 数值。")
    if kpis.get("result_complete") is False:
        gaps.append("服务标记最终估值不完整，仍可能存在未结算或未估值的组合。")
    if kpis.get("daily_statistics_complete") is False:
        gaps.append("服务标记每日统计存在缺失，不能将缺失区间视为零盈亏。")
    result = {
        "status": "unreconciled",
        "model_ledger_verified": False,
        "position_status": "unclosed" if _reported_number(kpis.get("unresolved_lots")) not in {None, "0"} else "unknown",
        "btc_net_pnl": None,
        "premium_paid_btc": None,
        "exit_income_btc": None,
        "fees_btc": None,
        "premium_return_pct": None,
        "hypothetical_account_return_pct": None,
        "hypothetical_capital_btc": "0.2",
        "capital_is_hypothetical": True,
        "reported_currency": currency,
        "reported_pnl": reported_pnl,
        "price_source": "SABR/WV4 曲面模型估值；不是 bid/ask 可成交收益。",
        "fee_assumption": "服务支持按期权标的名义额设置每次开平仓费用 bp；实际费率、包含方式及账户费用尚未核实。",
        "method": "仅保留服务明确返回的汇总币种和盈亏；未将汇总 PnL 当成逐笔核账结果，也不做期末汇率换算。0.2 BTC 仅为假设初始资金，无账户连接。",
        "gaps": gaps,
        "rows": [],
        "audit": None,
    }
    try:
        _require(isinstance(artifact_files, dict), "没有完整模型 CSV 产物。")
        with localcontext() as context:
            context.prec = 80
            result.update(_verified_model_ledger(report, artifact_files))
    except LedgerGap as error:
        result["gaps"].insert(0, str(error))
    return result
