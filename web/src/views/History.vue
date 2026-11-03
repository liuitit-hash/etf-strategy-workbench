<script setup>
import { ref, computed, onMounted } from 'vue'
import { marked } from 'marked'
import { supabase } from '../supabase'
import { BRIEFING_LABEL, fmtMoney, fmtPct } from '../lib/format'

const dates = ref([])
const date = ref('')
const items = ref([])
const open = ref(null)

async function loadDates() {
  const { data } = await supabase.from('briefings').select('date').order('date', { ascending: false }).limit(400)
  dates.value = [...new Set((data || []).map((d) => d.date))]
  if (dates.value.length && !date.value) { date.value = dates.value[0]; loadDate() }
}
async function loadDate() {
  const { data } = await supabase.from('briefings').select('*').eq('date', date.value).order('type').order('version', { ascending: false })
  // 每类型取最新版
  const seen = new Set(); const out = []
  for (const b of data || []) { if (!seen.has(b.type)) { seen.add(b.type); out.push(b) } }
  items.value = out
}
onMounted(loadDates)

const render = (md) => marked.parse(md || '')
const perf = (b) => b.inputs?.performance || null
</script>

<template>
  <h2>历史回溯</h2>
  <p class="muted" style="font-size:12px">查看任意一天的简报、当时估值数据与校验结论，复盘策略是否失效。</p>

  <div class="card">
    <label>选择日期</label>
    <select v-model="date" @change="loadDate">
      <option v-for="d in dates" :key="d" :value="d">{{ d }}</option>
    </select>
  </div>

  <div v-for="b in items" :key="b.id" class="card">
    <div class="spread" @click="open = open === b.id ? null : b.id" style="cursor:pointer">
      <b>{{ BRIEFING_LABEL[b.type] }}简报</b>
      <span class="muted">{{ open === b.id ? '收起' : '展开' }}</span>
    </div>
    <template v-if="perf(b)">
      <div class="grid2" style="margin-top:8px">
        <div class="block-realized"><div class="label up">当时已兑现</div><b class="mono">{{ fmtMoney(perf(b).totals?.realized) }}</b></div>
        <div class="block-float"><div class="label warn">当时账面浮动</div><b class="mono">{{ fmtMoney(perf(b).totals?.unrealized) }}</b></div>
      </div>
      <div class="muted" style="font-size:12px;margin-top:6px">MWR {{ fmtPct(perf(b).mwr_xirr_pct) }} · TWR {{ fmtPct(perf(b).twr_pct) }} · 执行率 {{ perf(b).execution?.execution_rate_pct ?? '—' }}%</div>
    </template>
    <div v-if="open === b.id" class="md" v-html="render(b.markdown)" style="margin-top:10px"></div>
  </div>

  <p v-if="!items.length" class="muted">该日期暂无简报。</p>
</template>
