"""
离线端到端 dry-run：不连 Supabase，用内存配置 + 真实行情，把
[拉数据 → 纪律引擎 → 绩效 → 组装 DeepSeek Prompt] 整条链路跑一遍。
若设置了 DEEPSEEK_API_KEY 环境变量，还会真的调用 DeepSeek 生成盘后简报。

用法： PYTHONUTF8=1 python -m jobs.dryrun
"""
from __future__ import annotations
import json, os
from datetime import date, datetime, timedelta
from dateutil import parser as dtparser

from jobs.common import datasource as ds
from jobs.common import discipline, finance, prompts

# ---------------- 内存配置（等价于 seed.sql） ----------------
INST = [
    {"id": "i1", "code": "510300.SH", "name": "沪深300ETF", "currency": "CNY", "channel": "a_etf",
     "frameworks": ["munger", "dalio", "graham"], "in_circle": True, "blacklist": False,
     "dividend_tax_rate": 0, "benchmark_index": "hs300"},
    {"id": "i2", "code": "513180.SH", "name": "恒生科技ETF", "currency": "CNY", "channel": "qdii",
     "frameworks": ["munger", "dalio", "graham"], "in_circle": True, "blacklist": False,
     "dividend_tax_rate": 0, "benchmark_index": "hstech"},
    {"id": "i3", "code": "510880.SH", "name": "红利ETF", "currency": "CNY", "channel": "a_etf",
     "frameworks": ["munger", "graham"], "in_circle": True, "blacklist": False,
     "dividend_tax_rate": 0, "benchmark_index": "dividend"},
    {"id": "i4", "code": "512660.SH", "name": "军工ETF", "currency": "CNY", "channel": "a_etf",
     "frameworks": ["graham"], "in_circle": False, "blacklist": True,
     "dividend_tax_rate": 0, "benchmark_index": None},
]
INST_BY_ID = {i["id"]: i for i in INST}
GRAHAM_RULES = {
    "i1": {"max_capital": 100000, "cooldown_days": 5, "anchor_mode": "cost", "anchor_price": None, "recent_high_lookback": 60},
    "i2": {"max_capital": 60000, "cooldown_days": 7, "anchor_mode": "cost", "anchor_price": None, "recent_high_lookback": 60},
}
TIERS = {
    "i1": [{"tier_index": 1, "drawdown_pct": 5, "add_amount": 10000},
           {"tier_index": 2, "drawdown_pct": 10, "add_amount": 15000}],
    "i2": [{"tier_index": 1, "drawdown_pct": 8, "add_amount": 8000}],
}
TP = {"i1": {"target_price": None, "target_return_pct": 30,
             "batches": [{"trigger_return": 20, "sell_ratio": 0.25}]}}
RESERVE = {"total_reserve": 150000}
ALLOC = {"i1": 45000, "i2": 35000}

# ---------------- 内存流水（含两笔故意违规，演示校验） ----------------
def iso(d):
    return d.isoformat()

TODAY = date.today()
TRADES = [
    {"id": "t1", "trade_time": iso(datetime.now() - timedelta(days=40)), "instrument_id": "i1",
     "side": "buy", "shares": 10000, "price": 4.20, "fee": 5, "fx_rate": 1, "dividend_cash": 0,
     "dividend_reinvest": False, "action_tag": "strategy"},                    # 建仓，合规
    {"id": "t2", "trade_time": iso(datetime.now() - timedelta(days=2)), "instrument_id": "i1",
     "side": "buy", "shares": 10000, "price": 4.10, "fee": 5, "fx_rate": 1, "dividend_cash": 0,
     "dividend_reinvest": False, "action_tag": "strategy"},                    # 回撤仅2.4%未到5%档 → 违规
    {"id": "t3", "trade_time": iso(datetime.now() - timedelta(days=1)), "instrument_id": "i4",
     "side": "buy", "shares": 5000, "price": 1.00, "fee": 2, "fx_rate": 1, "dividend_cash": 0,
     "dividend_reinvest": False, "action_tag": "strategy"},                    # 军工黑名单加仓 → 违规
    {"id": "t4", "trade_time": iso(datetime.now() - timedelta(hours=3)), "instrument_id": "i1",
     "side": "sell", "shares": 5000, "price": 5.50, "fee": 5, "fx_rate": 1, "dividend_cash": 0,
     "dividend_reinvest": False, "action_tag": "planned_tp"},                  # 收益~32% 达止盈 → 合规
]


def run():
    print("==== 1. 拉真实行情 ====")
    quotes = {}
    for i in INST:
        q = ds.etf_quote(i["code"]) or {}
        val = ds.index_valuation(i["benchmark_index"]) if i["benchmark_index"] else None
        quotes[i["id"]] = {**q, **(val or {})}
        print(f"  {i['name']:10s} 收盘={q.get('close')}  PE={(val or {}).get('pe')}  "
              f"股息率={(val or {}).get('dividend_yield')}  估值分位={(val or {}).get('valuation_percentile')}")
    macro = ds.macro_snapshot()
    print("  宏观:", macro)
    news = ds.news_digest(5)
    print(f"  新闻: {len(news)} 条")

    print("\n==== 2. 纪律引擎逐笔校验（权威） ====")
    running = {}
    checked = []
    for t in sorted(TRADES, key=lambda x: x["trade_time"]):
        iid = t["instrument_id"]
        st = running.setdefault(iid, {"shares": 0.0, "avg_cost": 0.0, "invested": 0.0, "last_buy": None})
        rule = GRAHAM_RULES.get(iid)
        ctx = {
            "instrument": INST_BY_ID[iid], "graham_rule": rule, "tiers": TIERS.get(iid, []),
            "tp_rule": TP.get(iid),
            "position": {"shares": st["shares"], "avg_cost": st["avg_cost"], "invested_principal": st["invested"]},
            "last_buy_time": st["last_buy"],
            "anchor_price": discipline.resolve_anchor(rule, {"avg_cost": st["avg_cost"]}, None),
            "current_price": t["price"],
        }
        res = discipline.evaluate_trade(t, ctx)
        t["discipline"] = res
        checked.append(t)
        tag = "✅合规" if res["ok"] else "❌违规"
        print(f"  {INST_BY_ID[iid]['name']:10s} {t['side']:4s} {t['shares']:>6}@{t['price']}  {tag}: {res['reason']}")
        # 更新运行态
        price, shares, fee = t["price"], t["shares"], t.get("fee", 0)
        if t["side"] == "buy":
            cost = price * shares + fee
            total = st["avg_cost"] * st["shares"] + cost
            st["shares"] += shares
            st["avg_cost"] = total / st["shares"]
            st["invested"] += cost
            st["last_buy"] = t["trade_time"]
        else:
            st["invested"] -= price * shares - fee
            st["shares"] -= shares
            if st["shares"] <= 1e-9:
                st["shares"] = st["avg_cost"] = 0.0

    buys = [t for t in checked if t["side"] == "buy"]
    ok_buys = [t for t in buys if t["discipline"]["ok"]]
    exec_rate = round(100 * len(ok_buys) / len(buys), 1) if buys else None
    print(f"  → 策略执行率: {exec_rate}%  （买入{len(buys)}笔，违规{len(buys)-len(ok_buys)}笔）")

    print("\n==== 3. 绩效（已兑现 vs 账面浮动 隔离） ====")
    pos = finance.build_positions(checked, INST_BY_ID)
    all_cf = []
    tot = {"principal": 0.0, "realized": 0.0, "mv": 0.0, "unreal": 0.0}
    for iid, p in pos.items():
        close = quotes.get(iid, {}).get("close")
        v = p.to_dict(float(close) if close else None, 1.0, 0)
        all_cf.extend(p.cashflows)
        tot["principal"] += v["invested_principal"] or 0
        tot["realized"] += v["realized_total"] or 0
        if v["market_value"]:
            tot["mv"] += v["market_value"]
        if v["unrealized"]:
            tot["unreal"] += v["unrealized"]
        if p.shares or v["realized_total"]:
            print(f"  {INST_BY_ID[iid]['name']:10s} 持仓{v['shares']:>6}  浮动={v['unrealized']}  已兑现={v['realized_total']}")
    if tot["mv"]:
        all_cf.append((TODAY, tot["mv"]))
    mwr = finance.xirr(all_cf)
    print(f"  → 累计已兑现(确定落袋)={round(tot['realized'],2)}  账面浮动(会消失)={round(tot['unreal'],2)}  MWR={mwr}%")

    print("\n==== 4. 组装发给 DeepSeek 的 Prompt ====")
    payload = {
        "date": str(TODAY), "briefing_type": "post", "macro": macro,
        "instruments": [{"name": i["name"], "code": i["code"], "in_circle": i["in_circle"],
                         "blacklist": i["blacklist"], **{k: quotes[i["id"]].get(k) for k in ("close", "pe", "dividend_yield", "valuation_percentile")}}
                        for i in INST],
        "reserve": {"total": RESERVE["total_reserve"], "allocations": ALLOC},
        "performance": {"totals": {k: round(v, 2) for k, v in tot.items()}, "mwr_xirr_pct": mwr,
                        "execution_rate_pct": exec_rate},
        "violations": [{"name": INST_BY_ID[t["instrument_id"]]["name"], "reason": t["discipline"]["reason"]}
                       for t in checked if not t["discipline"]["ok"]],
        "news": [{"title": n["title"]} for n in news[:5]],
    }
    system = prompts.system_for("post")
    user = ("请基于以下真实数据生成【盘后完整复盘（六维）】，严格区分已兑现与账面浮动，"
            "不预测、不荐股，操作预案只复述规则：\n\n```json\n"
            + json.dumps(payload, ensure_ascii=False, indent=2) + "\n```")
    print(f"  system 长度 {len(system)} 字符（稳定前缀，吃 DeepSeek 缓存）")
    print(f"  user   长度 {len(user)} 字符")

    key = os.getenv("DEEPSEEK_API_KEY")
    if key:
        print("\n==== 5. 调用 DeepSeek 生成简报 ====")
        from jobs.common import llm
        text, usage = llm.generate(system, user)
        print(text)
        print("\nusage:", usage)
    else:
        print("\n（未设 DEEPSEEK_API_KEY，跳过真实生成。设置后本脚本会打印完整盘后简报。）")
        print("\n----- 将发送的 user 消息预览（前 1200 字）-----")
        print(user[:1200])
    print("\n==== DRY-RUN DONE ====")


if __name__ == "__main__":
    run()
