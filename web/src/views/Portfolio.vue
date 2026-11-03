<script setup>
import { computed } from 'vue'
import { store, instById } from '../store'
import { buildPositions, positionView, xirr } from '../lib/finance'
import { fmtMoney, fmtPct, fmtNum, pnlClass } from '../lib/format'

const map = computed(() => instById())
const fxNow = (inst) => (inst?.currency === 'HKD' ? Number(store.macro.hkdcnh?.value || 0) || 1 : 1)

const positions = computed(() => buildPositions(store.trades, map.value))

const rows = computed(() =>
  Object.values(positions.value).map((p) => {
    const inst = map.value[p.instrument_id] || {}
    const close = store.quotes[p.instrument_id]?.close
    const v = positionView(p, close != null ? Number(close) : null, fxNow(inst))
    return { inst, ...v }
  }).filter((r) => r.inst.id)
)

const totals = computed(() => {
  const t = { principal: 0, realized: 0, mv: 0, unreal: 0 }
  for (const r of rows.value) {
    t.principal += r.investedPrincipal || 0
    t.realized += r.realizedTotal || 0
    if (r.marketValue != null) t.mv += r.marketValue
    if (r.unrealized != null) t.unreal += r.unrealized
  }
  t.unrealPct = t.mv - t.unreal ? (t.unreal / (t.mv - t.unreal)) * 100 : null
  return t
})

const mwr = computed(() => {
  const cf = []
  for (const p of Object.values(positions.value)) cf.push(...p.cashflows)
  if (totals.value.mv) cf.push([new Date(), totals.value.mv])
  return xirr(cf)
})

const exec = computed(() => store.execRate || {})
const reserveTotal = computed(() => Number(store.reserve?.total_reserve || 0))
const allocSum = computed(() => Object.values(store.allocations).reduce((s, v) => s + Number(v || 0), 0))
</script>

<template>
  <h2>持仓台账 & 绩效看板</h2>

  <!-- 两类盈亏强制隔离 -->
  <div class="grid2">
    <div class="block-realized">
      <div class="label up">● 累计已兑现收益</div>
      <div class="big mono" :class="pnlClass(totals.realized)">{{ fmtMoney(totals.realized) }}</div>
      <div class="muted" style="font-size:11px">卖出差价 + 税后分红(+汇兑)。确定落袋，不受后续行情影响。</div>
    </div>
    <div class="block-float">
      <div class="label warn">◌ 当前账面浮动盈亏</div>
      <div class="big mono" :class="pnlClass(totals.unreal)">{{ fmtMoney(totals.unreal) }}</div>
      <div class="warn" style="font-size:11px">仅账面 {{ fmtPct(totals.unrealPct) }}，行情反转会消失，不能作为操作依据。</div>
    </div>
  </div>

  <div class="card">
    <div class="grid2">
      <div class="kpi"><div class="v mono">{{ fmtMoney(totals.principal, 0) }}</div><div class="k">总投入本金</div></div>
      <div class="kpi"><div class="v mono">{{ fmtMoney(totals.mv, 0) }}</div><div class="k">当前持仓市值</div></div>
      <div class="kpi"><div class="v mono">{{ fmtPct(mwr) }}</div><div class="k">MWR / IRR（资金加权）</div></div>
      <div class="kpi"><div class="v mono">{{ exec.execution_rate_pct != null ? exec.execution_rate_pct + '%' : '—' }}</div><div class="k">策略执行率</div></div>
    </div>
    <p class="muted" style="font-size:11px;margin-top:8px">
      TWR（时间加权）用于区分"策略Beta vs 择时"，在盘后复盘简报中给出；买入 {{ exec.total_buys || 0 }} 笔，其中违规/情绪化 {{ (exec.total_buys || 0) - (exec.ok_buys || 0) }} 笔。
    </p>
  </div>

  <!-- 子弹储备池 -->
  <div class="card">
    <h3>子弹储备池</h3>
    <div class="spread"><span class="muted">总预备资金</span><b class="mono">{{ fmtMoney(reserveTotal, 0) }}</b></div>
    <div class="spread"><span class="muted">已分配额度合计</span><b class="mono">{{ fmtMoney(allocSum, 0) }}</b></div>
    <div class="spread"><span class="muted">未分配</span><b class="mono">{{ fmtMoney(reserveTotal - allocSum, 0) }}</b></div>
    <table style="margin-top:8px">
      <thead><tr><th>标的</th><th>剩余加仓额度</th></tr></thead>
      <tbody>
        <tr v-for="i in store.instruments" :key="i.id">
          <td>{{ i.name }} <span v-if="i.blacklist" class="badge block">禁加仓</span></td>
          <td class="mono">{{ fmtMoney(store.allocations[i.id] || 0, 0) }}</td>
        </tr>
      </tbody>
    </table>
  </div>

  <!-- 分标的独立台账 -->
  <div class="card">
    <h3>分标的独立台账</h3>
    <div class="scroll-x">
      <table>
        <thead>
          <tr><th>标的</th><th>份额</th><th>均价</th><th>投入</th><th>市值</th><th>浮动</th><th>浮动%</th><th>已兑现</th></tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.inst.id">
            <td>{{ r.inst.name }}<br><span class="muted" style="font-size:11px">{{ r.inst.code }}</span></td>
            <td class="mono">{{ fmtNum(r.shares, 0) }}</td>
            <td class="mono">{{ fmtNum(r.avgCost, 3) }}</td>
            <td class="mono">{{ fmtMoney(r.investedPrincipal, 0) }}</td>
            <td class="mono">{{ fmtMoney(r.marketValue, 0) }}</td>
            <td class="mono" :class="pnlClass(r.unrealized)">{{ fmtMoney(r.unrealized, 0) }}</td>
            <td class="mono" :class="pnlClass(r.unrealizedPct)">{{ fmtPct(r.unrealizedPct) }}</td>
            <td class="mono" :class="pnlClass(r.realizedTotal)">{{ fmtMoney(r.realizedTotal, 0) }}</td>
          </tr>
          <tr v-if="!rows.length"><td colspan="8" class="muted">暂无持仓，去"录入"记第一笔流水。</td></tr>
        </tbody>
      </table>
    </div>
    <p class="disclaimer-inline">浮动盈亏仅为账面数字；只有"已兑现"才是确定收益。本看板不构成任何操作建议。</p>
  </div>
</template>
