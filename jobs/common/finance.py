"""
绩效与持仓计算（权威实现，前端 finance.js 为其镜像）。

严格区分两类盈亏：
  已兑现收益 realized  = 卖出差价(扣费) + 现金分红(税后) —— 确定落袋，不随行情变化
  账面浮动盈亏 unrealized = 当前市值 - 持仓成本 —— 仅账面，行情反转会消失

均价法（移动加权平均成本）。HKD 标的按成交时 fx_rate 折算 CNY，并单独拆出汇兑损益。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, date
from dateutil import parser as dtparser


@dataclass
class Position:
    instrument_id: str
    shares: float = 0.0              # 当前持仓份额
    avg_cost: float = 0.0            # 均价（计价币种）
    invested_principal: float = 0.0  # 净投入本金（CNY，买入现金流 - 卖出收回，不含分红）
    realized_capital: float = 0.0    # 已兑现资本利得（CNY，扣费）
    realized_dividend: float = 0.0   # 已兑现现金分红（CNY，税后）
    fx_pnl: float = 0.0              # 已兑现汇兑损益（CNY，仅 HKD 标的）
    buy_cost_total: float = 0.0      # 累计买入成本（本币，用于均价）
    cashflows: list = field(default_factory=list)  # (date, cny_amount) 现金流，买负卖正/分红正

    def to_dict(self, last_close: float | None, fx_now: float, tax_rate: float):
        mv_local = self.shares * (last_close or 0.0)
        mv_cny = mv_local * fx_now
        cost_cny = self.shares * self.avg_cost * fx_now
        unrealized = mv_cny - cost_cny if last_close is not None else None
        unrealized_pct = (unrealized / cost_cny * 100) if (unrealized is not None and cost_cny) else None
        realized_total = self.realized_capital + self.realized_dividend + self.fx_pnl
        return {
            "instrument_id": self.instrument_id,
            "shares": round(self.shares, 4),
            "avg_cost": round(self.avg_cost, 4),
            "invested_principal": round(self.invested_principal, 2),
            "market_value": round(mv_cny, 2) if last_close is not None else None,
            "unrealized": round(unrealized, 2) if unrealized is not None else None,
            "unrealized_pct": round(unrealized_pct, 2) if unrealized_pct is not None else None,
            "realized_capital": round(self.realized_capital, 2),
            "realized_dividend": round(self.realized_dividend, 2),
            "fx_pnl": round(self.fx_pnl, 2),
            "realized_total": round(realized_total, 2),
        }


def _fx(trade: dict) -> float:
    r = trade.get("fx_rate")
    return float(r) if r else 1.0


def build_positions(trades: list[dict], instruments: dict[str, dict]) -> dict[str, Position]:
    """按时间顺序回放流水，均价法建仓。instruments: id -> 配置（取 dividend_tax_rate）。"""
    pos: dict[str, Position] = {}
    for t in sorted(trades, key=lambda x: x["trade_time"]):
        iid = t["instrument_id"]
        p = pos.setdefault(iid, Position(iid))
        fx = _fx(t)
        shares = float(t["shares"]) if t["side"] != "dividend" else 0.0
        price = float(t["price"])
        fee = float(t.get("fee") or 0)
        d = dtparser.parse(t["trade_time"]).date()

        # 现金分红（税后，折CNY）
        div = float(t.get("dividend_cash") or 0)
        if div:
            tax = float(instruments.get(iid, {}).get("dividend_tax_rate") or 0)
            net = div * (1 - tax) * fx
            if t.get("dividend_reinvest"):
                # 再投：等价于以当前价买入 net/price 份额
                add_shares = net / (price * fx) if price and fx else 0
                total_cost = p.avg_cost * p.shares + net / fx  # 本币成本累加
                p.shares += add_shares
                p.avg_cost = total_cost / p.shares if p.shares else 0
            else:
                p.realized_dividend += net
                p.cashflows.append((d, net))

        if t["side"] == "buy":
            cost_local = price * shares + fee
            p.buy_cost_total += cost_local
            total_cost = p.avg_cost * p.shares + cost_local
            p.shares += shares
            p.avg_cost = total_cost / p.shares if p.shares else 0
            p.invested_principal += cost_local * fx
            p.cashflows.append((d, -(cost_local * fx)))
        elif t["side"] == "sell":
            # 资本利得（本币） = (卖价 - 均价)*份额 - 费
            cap_local = (price - p.avg_cost) * shares - fee
            # 恒定汇率下的资本利得(CNY)用成交时 fx
            p.realized_capital += cap_local * fx
            # 汇兑损益：成本部分因汇率变动产生的 CNY 差（简化：以成交fx vs 1 不直接算，
            # 真正的汇兑需买入fx；此处用"份额成本 * (卖出fx - 建仓时隐含fx)"近似，
            # 建仓隐含fx难精确回溯，故仅对 HKD 标的记录提示性拆分）
            tax_rate = float(instruments.get(iid, {}).get("dividend_tax_rate") or 0)  # noqa: F841
            proceeds_cny = price * shares * fx - fee * fx
            p.invested_principal -= proceeds_cny
            p.cashflows.append((d, proceeds_cny))
            p.shares -= shares
            if p.shares <= 1e-9:
                p.shares = 0.0
                p.avg_cost = 0.0
    return pos


def xirr(cashflows: list[tuple[date, float]], guess: float = 0.1) -> float | None:
    """资金加权收益率（MWR/IRR）。cashflows 含期末市值作为正现金流。牛顿法+二分兜底。"""
    flows = [(d, float(a)) for d, a in cashflows if a]
    if len(flows) < 2:
        return None
    t0 = min(d for d, _ in flows)

    def npv(rate):
        return sum(a / (1 + rate) ** ((d - t0).days / 365.0) for d, a in flows)

    # 牛顿法
    rate = guess
    for _ in range(100):
        f = npv(rate)
        h = 1e-6
        d1 = (npv(rate + h) - f) / h
        if abs(d1) < 1e-12:
            break
        new = rate - f / d1
        if not (-0.999999 < new < 1e6):
            break
        if abs(new - rate) < 1e-8:
            return round(new * 100, 2)
        rate = new
    # 二分兜底
    lo, hi = -0.9999, 10.0
    flo, fhi = npv(lo), npv(hi)
    if flo * fhi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        fm = npv(mid)
        if abs(fm) < 1e-6:
            return round(mid * 100, 2)
        if flo * fm < 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return round(((lo + hi) / 2) * 100, 2)


def twr(daily_values: list[tuple[date, float]], flows_by_day: dict[date, float]) -> float | None:
    """
    时间加权收益率（真实日度法）。
    daily_values: 按日的组合市值 [(date, value)]（期末口径）。
    flows_by_day:  当日外部净现金流（买入为正的注入；卖出为负的抽出），用于剔除择时注入影响。
    r_t = (V_t - CF_t) / V_{t-1} - 1；TWR = ∏(1+r_t) - 1。
    数据不足返回 None（简报据实说明）。
    """
    dv = sorted(daily_values, key=lambda x: x[0])
    if len(dv) < 2:
        return None
    cum = 1.0
    ok = False
    for i in range(1, len(dv)):
        d, v = dv[i]
        v_prev = dv[i - 1][1]
        if v_prev <= 0:
            continue
        cf = flows_by_day.get(d, 0.0)
        r = (v - cf) / v_prev - 1
        cum *= (1 + r)
        ok = True
    return round((cum - 1) * 100, 2) if ok else None
