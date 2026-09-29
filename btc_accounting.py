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


def _csv_pair(path, description):
    _require(path is not None, f"未取得完整{description} CSV，不能完成模型账本核对。")
    try:
        _require(Path(path).stat().st_size <= 1_000_000, f"{description} CSV 超出固定单笔任务范围。")
        with Path(path).open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            fields = reader.fieldnames or []
            _require(bool(fields) and len(set(fields)) == len(fields), f"{description} CSV 表头缺失或重复。")
            rows = []
            for row in reader:
                rows.append(row)
                _require(len(rows) <= 2 and None not in row, f"{description} CSV 出现额外记录或字段。")
    except (OSError, UnicodeError, csv.Error, TypeError) as error:
        raise LedgerGap(f"{description} CSV 无法完整读取。") from error
    _require(len(rows) == 2, f"{description} CSV 必须恰有两条完整记录。")
    return rows


def _verified_model_ledger(report, artifact_files):
    """Verify only the observed v20 single long-call open/close model ledger.

    This is deliberately not a general trade parser. The complete service
    report states that inverse option_value is the quantity-weighted USD mark
    divided by that mark's own forward, and fees are already in row PnL.
    Unknown shapes, settlement, hedges and currencies remain unsupported.
    """
    request, kpis = report.get("request"), report.get("kpis")
    _require(isinstance(request, dict) and isinstance(kpis, dict), "缺少原始请求或结果 KPI。")
    _require(all(request.get(key) == value for key, value in {
        "asset": "BTC", "numeraire": "BTC", "mode": "reopen", "hedge_mode": "none",
    }.items()), "本轮仅核对 BTC inverse、reopen、无对冲的固定买方模型任务。")
    legs = request.get("legs")
    _require(isinstance(legs, list) and len(legs) == 1 and isinstance(legs[0], dict), "本轮只支持一条买入看涨腿。")
    leg = legs[0]
    _require(leg.get("side") == "long" and leg.get("option_type") == "call", "本轮只支持买入看涨腿。")
    quantity = _number(leg, "quantity", True)
    _require(quantity > 0 and _number(leg, "delta") == Decimal("0.5")
             and _number(leg, "expiry") == 7 and _number(leg, "close_dte") == 0,
             "本轮仅支持已核实的 0.5 Delta、7 天目标期限、close_dte=0 的买入看涨腿。")
    rate = _number(request, "option_transaction_cost_bp", True)
    _require(_number(request, "hedge_transaction_cost_bp", True) == 0, "无对冲任务的对冲费率必须为零。")
    _require(kpis.get("calculation_version") == "backtest_v20" and kpis.get("asset") == "BTC"
             and kpis.get("numeraire") == "BTC", "模型版本或 KPI 资产/币种不在已核实范围。")
    _require(kpis.get("result_complete") is True and kpis.get("daily_statistics_complete") is True
             and _number(kpis, "unresolved_lots") == 0 and _number(kpis, "valid_rows") == 2,
             "服务结果未明确完整闭合为两条模型事件。")
    _require(_number(kpis, "skip_total") == 0 and _number(kpis, "missing_daily_observations") == 0,
             "服务报告存在跳过事件或缺失每日观测。")
    opened, closed = _csv_pair(artifact_files.get("csv"), "明细")
    daily = _csv_pair(artifact_files.get("daily_csv"), "每日")
    _require(opened.get("event") == "open" and closed.get("event") == "close",
             "明细不是按顺序排列的一次开仓、一次平仓；不支持结算或额外事件。")
    _require(opened.get("position_closed") == "False" and closed.get("position_closed") == "True",
             "模型头寸未明确从开仓转为已平仓。")
    for field in ("lot_id", "leg_id", "open_time", "expiry_time", "strike", "quantity"):
        _require(bool(opened.get(field)) and opened[field] == closed.get(field), f"开平仓 {field} 不一致或缺失。")
    open_time, close_time = _utc(opened.get("event_time")), _utc(closed.get("event_time"))
    _require(open_time < close_time < _utc(closed.get("expiry_time")), "事件时间倒序或出现本轮未支持的到期结算。")
    _require(_utc(opened["open_time"]) == open_time and _utc(closed.get("previous_mark_time")) == open_time,
             "开仓时间或前次估值时间与明细事件不一致。")
    _require(open_time == _utc(f"{request.get('start_date')}T{request.get('session_bucket')}Z")
             and close_time == _utc(f"{request.get('end_date')}T{request.get('session_bucket')}Z"),
             "事件时间不匹配原始请求的起止 UTC 时点。")
    weekdays = request.get("entry_weekdays")
    _require(isinstance(weekdays, list) and open_time.weekday() in weekdays,
             "模型开仓日期不在请求允许的入场星期内。")
    _require(_utc(opened["expiry_time"]) - open_time == timedelta(days=7), "模型期限不等于原请求的 7 天。")
    fees = []
    for row in (opened, closed):
        _require(all(row.get(key) == value for key, value in {
            "asset": "BTC", "numeraire": "BTC", "calculation_version": "backtest_v20",
            "mode": "reopen", "hedge_mode": "none", "side": "long", "option_type": "call",
            "source_kind": "surface", "surface_tenor_coverage": "covered",
            "market_data_status": "scheduled", "interp_mode": "time_interp",
            "valuation_complete": "True", "result_complete": "True",
            "valuation_status": "complete", "daily_return_valid": "True",
        }.items()), "明细资产、币种、模型、策略或估值完整性不符合固定任务。")
        _require(row.get("date") == _utc(row.get("event_time")).date().isoformat(), "明细日期与 UTC 事件时间不一致。")
        _require(_number(row, "quantity", True) == quantity and _number(row, "delta_target") == Decimal("0.5")
                 and _number(row, "DTE") == 7 and _number(row, "close_dte") == 0,
                 "明细数量或策略参数与请求不一致。")
        _require(_number(row, "forward", True) > 0 and _number(row, "strike", True) > 0,
                 "模型远期价格或行权价无效。")
        _require(_utc(row.get("surface_source_time")) <= _utc(row.get("event_time")), "曲面来源时间晚于模型事件时间。")
        _require(not row.get("skip_reason") and not row.get("entry_failure_reason"), "模型明细记录了跳过或开仓失败。")
        for field in ("hedge_pnl", "hedge_transaction_cost", "hedge_position", "hedge_rebalances"):
            _require(_number(row, field) == 0, "模型明细包含本轮未支持的对冲金额或事件。")
        fee = _number(row, "option_transaction_cost", True)
        _match(fee, _number(row, "transaction_cost", True), "期权费与总费用")
        _match(fee, quantity * rate / 10000, "BTC 名义量乘每次费用 bp")
        _match(_number(row, "total_pnl"), _number(row, "option_pnl"), "无对冲逐事件盈亏")
        fees.append(fee)
    premium, receipt = _number(opened, "option_value", True), _number(closed, "option_value", True)
    _require(premium > 0, "模型开仓权利金必须为正数。")
    _match(_number(closed, "previous_option_value", True), premium, "平仓记录的前次模型价值与开仓价值")
    _match(_number(opened, "option_pnl"), -fees[0], "开仓 PnL 与开仓费用")
    _match(_number(closed, "option_pnl"), receipt - premium - fees[1], "平仓 PnL 与模型价值变动减平仓费")
    net = receipt - premium - sum(fees)
    detail_sum = sum(_number(row, "total_pnl") for row in (opened, closed))
    _match(net, detail_sum, "现金流与明细盈亏合计")
    _match(_number(closed, "cum_pnl"), net, "明细累计盈亏")
    for index, row in enumerate(daily):
        detail = (opened, closed)[index]
        _require(all(row.get(key) == value for key, value in {
            "asset": "BTC", "numeraire": "BTC", "calculation_version": "backtest_v20",
            "hedge_mode": "none", "valuation_complete": "True", "result_complete": "True",
            "daily_return_valid": "True", "valuation_status": "complete",
        }.items()) and row.get("date") == detail.get("date"), "每日记录的币种、日期或完整性不匹配明细。")
        for field in ("total_pnl", "option_pnl", "hedge_pnl", "transaction_cost", "option_transaction_cost", "hedge_transaction_cost", "cum_pnl"):
            _match(_number(row, field), _number(detail, field), f"每日与明细 {field}")
    _require(_number(daily[-1], "active_lots") == 0, "每日末记录仍存在未平仓模型组合。")
    _match(sum(_number(row, "total_pnl") for row in daily), net, "每日盈亏与现金流合计")
    _match(_number(kpis, "total_pnl"), net, "服务总盈亏与模型现金流")
    _match(_number(kpis, "option_pnl"), net, "服务期权盈亏与模型现金流")
    _require(_number(kpis, "hedge_pnl") == 0 and _number(kpis, "hedge_transaction_cost") == 0,
             "汇总存在本轮未支持的对冲盈亏或费用。")
    _match(_number(kpis, "option_transaction_cost", True), sum(fees), "服务期权费用合计")
    _match(_number(kpis, "transaction_cost", True), sum(fees), "服务总费用合计")
    result = summarize_cashflows(premium, receipt, sum(fees))
    result.update({
        "status": "model_ledger_verified", "model_ledger_verified": True,
        "price_source": "SABR/WV4 理论模型价；7 天期限与行权价由曲面插值确定，不是可成交 bid/ask。",
        "fee_assumption": f"假设每次开平仓 {rate} bp × BTC 名义数量；本次费用合计 {_text(sum(fees))} BTC，已包含在服务 PnL 中。按原始模型价值重建只扣一次费用；并非账户实际费率。",
        "method": "模型账本净 BTC = 平仓 option_value − 开仓 option_value − 两次费用。option_value 已包含 quantity，按各估值时点的 USD 模型价值 / 当时 forward 计为 BTC，不再乘数量、不用期末币价换算。已核对两条明细、每日表和 KPI；仅为模型开平仓账本，不是交易所现金流水。权利金回报率以不含费用的模型开仓权利金为分母；账户回报率仅以假设 0.2 BTC 为分母。",
        "gaps": [
            "模型期限和行权价来自曲面插值，没有实际 Deribit instrument_name，不证明有相同的可交易合约。",
            "没有真实成交、bid/ask、深度、滑点及交易所现金流水；模型收益不等于可成交收益。",
            "费用为请求中的假设费率，无真实账户或资金授权；0.2 BTC 仅是假设资金，不是账户余额。",
            "仅核对本轮 backtest_v20 单腿无对冲开平仓形状；到期结算、其他策略或缺失数据仍不支持。",
        ],
        "rows": [
            {"date": opened["event_time"], "description": "模型开仓权利金支出（已含数量）", "amount_btc": _text(-premium)},
            {"date": opened["event_time"], "description": "假设开仓费用", "amount_btc": _text(-fees[0])},
            {"date": closed["event_time"], "description": "模型平仓收入（已含数量）", "amount_btc": _text(receipt)},
            {"date": closed["event_time"], "description": "假设平仓费用", "amount_btc": _text(-fees[1])},
        ],
        "audit": {
            "calculation_version": "backtest_v20", "detail_rows": 2, "daily_rows": 2,
            "absolute_tolerance_btc": _text(MODEL_TOLERANCE),
            "reconstructed_net_btc": _text(net), "detail_pnl_sum_btc": _text(detail_sum),
            "daily_pnl_sum_btc": _text(sum(_number(row, "total_pnl") for row in daily)),
            "reported_pnl_btc": _text(_number(kpis, "total_pnl")),
            "reported_difference_btc": _text(net - _number(kpis, "total_pnl")),
            "fees_already_in_reported_pnl": True,
            "nominal_quantity_btc": _text(quantity), "value_already_includes_quantity": True,
            "open_forward_usd": opened["forward"], "close_forward_usd": closed["forward"],
            "checks": ["request_and_version", "closed_single_lot", "BTC_currency", "event_fee_identities",
                       "detail_pnl", "daily_pnl", "service_kpis", "no_double_quantity_or_fee"],
        },
    })
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
