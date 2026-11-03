// 纪律校验（Python discipline.py 的前端镜像）。
// 用于交易录入时的即时提示；盘后由 Python 引擎以权威身份重算并写回数据库。

export function resolveAnchor(rule, position, highs) {
  if (!rule) return position.avgCost
  const mode = rule.anchor_mode || 'cost'
  if (mode === 'manual') return rule.anchor_price
  if (mode === 'recent_high' && highs && highs.length) return Math.max(...highs)
  return position.avgCost
}

export function evaluateTrade(trade, ctx) {
  const inst = ctx.instrument
  const flags = []
  const add = (code, level, msg) => flags.push({ code, level, msg })
  const side = trade.side
  const tag = trade.action_tag
  const price = Number(trade.price)
  const shares = Number(trade.shares)
  const amount = price * shares + Number(trade.fee || 0)
  const pos = ctx.position || {}
  const held = Number(pos.shares || 0)

  if (tag === 'emotional') add('self_tagged_emotional', 'block', '本人已标记为情绪化提前操作')

  if (side === 'buy') {
    if (inst.blacklist) add('blacklist_add', 'block', `${inst.name} 为黑名单标的，永久禁止加仓，仅可止盈减仓`)
    if ((inst.frameworks || []).includes('munger') && !inst.in_circle)
      add('out_of_circle', 'warn', '标的不在能力圈内，芒格框架提示谨慎')

    const tiers = ctx.tiers || []
    const rule = ctx.graham_rule
    if (held <= 1e-9) {
      add('initial_build', 'info', '首次建仓，不触发梯度档位校验')
    } else {
      const anchor = ctx.anchor_price
      const cur = ctx.current_price || price
      const drawdown = anchor && anchor > 0 ? ((anchor - cur) / anchor) * 100 : 0
      const reached = tiers.filter((t) => drawdown >= Number(t.drawdown_pct))
      if (!reached.length) {
        const tier1 = tiers.length ? tiers[0].drawdown_pct : null
        add('below_tier', 'block', tier1 != null
          ? `当前回撤 ${drawdown.toFixed(1)}% 未达首档 ${tier1}%，属情绪化提前加仓`
          : `未设置加仓档位，回撤 ${drawdown.toFixed(1)}% 的加仓缺少依据`)
      } else {
        const top = reached[reached.length - 1]
        const allow = Number(top.add_amount)
        if (amount > allow * 1.05)
          add('over_tier_amount', 'block', `已达第${top.tier_index}档(回撤≥${top.drawdown_pct}%)，允许约 ${allow}，本次 ${amount.toFixed(0)} 超额`)
        else
          add('tier_ok', 'info', `命中第${top.tier_index}档(回撤≥${top.drawdown_pct}%)，金额在允许范围`)
      }
      if (rule && rule.cooldown_days && ctx.last_buy_time) {
        const gap = Math.floor((new Date(trade.trade_time) - new Date(ctx.last_buy_time)) / 86400000)
        if (gap < Number(rule.cooldown_days))
          add('cooldown', 'block', `距上次加仓仅 ${gap} 天，未过冷却期 ${rule.cooldown_days} 天`)
      }
      if (rule && rule.max_capital != null) {
        const after = Number(pos.investedPrincipal || 0) + amount
        if (after > Number(rule.max_capital))
          add('over_max_capital', 'block', `加仓后投入 ${after.toFixed(0)} 超单标的上限 ${Number(rule.max_capital).toFixed(0)}`)
      }
    }
  } else if (side === 'sell') {
    const tp = ctx.tp_rule
    const avg = Number(pos.avgCost || 0)
    const ret = avg ? ((price - avg) / avg) * 100 : null
    let hit = false
    if (tp) {
      if (tp.target_price && price >= Number(tp.target_price)) hit = true
      if (tp.target_return_pct && ret != null && ret >= Number(tp.target_return_pct)) hit = true
      for (const b of tp.batches || []) if (ret != null && ret >= Number(b.trigger_return)) hit = true
    }
    if (tag === 'planned_tp' && !hit)
      add('early_sell', 'block', `标记为计划内止盈，但收益率 ${ret != null ? ret.toFixed(1) + '%' : '未知'} 未达任何止盈触发条件`)
    else if (hit) add('tp_ok', 'info', '达到预设止盈触发条件')
    else if (tag === 'strategy') add('sell_no_rule', 'warn', '卖出未匹配止盈规则，请确认是否偏离计划')
  }

  const ok = !flags.some((f) => f.level === 'block')
  const reason = flags.map((f) => f.msg).join('；') || '无异常'
  return { ok, flags, reason, checked_by: 'frontend' }
}
