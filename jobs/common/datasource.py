"""
公开免费数据源抓取层。
设计原则：每个抓取都包在 try/except 里，单点失败不拖垮整条任务；拿不到就返回 None，
简报里据实注明"数据缺失"，绝不编造数值。

主源：akshare（东财/乐咕/韭圈儿公开源，A股ETF与指数估值分位、南向资金、DR007）。
辅源：yfinance（海外宏观：10Y美债、美元指数、恒生科技指数）。

说明：akshare 接口名偶有变动。若某接口报错，去 https://akshare.akfamily.xyz 查最新函数名，
只需改本文件对应处；上层逻辑不受影响。
"""
from __future__ import annotations
import logging
from datetime import date, datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("datasource")


def _safe(fn, default=None):
    try:
        return fn()
    except Exception as e:                       # noqa: BLE001
        log.warning("数据抓取失败 %s: %s", getattr(fn, "__name__", fn), e)
        return default


# benchmark_index 代码 -> 中证指数官方估值代码（stock_zh_index_value_csindex）
# 只收录中证系列（有官方 PE/股息率日度历史）。恒生科技等非中证指数无免费估值分位，返回 None（简报据实标注缺失）。
CSI_SYMBOL = {
    "hs300": "000300",
    "dividend": "000922",
    "sse50": "000016",
    "csi500": "000905",
    "csi1000": "000852",
    "hkdiv": "930914",      # 中证港股通高股息投资指数（513820 港股通红利ETF 跟踪）
}

# benchmark_index -> 乐咕乐股(stock_index_pe_lg) 指数名：长历史滚动市盈率，用于估值分位
# 仅收录乐咕支持的宽基；其余指数分位置空（据实标注缺失）。
LG_SYMBOL = {
    "hs300": "沪深300",
    "sse50": "上证50",
    "csi500": "中证500",
    "chinext": "创业板指",
    "kc50": "科创50",
}

# benchmark_index -> yfinance 符号（基准指数行情对比）
YF_INDEX = {
    "hs300": "000300.SS",
    "dividend": "000922.SS",
}


# ---------- 交易日 ----------

def is_trading_day(d: date) -> bool:
    """A股交易日历（akshare）。拿不到日历时退化为"周一到周五=True"。"""
    import akshare as ak

    def _run():
        df = ak.tool_trade_date_hist_sina()
        days = {str(x) for x in df["trade_date"].astype(str)}
        return str(d) in days

    res = _safe(_run)
    if res is None:
        return d.weekday() < 5
    return res


# ---------- ETF 行情 / 净值 ----------

def _sina_prefix(code: str) -> str:
    """513180.SH -> sh513180；159915.SZ -> sz159915。"""
    sym6, _, suf = code.partition(".")
    suf = suf.lower()
    if suf.startswith("sh") or suf == "ss":
        p = "sh"
    elif suf.startswith("sz"):
        p = "sz"
    else:
        p = "sh" if sym6[:1] in ("5", "6") else "sz"
    return f"{p}{sym6}"


def etf_quote(code: str) -> dict | None:
    """返回 {close, nav, date}。行情主源 sina（稳），eastmoney 兜底；净值 best-effort。"""
    import akshare as ak
    sym6 = code.split(".")[0]

    def _sina():
        df = ak.fund_etf_hist_sina(symbol=_sina_prefix(code))
        if df is None or df.empty:
            return None
        last = df.iloc[-1]
        return {"close": float(last["close"]), "date": str(last["date"])}

    def _em():
        df = ak.fund_etf_hist_em(symbol=sym6, period="daily", adjust="")
        if df is None or df.empty:
            return None
        last = df.iloc[-1]
        return {"close": float(last["收盘"]), "date": str(last["日期"])}

    base = _safe(_sina) or _safe(_em)
    if base is None:
        return None

    # 净值(nav)留空：场内收盘价已满足绩效计算，且 fund_etf_fund_info_em
    # 会全量翻页抓取、极慢，不适合定时任务。如确需净值可另行单独补抓。
    base["nav"] = None
    return base


# ---------- 指数估值（PE/PB/股息率 + 历史分位，自算分位最稳） ----------

def index_valuation(index_code: str) -> dict | None:
    """
    返回 {pe, pb, dividend_yield, valuation_percentile}。
    数据源：中证指数官方估值 stock_zh_index_value_csindex（滚动市盈率=市盈率2、股息率=股息率2）。
    分位由历史 PE 序列自算；历史点数不足 60 时分位返回 None（据实标注，不硬凑）。
    PB 官方此接口不提供，返回 None。非中证指数（如恒生科技）返回 None。
    """
    import akshare as ak
    csi = CSI_SYMBOL.get(index_code)
    lg = LG_SYMBOL.get(index_code)
    pe = dy = pct = None
    points = 0

    # 当前 PE / 股息率：中证官方（日度，最新）
    if csi:
        def _cs():
            df = ak.stock_zh_index_value_csindex(symbol=csi).sort_values("日期")
            pe_col = "市盈率2" if "市盈率2" in df.columns else "市盈率1"
            dy_col = "股息率2" if "股息率2" in df.columns else "股息率1"
            p = df[pe_col].astype(float).dropna()
            d = df[dy_col].astype(float).dropna()
            return (float(p.iloc[-1]) if not p.empty else None,
                    float(d.iloc[-1]) if not d.empty else None)
        r = _safe(_cs)
        if r:
            pe, dy = r

    # 历史分位：乐咕长历史滚动市盈率（点数充足才算）
    if lg:
        def _lg():
            df = ak.stock_index_pe_lg(symbol=lg).sort_values("日期")
            return df["滚动市盈率"].astype(float).dropna()
        s = _safe(_lg)
        if s is not None and len(s) >= 60:
            latest = pe if pe is not None else float(s.iloc[-1])
            pct = round(float((s <= latest).mean()) * 100, 1)
            points = int(len(s))
            if pe is None:
                pe = float(s.iloc[-1])

    if pe is None and dy is None and pct is None:
        return None
    return {"pe": pe, "pb": None, "dividend_yield": dy,
            "valuation_percentile": pct, "pe_history_points": points}


# ---------- 指数行情（基准对比） ----------

def index_quote(index_code: str) -> dict | None:
    import yfinance as yf
    sym = YF_INDEX.get(index_code)
    if not sym:
        return None

    def _run():
        hist = yf.Ticker(sym).history(period="5d")
        if hist is None or hist.empty:
            return None
        close = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else close
        pct = round((close / prev - 1) * 100, 2) if prev else None
        return {"close": close, "pct_change": pct}

    return _safe(_run)


# ---------- 宏观 ----------

def macro_snapshot() -> dict[str, float | None]:
    import yfinance as yf
    import akshare as ak
    from datetime import timedelta
    out: dict[str, float | None] = {}

    def _yf_last(sym):
        hist = yf.Ticker(sym).history(period="5d")
        return float(hist["Close"].iloc[-1]) if hist is not None and not hist.empty else None

    out["us10y"] = _safe(lambda: _yf_last("^TNX"))            # 10年美债收益率（%）
    out["dxy"] = _safe(lambda: _yf_last("DX-Y.NYB"))          # 美元指数

    def _southbound():
        df = ak.stock_hsgt_fund_flow_summary_em()
        sub = df[df["资金方向"].str.contains("南向", na=False)]
        return round(float(sub["成交净买额"].astype(float).sum()), 2) if not sub.empty else None

    out["southbound_net"] = _safe(_southbound)                # 南向资金净流入（亿）

    def _dr007():
        # 存款类机构质押式回购定盘利率 7天（DR007 代理）
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=20)).strftime("%Y%m%d")
        df = ak.repo_rate_hist(start_date=start, end_date=end)
        col = "FDR007" if "FDR007" in df.columns else "FR007"
        s = df[col].astype(float).dropna()
        return float(s.iloc[-1]) if not s.empty else None

    out["dr007"] = _safe(_dr007)

    def _fx(pair):
        # 中行牌价「中行折算价」为每100外币兑人民币，除以100得汇率
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=20)).strftime("%Y%m%d")
        df = ak.currency_boc_sina(symbol=pair, start_date=start, end_date=end)
        col = "中行折算价" if "中行折算价" in df.columns else "央行中间价"
        s = df[col].astype(float).dropna()
        return round(float(s.iloc[-1]) / 100, 4) if not s.empty else None

    out["usdcnh"] = _safe(lambda: _fx("美元"))
    out["hkdcnh"] = _safe(lambda: _fx("港币"))
    return out


# ---------- 财经新闻（只取标题+摘要，不做解读） ----------

def news_digest(limit: int = 15) -> list[dict]:
    """财经日历/事件（百度），只取客观字段，不做解读。CCTV 新闻联播为兜底。"""
    import akshare as ak

    def _baidu():
        df = ak.news_economic_baidu(date=datetime.now().strftime("%Y%m%d"))
        if df is None or df.empty:
            return []
        rows = []
        for _, r in df.head(limit).iterrows():
            rows.append({
                "title": f"{r.get('地区', '')}·{r.get('事件', '')}"[:200],
                "summary": f"公布{r.get('公布')} 预期{r.get('预期')} 前值{r.get('前值')} 重要性{r.get('重要性')}"[:400],
                "source": "财经日历(baidu)",
                "url": None,
            })
        return rows

    def _cctv():
        df = ak.news_cctv(date=datetime.now().strftime("%Y%m%d"))
        if df is None or df.empty:
            return []
        return [{"title": str(r.get("title", ""))[:200], "summary": str(r.get("content", ""))[:400],
                 "source": "CCTV", "url": None} for _, r in df.head(limit).iterrows()]

    rows = _safe(_baidu, default=[]) or []
    if not rows:
        rows = _safe(_cctv, default=[]) or []
    return rows
