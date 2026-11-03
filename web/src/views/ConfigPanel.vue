<script setup>
import { ref, reactive, computed } from 'vue'
import { supabase } from '../supabase'
import { store, loadConfig } from '../store'
import { CHANNEL_LABEL, FRAMEWORK_LABEL, fmtMoney } from '../lib/format'

const FRAMES = ['munger', 'dalio', 'graham']
const msg = ref('')
const expanded = ref(null)

// 新增标的
const blank = () => ({ code: '', name: '', currency: 'CNY', channel: 'a_etf', frameworks: ['munger', 'dalio', 'graham'], in_circle: true, blacklist: false, dividend_tax_rate: 0, benchmark_index: '', sort_order: 0 })
const nf = reactive(blank())

async function addInstrument() {
  if (!nf.code || !nf.name) { msg.value = '请填代码和名称'; return }
  const { error } = await supabase.from('instruments').insert({ ...nf })
  msg.value = error ? '失败：' + error.message : '已添加'
  if (!error) { Object.assign(nf, blank()); await loadConfig() }
}

async function updateInstrument(i) {
  const { id, ...rest } = i
  const { error } = await supabase.from('instruments').update(rest).eq('id', id)
  msg.value = error ? '失败：' + error.message : '已保存'
  if (!error) await loadConfig()
}

function toggleFrame(i, fr) {
  const s = new Set(i.frameworks || [])
  s.has(fr) ? s.delete(fr) : s.add(fr)
  i.frameworks = [...s]
}

// 格雷厄姆规则 + 档位 工作副本
const work = reactive({})
function openEditor(i) {
  expanded.value = expanded.value === i.id ? null : i.id
  if (expanded.value) {
    work[i.id] = {
      rule: { ...(store.grahamRules[i.id] || { instrument_id: i.id, max_capital: 0, cooldown_days: 0, anchor_mode: 'cost', anchor_price: null, recent_high_lookback: 60 }) },
      tiers: JSON.parse(JSON.stringify(store.tiers[i.id] || [])),
      tp: { ...(store.takeProfit[i.id] || { instrument_id: i.id, target_price: null, target_return_pct: null, batches: [] }) },
      alloc: Number(store.allocations[i.id] || 0),
    }
  }
}
function addTier(i) {
  const list = work[i.id].tiers
  list.push({ instrument_id: i.id, tier_index: list.length + 1, drawdown_pct: 5, add_amount: 10000 })
}
function addBatch(i) { (work[i.id].tp.batches ||= []).push({ trigger_return: 20, sell_ratio: 0.25 }) }

async function saveGraham(i) {
  const w = work[i.id]
  await supabase.from('graham_rules').upsert({ ...w.rule, instrument_id: i.id })
  await supabase.from('graham_tiers').delete().eq('instrument_id', i.id)
  const tiers = w.tiers.map((t, idx) => ({ instrument_id: i.id, tier_index: idx + 1, drawdown_pct: Number(t.drawdown_pct), add_amount: Number(t.add_amount) }))
  if (tiers.length) await supabase.from('graham_tiers').insert(tiers)
  await supabase.from('take_profit_rules').upsert({ instrument_id: i.id, target_price: w.tp.target_price || null, target_return_pct: w.tp.target_return_pct || null, batches: w.tp.batches || [] })
  await supabase.from('reserve_allocations').upsert({ instrument_id: i.id, allocated: Number(w.alloc || 0) })
  msg.value = '策略规则已保存'
  await loadConfig()
}

const reserveTotal = ref(0)
function syncReserve() { reserveTotal.value = Number(store.reserve?.total_reserve || 0) }
syncReserve()
async function saveReserve() {
  await supabase.from('reserve').upsert({ id: 1, total_reserve: Number(reserveTotal.value || 0), updated_at: new Date().toISOString() })
  msg.value = '储备金已更新'; await loadConfig()
}
</script>

<template>
  <h2>策略配置面板（基准契约）</h2>
  <p class="muted" style="font-size:12px">这里写死的规则是永久校验基准。每次校验交易、生成简报都与这套基准对比。</p>
  <p v-if="msg" class="badge accent" style="margin:6px 0">{{ msg }}</p>

  <div class="card">
    <h3>子弹总预备资金</h3>
    <div class="row"><input type="number" v-model="reserveTotal" @focus="syncReserve" /><button class="primary" @click="saveReserve">保存</button></div>
  </div>

  <h3>标的池</h3>
  <div v-for="i in store.instruments" :key="i.id" class="card">
    <div class="spread">
      <div><b>{{ i.name }}</b> <span class="muted mono">{{ i.code }}</span>
        <span class="badge" style="margin-left:6px">{{ CHANNEL_LABEL[i.channel] }}</span>
        <span v-if="i.blacklist" class="badge block" style="margin-left:4px">黑名单</span>
        <span v-if="!i.in_circle" class="badge warn" style="margin-left:4px">圈外</span>
      </div>
      <button class="ghost" @click="openEditor(i)">{{ expanded === i.id ? '收起' : '编辑' }}</button>
    </div>

    <template v-if="expanded === i.id">
      <div class="grid2">
        <div><label>名称</label><input v-model="i.name" /></div>
        <div><label>代码</label><input v-model="i.code" /></div>
      </div>
      <div class="grid2">
        <div><label>计价币种</label><select v-model="i.currency"><option>CNY</option><option>HKD</option></select></div>
        <div><label>持有通道</label><select v-model="i.channel"><option value="a_etf">A股ETF</option><option value="hk_connect">港股通</option><option value="qdii">QDII跨境</option></select></div>
      </div>
      <div class="grid2">
        <div><label>红利税率（港股通直接持股=0.2）</label><input type="number" step="0.01" v-model="i.dividend_tax_rate" /></div>
        <div><label>估值基准指数</label><input v-model="i.benchmark_index" placeholder="hs300/hstech/dividend" /></div>
      </div>
      <label>校验框架</label>
      <div class="pill-group">
        <button v-for="fr in FRAMES" :key="fr" :class="{ on: (i.frameworks || []).includes(fr) }" @click="toggleFrame(i, fr)">{{ FRAMEWORK_LABEL[fr] }}</button>
      </div>
      <div class="row wrap" style="margin-top:10px">
        <label style="width:auto"><input type="checkbox" v-model="i.in_circle" style="width:auto;margin-right:6px" />在能力圈内</label>
        <label style="width:auto"><input type="checkbox" v-model="i.blacklist" style="width:auto;margin-right:6px" />黑名单（禁加仓，仅止盈）</label>
      </div>
      <button class="primary" style="margin-top:8px" @click="updateInstrument(i)">保存标的基础信息</button>

      <template v-if="work[i.id]">
        <h3 style="margin-top:16px">格雷厄姆梯度加仓</h3>
        <div class="grid2">
          <div><label>单标的资金上限</label><input type="number" v-model="work[i.id].rule.max_capital" /></div>
          <div><label>加仓冷却间隔(天)</label><input type="number" v-model="work[i.id].rule.cooldown_days" /></div>
        </div>
        <div class="grid2">
          <div><label>回撤锚点</label><select v-model="work[i.id].rule.anchor_mode"><option value="cost">持仓成本</option><option value="recent_high">近期高点</option><option value="manual">手动</option></select></div>
          <div v-if="work[i.id].rule.anchor_mode === 'manual'"><label>手动锚价</label><input type="number" step="0.001" v-model="work[i.id].rule.anchor_price" /></div>
          <div v-else-if="work[i.id].rule.anchor_mode === 'recent_high'"><label>近高回看(交易日)</label><input type="number" v-model="work[i.id].rule.recent_high_lookback" /></div>
        </div>
        <label>加仓档位（回撤% → 允许金额）</label>
        <div v-for="(t, idx) in work[i.id].tiers" :key="idx" class="row" style="margin-bottom:6px">
          <input type="number" v-model="t.drawdown_pct" placeholder="回撤%" />
          <input type="number" v-model="t.add_amount" placeholder="加仓金额" />
          <button class="ghost" @click="work[i.id].tiers.splice(idx, 1)">×</button>
        </div>
        <button class="ghost" @click="addTier(i)">+ 加一档</button>

        <h3 style="margin-top:16px">止盈规则</h3>
        <div class="grid2">
          <div><label>止盈目标价</label><input type="number" step="0.001" v-model="work[i.id].tp.target_price" /></div>
          <div><label>止盈目标收益率%</label><input type="number" v-model="work[i.id].tp.target_return_pct" /></div>
        </div>
        <label>分批止盈（触发收益% → 卖出比例）</label>
        <div v-for="(b, idx) in work[i.id].tp.batches" :key="idx" class="row" style="margin-bottom:6px">
          <input type="number" v-model="b.trigger_return" placeholder="触发收益%" />
          <input type="number" step="0.05" v-model="b.sell_ratio" placeholder="卖出比例 0-1" />
          <button class="ghost" @click="work[i.id].tp.batches.splice(idx, 1)">×</button>
        </div>
        <button class="ghost" @click="addBatch(i)">+ 加一批</button>

        <h3 style="margin-top:16px">该标的加仓额度</h3>
        <input type="number" v-model="work[i.id].alloc" />

        <button class="primary" style="width:100%;margin-top:12px" @click="saveGraham(i)">保存全部策略规则</button>
      </template>
    </template>
  </div>

  <h3>新增标的</h3>
  <div class="card">
    <div class="grid2">
      <div><label>代码</label><input v-model="nf.code" placeholder="510300.SH" /></div>
      <div><label>名称</label><input v-model="nf.name" placeholder="沪深300ETF" /></div>
    </div>
    <div class="grid2">
      <div><label>币种</label><select v-model="nf.currency"><option>CNY</option><option>HKD</option></select></div>
      <div><label>通道</label><select v-model="nf.channel"><option value="a_etf">A股ETF</option><option value="hk_connect">港股通</option><option value="qdii">QDII跨境</option></select></div>
    </div>
    <div class="grid2">
      <div><label>红利税率</label><input type="number" step="0.01" v-model="nf.dividend_tax_rate" /></div>
      <div><label>估值基准指数</label><input v-model="nf.benchmark_index" placeholder="hstech" /></div>
    </div>
    <label>框架</label>
    <div class="pill-group"><button v-for="fr in FRAMES" :key="fr" :class="{ on: nf.frameworks.includes(fr) }" @click="toggleFrame(nf, fr)">{{ FRAMEWORK_LABEL[fr] }}</button></div>
    <div class="row wrap" style="margin-top:10px">
      <label style="width:auto"><input type="checkbox" v-model="nf.in_circle" style="width:auto;margin-right:6px" />能力圈</label>
      <label style="width:auto"><input type="checkbox" v-model="nf.blacklist" style="width:auto;margin-right:6px" />黑名单</label>
    </div>
    <button class="primary" style="width:100%;margin-top:10px" @click="addInstrument">添加标的</button>
  </div>
</template>
