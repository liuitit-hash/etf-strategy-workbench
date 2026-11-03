// 绩效计算（Python finance.py 的前端镜像，用于看板即时展示）。
// 均价法。严格区分：已兑现（落袋）vs 账面浮动（会消失）。

function fx(t) {
  const r = Number(t.fx_rate)
  return r ? r : 1.0
}

export function buildPositions(trades, instById) {
  const pos = {}
  const sorted = [...trades].sort((a, b) => new Date(a.trade_time) - new Date(b.trade_time))
  for (const t of sorted) {
    const iid = t.instrument_id
    if (!pos[iid]) {
      pos[iid] = {
        instrument_id: iid, shares: 0, avgCost: 0, investedPrincipal: 0,
        realizedCapital: 0, realizedDividend: 0, fxPnl: 0, cashflows: [],
      }
    }
    const p = pos[iid]
    const price = Number(t.price), shares = Number(t.shares), fee = Number(t.fee || 0)
    const rate = fx(t)
    const d = new Date(t.trade_time)

    const div = Number(t.dividend_cash || 0)
    if (div) {
      const tax = Number((instById[iid] || {}).dividend_tax_rate || 0)
      const net = div * (1 - tax) * rate
      if (t.dividend_reinvest) {
        const addShares = price && rate ? net / (price * rate) : 0
        const totalCost = p.avgCost * p.shares + net / rate
        p.shares += addShares
        p.avgCost = p.shares ? totalCost / p.shares : 0
      } else {
        p.realizedDividend += net
        p.cashflows.push([d, net])
      }
    }

    if (t.side === 'buy') {
      const cost = price * shares + fee
      const total = p.avgCost * p.shares + cost
      p.shares += shares
      p.avgCost = p.shares ? total / p.shares : 0
      p.investedPrincipal += cost * rate
      p.cashflows.push([d, -(cost * rate)])
    } else if (t.side === 'sell') {
      const capLocal = (price - p.avgCost) * shares - fee
      p.realizedCapital += capLocal * rate
      const proceeds = price * shares * rate - fee * rate
      p.investedPrincipal -= proceeds
      p.cashflows.push([d, proceeds])
      p.shares -= shares
      if (p.shares <= 1e-9) { p.shares = 0; p.avgCost = 0 }
    }
  }
  return pos
}

export function positionView(p, lastClose, fxNow) {
  const mvLocal = p.shares * (lastClose || 0)
  const mvCny = mvLocal * fxNow
  const costCny = p.shares * p.avgCost * fxNow
  const hasClose = lastClose != null
  const unreal = hasClose ? mvCny - costCny : null
  const unrealPct = unreal != null && costCny ? (unreal / costCny) * 100 : null
  return {
    shares: p.shares,
    avgCost: p.avgCost,
    investedPrincipal: p.investedPrincipal,
    marketValue: hasClose ? mvCny : null,
    unrealized: unreal,
    unrealizedPct: unrealPct,
    realizedCapital: p.realizedCapital,
    realizedDividend: p.realizedDividend,
    fxPnl: p.fxPnl,
    realizedTotal: p.realizedCapital + p.realizedDividend + p.fxPnl,
  }
}

// 资金加权收益 XIRR（牛顿法 + 二分兜底）。cashflows: [[Date, amount], ...]，含期末市值
export function xirr(cashflows, guess = 0.1) {
  const flows = cashflows.filter(([, a]) => a)
  if (flows.length < 2) return null
  const t0 = flows.reduce((m, [d]) => (d < m ? d : m), flows[0][0])
  const yr = (d) => (d - t0) / (365 * 24 * 3600 * 1000)
  const npv = (r) => flows.reduce((s, [d, a]) => s + a / Math.pow(1 + r, yr(d)), 0)

  let rate = guess
  for (let i = 0; i < 100; i++) {
    const f = npv(rate), h = 1e-6
    const d1 = (npv(rate + h) - f) / h
    if (Math.abs(d1) < 1e-12) break
    const next = rate - f / d1
    if (!(next > -0.999999 && next < 1e6)) break
    if (Math.abs(next - rate) < 1e-8) return +(next * 100).toFixed(2)
    rate = next
  }
  let lo = -0.9999, hi = 10, flo = npv(lo), fhi = npv(hi)
  if (flo * fhi > 0) return null
  for (let i = 0; i < 200; i++) {
    const mid = (lo + hi) / 2, fm = npv(mid)
    if (Math.abs(fm) < 1e-6) return +(mid * 100).toFixed(2)
    if (flo * fm < 0) { hi = mid; fhi = fm } else { lo = mid; flo = fm }
  }
  return +(((lo + hi) / 2) * 100).toFixed(2)
}
