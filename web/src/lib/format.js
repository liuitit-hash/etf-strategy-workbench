export const fmtMoney = (v, d = 2) =>
  v == null || isNaN(v) ? '—' : Number(v).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d })

export const fmtPct = (v, d = 2) => (v == null || isNaN(v) ? '—' : `${Number(v).toFixed(d)}%`)

export const fmtNum = (v, d = 4) => (v == null || isNaN(v) ? '—' : Number(v).toFixed(d))

export const pnlClass = (v) => (v == null ? '' : v > 0 ? 'up' : v < 0 ? 'down' : '')

export const CHANNEL_LABEL = { a_etf: 'A股ETF', hk_connect: '港股通', qdii: 'QDII跨境' }
export const FRAMEWORK_LABEL = { munger: '芒格', dalio: '达利欧', graham: '格雷厄姆' }
export const TAG_LABEL = { strategy: '按策略触发', emotional: '情绪化提前', planned_tp: '计划内止盈' }
export const BRIEFING_LABEL = { daily: '每日研判', pre: '盘前', intra: '盘中', post: '盘后复盘' }
