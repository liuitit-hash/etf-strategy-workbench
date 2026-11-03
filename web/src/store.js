import { reactive } from 'vue'
import { supabase } from './supabase'

export const store = reactive({
  user: null,
  instruments: [],
  grahamRules: {},   // iid -> rule
  tiers: {},         // iid -> [tier]
  takeProfit: {},    // iid -> rule
  reserve: {},
  allocations: {},   // iid -> allocated
  trades: [],
  quotes: {},        // iid -> latest quote
  macro: {},         // metric -> row
  benchmarks: [],
  news: [],
  execRate: {},
  loading: false,
  error: '',
})

export const instById = () => Object.fromEntries(store.instruments.map((i) => [i.id, i]))

async function sel(table, order) {
  let q = supabase.from(table).select('*')
  if (order) q = q.order(order.col, { ascending: order.asc !== false })
  const { data, error } = await q
  if (error) throw error
  return data || []
}

export async function loadConfig() {
  store.instruments = await sel('instruments', { col: 'sort_order' })
  store.grahamRules = Object.fromEntries((await sel('graham_rules')).map((r) => [r.instrument_id, r]))
  const tiers = await sel('graham_tiers', { col: 'tier_index' })
  store.tiers = {}
  for (const t of tiers) (store.tiers[t.instrument_id] ||= []).push(t)
  store.takeProfit = Object.fromEntries((await sel('take_profit_rules')).map((r) => [r.instrument_id, r]))
  const res = await sel('reserve')
  store.reserve = res[0] || { total_reserve: 0 }
  store.allocations = Object.fromEntries((await sel('reserve_allocations')).map((r) => [r.instrument_id, r.allocated]))
}

export async function loadTrades() {
  store.trades = await sel('trades', { col: 'trade_time', asc: false })
}

export async function loadMarket() {
  const q = await sel('v_latest_quote')
  store.quotes = Object.fromEntries(q.map((r) => [r.instrument_id, r]))
  const macro = await sel('macro_data', { col: 'date', asc: false })
  store.macro = {}
  for (const m of macro) if (!store.macro[m.metric]) store.macro[m.metric] = m
  store.benchmarks = (await sel('benchmarks', { col: 'date', asc: false })).slice(0, 12)
  const { data: er } = await supabase.from('v_execution_rate').select('*').single()
  store.execRate = er || {}
}

export async function loadNews() {
  store.news = (await sel('news_items', { col: 'date', asc: false })).slice(0, 40)
}

export async function loadAll() {
  store.loading = true
  store.error = ''
  try {
    await loadConfig()
    await Promise.all([loadTrades(), loadMarket(), loadNews()])
  } catch (e) {
    store.error = e.message || String(e)
  } finally {
    store.loading = false
  }
}
