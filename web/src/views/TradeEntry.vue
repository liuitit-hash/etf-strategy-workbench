<script setup>
import { ref, computed, reactive } from 'vue'
import { supabase } from '../supabase'
import { store, instById, loadTrades } from '../store'
import { buildPositions } from '../lib/finance'
import { evaluateTrade, resolveAnchor } from '../lib/discipline'
import { fmtMoney, fmtNum, TAG_LABEL } from '../lib/format'

const map = computed(() => instById())
const nowLocal = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16)

const f = reactive({
  trade_time: nowLocal(), instrument_id: '', side: 'buy', shares: null, price: null,
  fee: 0, fx_rate: null, dividend_cash: 0, dividend_reinvest: false, action_tag: 'strategy', note: '',
})
const saving = ref(false)
const saveMsg = ref('')

const selInst = computed(() => map.value[f.instrument_id])
const isHKD = computed(() => selInst.value?.currency === 'HKD')

const positionsNow = computed(() => buildPositions(store.trades, map.value))
const posBefore = computed(() => positionsNow.value[f.instrument_id] || { shares: 0, avgCost: 0, investedPrincipal: 0 })
const lastBuy = computed(() => {
  const buys = store.trades.filter((t) => t.instrument_id === f.instrument_id && t.side === 'buy')
  return buys.length ? buys.map((t) => t.trade_time).sort().at(-1) : null
})

const preview = computed(() => {
  if (!selInst.value || !f.price || !f.shares) return null
  const rule = store.grahamRules[f.instrument_id]
  const ctx = {
    instrument: selInst.value,
    graham_rule: rule,
    tiers: store.tiers[f.instrument_id] || [],
    tp_rule: store.takeProfit[f.instrument_id],
    position: posBefore.value,
    last_buy_time: lastBuy.value,
    current_price: Number(f.price),
    anchor_price: resolveAnchor(rule, posBefore.value, null),
  }
  return evaluateTrade({ ...f, price: Number(f.price), shares: Number(f.shares), fee: Number(f.fee || 0) }, ctx)
})

async function save() {
  if (!f.instrument_id || !f.price || !f.shares) { saveMsg.value = '请填完标的、份额、单价'; return }
  saving.value = true; saveMsg.value = ''
  const payload = {
    trade_time: new Date(f.trade_time).toISOString(),
    instrument_id: f.instrument_id, side: f.side,
    shares: Number(f.shares), price: Number(f.price), fee: Number(f.fee || 0),
    fx_rate: isHKD.value ? Number(f.fx_rate || 0) || null : 1,
    dividend_cash: Number(f.dividend_cash || 0), dividend_reinvest: f.dividend_reinvest,
    action_tag: f.action_tag, note: f.note || null,
    discipline: preview.value,
  }
  const { error } = await supabase.from('trades').insert(payload)
  saving.value = false
  if (error) { saveMsg.value = '保存失败：' + error.message; return }
  saveMsg.value = '已入账（盘后将由引擎权威复核）'
  Object.assign(f, { shares: null, price: null, fee: 0, dividend_cash: 0, note: '' })
  await loadTrades()
}

// 备注更正（不可删除历史）
const editing = ref(null)
const correction = ref('')
async function saveCorrection(id) {
  await supabase.from('trades').update({ correction_note: correction.value }).eq('id', id)
  editing.value = null; correction.value = ''
  await loadTrades()
}
</script>

<template>
  <h2>交易流水录入</h2>
  <p class="muted" style="font-size:12px">手动录入本身就是冷静机制。流水只增不删，更正仅限备注。</p>

  <div class="card">
    <label>交易时间</label>
    <input type="datetime-local" v-model="f.trade_time" />

    <label>标的</label>
    <select v-model="f.instrument_id">
      <option value="" disabled>选择标的</option>
      <option v-for="i in store.instruments" :key="i.id" :value="i.id">{{ i.name }}（{{ i.code }}）</option>
    </select>

    <div class="grid2">
      <div>
        <label>方向</label>
        <select v-model="f.side"><option value="buy">买入</option><option value="sell">卖出</option></select>
      </div>
      <div>
        <label>操作标签</label>
        <select v-model="f.action_tag">
          <option value="strategy">按策略触发</option>
          <option value="emotional">情绪化提前操作</option>
          <option value="planned_tp">计划内止盈</option>
        </select>
      </div>
    </div>

    <div class="grid2">
      <div><label>成交份额</label><input type="number" v-model="f.shares" placeholder="如 10000" /></div>
      <div><label>成交单价</label><input type="number" step="0.001" v-model="f.price" placeholder="如 3.852" /></div>
    </div>
    <div class="grid2">
      <div><label>手续费</label><input type="number" step="0.01" v-model="f.fee" /></div>
      <div v-if="isHKD"><label>成交汇率(→CNY)</label><input type="number" step="0.0001" v-model="f.fx_rate" placeholder="HKD兑人民币" /></div>
    </div>
    <div class="grid2">
      <div><label>现金分红(税前，仅分红事件填)</label><input type="number" step="0.01" v-model="f.dividend_cash" /></div>
      <div><label style="margin-top:34px"><input type="checkbox" v-model="f.dividend_reinvest" style="width:auto;margin-right:6px" />分红再投</label></div>
    </div>
    <label>备注</label>
    <input v-model="f.note" placeholder="可选" />

    <!-- 即时纪律预检 -->
    <div v-if="preview" class="notice" :style="preview.ok ? 'color:var(--up);background:var(--realized-bg);border-color:var(--realized-line)' : ''">
      <b>{{ preview.ok ? '✓ 符合纪律（预检）' : '✗ 违反纪律（预检）' }}</b>：{{ preview.reason }}
      <div style="margin-top:4px">
        <span v-for="fl in preview.flags" :key="fl.code" class="badge" :class="fl.level === 'block' ? 'block' : fl.level === 'warn' ? 'warn' : 'ok'" style="margin:2px 4px 0 0">{{ fl.msg }}</span>
      </div>
    </div>

    <button class="primary" style="width:100%;margin-top:12px" :disabled="saving" @click="save">{{ saving ? '保存中…' : '入账' }}</button>
    <p v-if="saveMsg" class="muted" style="font-size:12px;margin-top:6px">{{ saveMsg }}</p>
  </div>

  <h3>最近流水（不可删除）</h3>
  <div class="card tight">
    <div v-for="t in store.trades.slice(0, 30)" :key="t.id" class="list-item">
      <div class="spread">
        <div>
          <b>{{ map[t.instrument_id]?.name || '—' }}</b>
          <span class="badge" :class="t.side === 'buy' ? 'accent' : 'warn'" style="margin-left:6px">{{ t.side === 'buy' ? '买' : '卖' }}</span>
          <span class="badge" style="margin-left:4px">{{ TAG_LABEL[t.action_tag] }}</span>
        </div>
        <span class="badge" :class="(t.discipline?.ok ?? true) ? 'ok' : 'block'">{{ (t.discipline?.ok ?? true) ? '合规' : '违规' }}</span>
      </div>
      <div class="muted mono" style="font-size:12px;margin-top:3px">
        {{ new Date(t.trade_time).toLocaleString('zh-CN') }} · {{ fmtNum(t.shares,0) }}份 × {{ fmtNum(t.price,3) }} · 费{{ fmtMoney(t.fee,2) }}
        <span v-if="t.discipline?.checked_by === 'engine'" style="color:var(--accent)"> · 引擎已核</span>
      </div>
      <div v-if="t.discipline && !t.discipline.ok" class="warn" style="font-size:12px;margin-top:2px">⚠ {{ t.discipline.reason }}</div>
      <div v-if="t.note" class="muted" style="font-size:12px">备注：{{ t.note }}</div>
      <div v-if="t.correction_note" class="muted" style="font-size:12px">更正：{{ t.correction_note }}</div>
      <div style="margin-top:6px">
        <template v-if="editing === t.id">
          <input v-model="correction" placeholder="填写更正说明" />
          <div class="row" style="margin-top:6px"><button class="primary" @click="saveCorrection(t.id)">保存更正</button><button class="ghost" @click="editing = null">取消</button></div>
        </template>
        <button v-else class="ghost" style="font-size:12px;padding:5px 10px" @click="editing = t.id; correction = t.correction_note || ''">备注更正</button>
      </div>
    </div>
    <p v-if="!store.trades.length" class="muted">暂无流水。</p>
  </div>
</template>
