"""三种简报的统一执行链路。被 premarket/intraday/postmarket 调用。"""
from __future__ import annotations
import logging
import sys
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
except Exception:                       # py<3.9 兜底
    ZoneInfo = None  # type: ignore

from . import config, db, assemble, prompts, llm
from .prompts import DISCLAIMER

log = logging.getLogger("runner")


def _today():
    if ZoneInfo:
        return datetime.now(ZoneInfo(config.TZ)).date()
    return datetime.now().date()


def run_briefing(btype: str) -> None:
    force = "force" in sys.argv[1:]          # 手动复盘时传 force 跳过交易日判断
    d = _today()
    cfg = db.load_config()

    from . import datasource
    if not force and not datasource.is_trading_day(d):
        log.info("%s 非交易日，跳过 %s 简报", d, btype)
        return

    snap = assemble.refresh_market_data(cfg, d)

    trades = None
    perf = None
    if btype == "post":
        trades = assemble.recheck_discipline(cfg)
        perf = assemble.compute_performance(cfg, trades, d)
    elif btype == "pre":
        perf = assemble.compute_performance(cfg, db.load_trades(), d)

    user = assemble.build_user_message(btype, cfg, d, snap, perf, trades)
    system = prompts.system_for(btype)

    text, usage = llm.generate(system, user)
    text = text.strip()
    if DISCLAIMER not in text:              # 强制免责兜底
        text += f"\n\n> {DISCLAIMER}"

    inputs = {"performance": perf, "macro_keys": list((snap or {}).get("macro", {}).keys())}
    version = db.save_briefing(d, btype, text, config.LLM_MODEL, usage, inputs)
    log.info("已生成 %s 简报 %s v%s，usage=%s", btype, d, version, usage)
