<script setup>
import { computed } from 'vue'
import { store } from '../store'
import { fmtNum, fmtPct } from '../lib/format'

const macroRows = computed(() => {
  const m = store.macro
  const def = [
    ['us10y', '10年期美债收益率', '%'],
    ['dxy', '美元指数', ''],
    ['southbound_net', '南向资金净流入', '亿'],
    ['dr007', 'DR007 / 7天Shibor', '%'],
    ['usdcnh', '美元兑人民币', ''],
    ['hkdcnh', '港币兑人民币', ''],
  ]
  return def.map(([k, label, unit]) => ({ label, unit, value: m[k]?.value, date: m[k]?.date }))
})
const valQuality = (p) => (p == null ? '' : p <= 30 ? 'up' : p >= 70 ? 'down' : 'warn')
</script>

<template>
  <h2>自动数据看板</h2>
  <p class="muted" style="font-size:12px">定时任务抓取的公开数据缓存，页面只读、不消耗任何 LLM token。</p>

  <div class="card">
    <h3>标的估值（对应指数）</h3>
    <div class="scroll-x">
      <table>
        <thead><tr><th>标的</th><th>现价</th><th>PE</th><th>PB</th><th>股息率</th><th>估值分位</th></tr></thead>
        <tbody>
          <tr v-for="i in store.instruments" :key="i.id">
            <td>{{ i.name }}</td>
            <td class="mono">{{ fmtNum(store.quotes[i.id]?.close, 3) }}</td>
            <td class="mono">{{ fmtNum(store.quotes[i.id]?.pe, 2) }}</td>
            <td class="mono">{{ fmtNum(store.quotes[i.id]?.pb, 2) }}</td>
            <td class="mono">{{ fmtPct(store.quotes[i.id]?.dividend_yield) }}</td>
            <td class="mono" :class="valQuality(store.quotes[i.id]?.valuation_percentile)">{{ fmtPct(store.quotes[i.id]?.valuation_percentile, 1) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="muted" style="font-size:11px">估值分位：越低越接近安全边际区间（绿），越高越接近高估区间（红）。仅供芒格框架定性，不预测涨跌。</p>
  </div>

  <div class="card">
    <h3>宏观（达利欧框架输入）</h3>
    <div v-for="r in macroRows" :key="r.label" class="spread list-item">
      <span class="muted">{{ r.label }}</span>
      <b class="mono">{{ r.value != null ? fmtNum(r.value, 2) + r.unit : '数据缺失' }}</b>
    </div>
  </div>

  <div class="card">
    <h3>基准指数</h3>
    <table>
      <thead><tr><th>指数</th><th>收盘</th><th>涨跌</th><th>日期</th></tr></thead>
      <tbody>
        <tr v-for="b in store.benchmarks" :key="b.index_code + b.date">
          <td>{{ b.index_code }}</td><td class="mono">{{ fmtNum(b.close, 2) }}</td>
          <td class="mono" :class="b.pct_change > 0 ? 'up' : b.pct_change < 0 ? 'down' : ''">{{ fmtPct(b.pct_change) }}</td>
          <td class="muted">{{ b.date }}</td>
        </tr>
      </tbody>
    </table>
  </div>

  <div class="card">
    <h3>财经新闻摘要</h3>
    <div v-for="n in store.news" :key="n.id" class="list-item">
      <b style="font-size:13px">{{ n.title }}</b>
      <span v-for="c in (n.matched || [])" :key="c" class="badge accent" style="margin-left:4px">{{ c }}</span>
      <div class="muted" style="font-size:12px">{{ n.summary }}</div>
      <div class="muted" style="font-size:11px">{{ n.date }} · {{ n.source }}</div>
    </div>
    <p v-if="!store.news.length" class="muted">暂无新闻缓存。</p>
  </div>
</template>
