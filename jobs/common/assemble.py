"""
组装层：刷新外部数据 → 权威重算纪律 → 计算绩效 → 拼装发给 LLM 的 user 消息。
被 premarket/intraday/postmarket 三个脚本共用。
"""
from __future__ import annotations
import json
from datetime import date
from dateutil import parser as dtparser

from . import db, datasource, finance, discipline


# ---------------- 1. 刷新外部数据 ----------------

def refresh_market_data(cfg: dict, d: date) -> dict:
    """抓取并 upsert 行情/估值/宏观/基准/新闻。返回快照（内存版，供拼装）。"""
    snap = {"quotes": {}, "macro": {}, "benchmarks": {}, "news": []}

    # 指数估值缓存（按 benchmark_index 去重，避免重复抓）
    val_cache: dict[str, dict | None] = {}
    for inst in cfg["instruments"]:
        iid, code = inst["id"], inst["code"]
        q = datasource.etf_quote(code) or {}
        bidx = inst.get("benchmark_index")
        val = None
        if bidx:
            if bidx not in val_cache:
                val_cache[bidx] = datasource.index_valuation(bidx)
            val = val_cache[bidx] or {}
        row = {
            "instrument_id": iid, "date": str(d),
            "close": q.get("close"), "nav": q.get("nav"),
            "pe": (val or {}).get("pe"), "pb": (val or {}).get("pb"),
            "dividend_yield": (val or {}).get("dividend_yield"),
            "valuation_percentile": (val or {}).get("valuation_percentile"),
            "source": "akshare",
        }
        db.upsert_quote(row)
        snap["quotes"][iid] = row

    # 宏观
    macro = datasource.macro_snapshot()
    for k, v in macro.items():
        if v is not None:
            db.upsert_macro({"date": str(d), "metric": k, "value": v, "source": "akshare/yfinance"})
    snap["macro"] = macro

    # 基准指数
    for code in ("hs300", "hstech", "dividend"):
        iq = datasource.index_quote(code)
        if iq:
            db.upsert_benchmark({"date": str(d), "index_code": code,
                                 "close": iq.get("close"), "pct_change": iq.get("pct_change"),
                                 "source": "yfinance"})
            snap["benchmarks"][code] = iq

    # 新闻（只摘要）
    news = datasource.news_digest()
    codes = {i["code"]: i["name"] for i in cfg["instruments"]}
    rows = []
    for n in news:
        matched = [c for c, nm in codes.items() if nm and nm[:2] in (n.get("title", "") + n.get("summary", ""))]
        rows.append({**n, "date": str(d), "matched": matched})
    if rows:
        db.insert_news(rows)
    snap["news"] = rows
    return snap


# ---------------- 2. 权威重算纪律 ----------------

def recheck_discipline(cfg: dict) -> list[dict]:
    """按时间回放全部流水，用引擎重算 discipline 并写回。返回重算后的 trades。"""
    trades = db.load_trades()
    inst_by_id = {i["id"]: i for i in cfg["instruments"]}
    # 行情历史（供 recent_high 锚点）
    highs = {i["id"]: [float(r["close"]) for r in db.quote_history(i["id"]) if r.get("close")]
             for i in cfg["instruments"]}

    running: dict[str, dict] = {}   # iid -> {shares, avg_cost, invested, last_buy}
    for t in sorted(trades, key=lambda x: x["trade_time"]):
        iid = t["instrument_id"]
        inst = inst_by_id.get(iid)
        if not inst:
            continue
        st = running.setdefault(iid, {"shares": 0.0, "avg_cost": 0.0, "invested": 0.0, "last_buy": None})
        rule = cfg["graham_rules"].get(iid)
        ctx = {
            "instrument": inst,
            "graham_rule": rule,
            "tiers": cfg["tiers"].get(iid, []),
            "tp_rule": cfg["take_profit"].get(iid),
            "position": {"shares": st["shares"], "avg_cost": st["avg_cost"],
                         "invested_principal": st["invested"]},
            "last_buy_time": st["last_buy"],
            "anchor_price": discipline.resolve_anchor(
                rule, {"avg_cost": st["avg_cost"]}, highs.get(iid)),
            "current_price": float(t["price"]),
        }
        result = evaluate_and_store(t, ctx)
        t["discipline"] = result

        # 更新 running 状态（均价法，简化版，仅为上下文）
        price, shares = float(t["price"]), float(t["shares"])
        fee = float(t.get("fee") or 0)
        fx = float(t.get("fx_rate") or 1)
        if t["side"] == "buy":
            cost = price * shares + fee
            total = st["avg_cost"] * st["shares"] + cost
            st["shares"] += shares
            st["avg_cost"] = total / st["shares"] if st["shares"] else 0
            st["invested"] += cost * fx
            st["last_buy"] = t["trade_time"]
        elif t["side"] == "sell":
            st["invested"] -= (price * shares - fee) * fx
            st["shares"] -= shares
            if st["shares"] <= 1e-9:
                st["shares"], st["avg_cost"] = 0.0, 0.0
    return trades


def evaluate_and_store(trade: dict, ctx: dict) -> dict:
    result = discipline.evaluate_trade(trade, ctx)
    prev = trade.get("discipline") or {}
    if prev.get("ok") != result["ok"] or prev.get("checked_by") != "engine":
        db.update_trade_discipline(trade["id"], result)
    return result


# ---------------- 3. 绩效 ----------------

def _fx_now(macro: dict, inst: dict) -> float:
    if inst.get("currency") == "HKD":
        return float(macro.get("hkdcnh") or 0) or 1.0
    return 1.0


def compute_performance(cfg: dict, trades: list[dict], d: date) -> dict:
    inst_by_id = {i["id"]: i for i in cfg["instruments"]}
    quotes = db.latest_quotes()
    macro = {k: v.get("value") for k, v in db.latest_macro().items()}
    positions = finance.build_positions(trades, inst_by_id)

    per = []
    all_cashflows: list = []
    tot = {"principal": 0.0, "realized": 0.0, "market_value": 0.0, "unrealized": 0.0}
    for iid, p in positions.items():
        inst = inst_by_id.get(iid, {})
        last_close = quotes.get(iid, {}).get("close")
        last_close = float(last_close) if last_close is not None else None
        fx = _fx_now(macro, inst)
        pd = p.to_dict(last_close, fx, float(inst.get("dividend_tax_rate") or 0))
        pd["code"] = inst.get("code")
        pd["name"] = inst.get("name")
        per.append(pd)
        all_cashflows.extend(p.cashflows)
        tot["principal"] += pd["invested_principal"] or 0
        tot["realized"] += pd["realized_total"] or 0
        if pd["market_value"]:
            tot["market_value"] += pd["market_value"]
        if pd["unrealized"]:
            tot["unrealized"] += pd["unrealized"]

    # XIRR：全部现金流 + 期末总市值作为正向现金流
    xirr_flows = list(all_cashflows)
    if tot["market_value"]:
        xirr_flows.append((d, tot["market_value"]))
    mwr = finance.xirr(xirr_flows)

    # TWR：best-effort（历史市值序列不足时为 None）
    tw = _twr_best_effort(trades, inst_by_id, macro)

    exec_rate = db.execution_rate()
    return {
        "totals": {k: round(v, 2) for k, v in tot.items()},
        "per_instrument": per,
        "mwr_xirr_pct": mwr,
        "twr_pct": tw,
        "execution": exec_rate,
    }


def _twr_best_effort(trades, inst_by_id, macro) -> float | None:
    """用已缓存的日度收盘重建组合日市值 + 当日外部净注入，算真实日度 TWR。"""
    if not trades:
        return None
    # 每标的日度收盘
    closes: dict[str, dict] = {}
    for iid in {t["instrument_id"] for t in trades}:
        closes[iid] = {r["date"]: float(r["close"]) for r in db.quote_history(iid) if r.get("close")}
    all_dates = sorted({dd for m in closes.values() for dd in m})
    if len(all_dates) < 2:
        return None

    daily_values, flows_by_day = [], {}
    strades = sorted(trades, key=lambda x: x["trade_time"])
    for dd in all_dates:
        holdings: dict[str, float] = {}
        inj = 0.0
        for t in strades:
            td = dtparser.parse(t["trade_time"]).date()
            if str(td) > dd:
                continue
            iid = t["instrument_id"]
            sh = float(t["shares"])
            fx = float(t.get("fx_rate") or 1)
            if t["side"] == "buy":
                holdings[iid] = holdings.get(iid, 0) + sh
            elif t["side"] == "sell":
                holdings[iid] = holdings.get(iid, 0) - sh
            if str(td) == dd:
                if t["side"] == "buy":
                    inj += (float(t["price"]) * sh + float(t.get("fee") or 0)) * fx
                elif t["side"] == "sell":
                    inj -= (float(t["price"]) * sh - float(t.get("fee") or 0)) * fx
        v = 0.0
        for iid, sh in holdings.items():
            c = closes.get(iid, {}).get(dd)
            if c is None:
                continue
            fx = _fx_now(macro, inst_by_id.get(iid, {}))
            v += sh * c * fx
        from datetime import date as _date
        daily_values.append((_date.fromisoformat(dd), v))
        if inj:
            flows_by_day[_date.fromisoformat(dd)] = inj
    return finance.twr(daily_values, flows_by_day)


# ---------------- 4. 距档位 / 距止盈 ----------------

def tier_gaps(cfg: dict) -> list[dict]:
    quotes = db.latest_quotes()
    out = []
    for inst in cfg["instruments"]:
        iid = inst["id"]
        q = quotes.get(iid, {})
        cur = q.get("close")
        rule = cfg["graham_rules"].get(iid)
        tiers = cfg["tiers"].get(iid, [])
        tp = cfg["take_profit"].get(iid)
        info = {"code": inst["code"], "name": inst["name"], "current": cur,
                "blacklist": inst.get("blacklist", False)}
        if cur and rule:
            # 锚点用近高（无持仓上下文时的参考）
            highs = [float(r["close"]) for r in db.quote_history(iid) if r.get("close")]
            anchor = discipline.resolve_anchor(rule, {"avg_cost": cur}, highs) or cur
            dd = round((anchor - float(cur)) / anchor * 100, 2) if anchor else None
            info["anchor"] = anchor
            info["drawdown_pct"] = dd
            nxt = next((t for t in tiers if dd is not None and dd < float(t["drawdown_pct"])), None)
            if nxt:
                info["next_tier"] = {"tier": nxt["tier_index"], "need_drawdown_pct": nxt["drawdown_pct"],
                                     "add_amount": nxt["add_amount"],
                                     "gap_pct": round(float(nxt["drawdown_pct"]) - dd, 2) if dd is not None else None}
        if cur and tp and tp.get("target_price"):
            info["to_take_profit_price"] = round(float(tp["target_price"]) - float(cur), 4)
        out.append(info)
    return out


# ---------------- 5. 拼装 user 消息 ----------------

def build_user_message(btype: str, cfg: dict, d: date,
                       snap: dict | None, perf: dict | None,
                       trades: list[dict] | None) -> str:
    macro = {k: v.get("value") for k, v in db.latest_macro().items()}
    news = [{"title": n["title"], "summary": n.get("summary"), "matched": n.get("matched")}
            for n in db.recent_news(d)]
    quotes = db.latest_quotes()

    inst_by_id = {i["id"]: i for i in cfg["instruments"]}
    positions = finance.build_positions(db.load_trades(), inst_by_id)
    inst_view = []
    for i in cfg["instruments"]:
        q = quotes.get(i["id"], {})
        p = positions.get(i["id"])
        held = bool(p and p.shares > 1e-9)
        inst_view.append({
            "code": i["code"], "name": i["name"], "currency": i["currency"], "channel": i["channel"],
            "group": "持仓" if held else "跟踪",            # 持仓 vs 跟踪清单
            "shares": round(p.shares, 2) if p else 0,
            "avg_cost": round(p.avg_cost, 4) if p else None,
            "in_circle": i["in_circle"], "blacklist": i["blacklist"],
            "frameworks": i["frameworks"], "benchmark_index": i.get("benchmark_index"),
            "close": q.get("close"), "pe": q.get("pe"), "pb": q.get("pb"),
            "dividend_yield": q.get("dividend_yield"),
            "valuation_percentile": q.get("valuation_percentile"),
        })

    payload = {
        "date": str(d),
        "briefing_type": btype,
        "macro": macro,
        "instruments": inst_view,
        "tier_gaps": tier_gaps(cfg),
        "reserve": {"total": cfg["reserve"].get("total_reserve"), "allocations": cfg["allocations"]},
        "news": news,
    }
    if perf:
        payload["performance"] = perf
    if trades is not None and btype == "post":
        today = str(d)
        payload["today_trades"] = [
            {"time": t["trade_time"], "instrument": t["instrument_id"], "side": t["side"],
             "shares": t["shares"], "price": t["price"], "action_tag": t["action_tag"],
             "discipline": t.get("discipline")}
            for t in trades if str(dtparser.parse(t["trade_time"]).date()) == today
        ]
        payload["violations"] = [
            {"time": t["trade_time"], "side": t["side"], "price": t["price"],
             "reason": (t.get("discipline") or {}).get("reason")}
            for t in trades if (t.get("discipline") or {}).get("ok") is False
        ]

    guide = {
        "pre": "请据此生成【盘前简报】。缺失字段如实标注数据缺失。",
        "intra": "请据此生成【盘中快照简报】，一次性，不预测。",
        "post": "请据此生成【盘后完整复盘（六维）】。严格区分已兑现与账面浮动盈亏。",
        "daily": "请据此生成【每日研判条】：置顶、简短；宏观定性+估值温度+高久期风险+按我的规则今日触发。只复述规则、不新增建议、不预测、不搬外部荐股。",
    }[btype]

    return (
        f"{guide}\n\n以下为结构化输入数据（JSON），请只基于这些数据生成简报，"
        f"不得编造、不得预测、操作预案只复述规则：\n\n```json\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}\n```"
    )
