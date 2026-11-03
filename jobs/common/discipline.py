"""
纪律校验引擎（权威实现，前端 discipline.js 为其镜像）。
把每一笔交易与"基准契约"（策略配置）对比，判定是否违背纪律。

规则固化，LLM 不参与判定——LLM 只复述本引擎的结论。

flags 语义：ok=False 的都是"违反纪律"，计入执行率扣减；warn 仅提示。
"""
from __future__ import annotations
from datetime import datetime
from dateutil import parser as dtparser


def evaluate_trade(trade: dict, ctx: dict) -> dict:
    """
    trade: 一笔流水（含 side/shares/price/fee/action_tag/trade_time）
    ctx:
      instrument   : 标的配置（blacklist/in_circle/channel...）
      graham_rule  : 该标的 graham_rules 行（或 None）
      tiers        : 按 tier_index 升序的档位列表
      tp_rule      : take_profit_rules 行（或 None）
      position     : {shares, avg_cost, invested_principal}（本笔之前的状态）
      last_buy_time: 上一次买入时间（ISO 字符串或 None）
      anchor_price : 回撤基准价（已按 anchor_mode 解析好）
      current_price: 本笔成交价
    返回 {ok, flags:[{code,level,msg}], reason, checked_by:'engine'}
    """
    inst = ctx["instrument"]
    flags: list[dict] = []
    side = trade["side"]
    tag = trade.get("action_tag")
    price = float(trade["price"])
    shares = float(trade["shares"])
    amount = price * shares + float(trade.get("fee") or 0)
    pos = ctx.get("position") or {}
    held = float(pos.get("shares") or 0)

    def add(code, level, msg):
        flags.append({"code": code, "level": level, "msg": msg})

    # 自报情绪化：直接判违规
    if tag == "emotional":
        add("self_tagged_emotional", "block", "本人已标记为情绪化提前操作")

    if side == "buy":
        # 1) 黑名单永久禁止加仓
        if inst.get("blacklist"):
            add("blacklist_add", "block", f"{inst['name']} 为黑名单标的，永久禁止加仓，仅可止盈减仓")

        # 2) 能力圈（芒格框架）
        if "munger" in (inst.get("frameworks") or []) and not inst.get("in_circle"):
            add("out_of_circle", "warn", "标的不在你标记的能力圈内，芒格框架提示谨慎")

        # 3) 格雷厄姆梯度：建仓 vs 加仓
        tiers = ctx.get("tiers") or []
        rule = ctx.get("graham_rule")
        if held <= 1e-9:
            add("initial_build", "info", "首次建仓，不触发梯度档位校验")
        else:
            anchor = ctx.get("anchor_price")
            cur = ctx.get("current_price") or price
            if anchor and anchor > 0:
                drawdown = (anchor - cur) / anchor * 100
            else:
                drawdown = 0.0
            reached = [t for t in tiers if drawdown >= float(t["drawdown_pct"])]
            if not reached:
                tier1 = tiers[0]["drawdown_pct"] if tiers else None
                add("below_tier", "block",
                    f"当前回撤 {drawdown:.1f}% 未达首档 {tier1}%，属情绪化提前加仓" if tier1 is not None
                    else f"未设置加仓档位，当前回撤 {drawdown:.1f}% 的加仓缺少依据")
            else:
                top = reached[-1]
                allow = float(top["add_amount"])
                if amount > allow * 1.05:   # 5% 容差
                    add("over_tier_amount", "block",
                        f"已达第{top['tier_index']}档(回撤≥{top['drawdown_pct']}%)，允许加仓约 {allow:.0f}，本次 {amount:.0f} 超额")
                else:
                    add("tier_ok", "info", f"命中第{top['tier_index']}档(回撤≥{top['drawdown_pct']}%)，加仓金额在允许范围")

            # 4) 冷却期
            if rule and rule.get("cooldown_days") and ctx.get("last_buy_time"):
                last = dtparser.parse(ctx["last_buy_time"])
                now = dtparser.parse(trade["trade_time"])
                gap = (now - last).days
                if gap < int(rule["cooldown_days"]):
                    add("cooldown", "block", f"距上次加仓仅 {gap} 天，未过冷却期 {rule['cooldown_days']} 天")

            # 5) 单标的资金上限
            if rule and rule.get("max_capital") is not None:
                after = float(pos.get("invested_principal") or 0) + amount
                if after > float(rule["max_capital"]):
                    add("over_max_capital", "block",
                        f"加仓后投入 {after:.0f} 超单标的上限 {float(rule['max_capital']):.0f}")

    elif side == "sell":
        # 止盈校验
        tp = ctx.get("tp_rule")
        avg = float(pos.get("avg_cost") or 0)
        ret = ((price - avg) / avg * 100) if avg else None
        hit = False
        if tp:
            if tp.get("target_price") and price >= float(tp["target_price"]):
                hit = True
            if tp.get("target_return_pct") and ret is not None and ret >= float(tp["target_return_pct"]):
                hit = True
            for b in (tp.get("batches") or []):
                if ret is not None and ret >= float(b.get("trigger_return", 1e9)):
                    hit = True
        if tag == "planned_tp" and not hit:
            add("early_sell", "block",
                f"标记为计划内止盈，但当前收益率 {('%.1f%%' % ret) if ret is not None else '未知'} 未达任何止盈触发条件")
        elif hit:
            add("tp_ok", "info", "达到预设止盈触发条件")
        elif tag == "strategy":
            add("sell_no_rule", "warn", "卖出未匹配到止盈规则，请确认是否偏离计划")

    ok = not any(f["level"] == "block" for f in flags)
    reason = "；".join(f["msg"] for f in flags) or "无异常"
    return {"ok": ok, "flags": flags, "reason": reason, "checked_by": "engine",
            "checked_at": datetime.utcnow().isoformat()}


def resolve_anchor(rule: dict | None, position: dict, highs: list[float] | None) -> float | None:
    """按 anchor_mode 解析回撤基准价。"""
    if not rule:
        return position.get("avg_cost")
    mode = rule.get("anchor_mode", "cost")
    if mode == "manual":
        return rule.get("anchor_price")
    if mode == "recent_high" and highs:
        return max(highs) if highs else position.get("avg_cost")
    return position.get("avg_cost")
