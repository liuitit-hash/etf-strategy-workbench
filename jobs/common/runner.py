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


def run_briefings(types: list[str]) -> None:
    """一次拉数据，生成一个或多个简报（如盘前同时出 pre + daily 研判）。"""
    force = "force" in sys.argv[1:]          # 手动触发时传 force 跳过交易日判断
    d = _today()
    cfg = db.load_config()

    from . import datasource
    if not force and not datasource.is_trading_day(d):
        log.info("%s 非交易日，跳过 %s", d, types)
        return

    snap = assemble.refresh_market_data(cfg, d)

    # post 需要权威重算纪律并写回；其余读现有流水
    trades = assemble.recheck_discipline(cfg) if "post" in types else db.load_trades()
    need_perf = any(t in ("pre", "post", "daily") for t in types)
    perf = assemble.compute_performance(cfg, trades, d) if need_perf else None

    for btype in types:
        t_arg = trades if btype == "post" else None
        user = assemble.build_user_message(btype, cfg, d, snap, perf, t_arg)
        system = prompts.system_for(btype)
        text, usage = llm.generate(system, user)
        text = text.strip()
        if DISCLAIMER not in text:          # 强制免责兜底
            text += f"\n\n> {DISCLAIMER}"
        inputs = {"performance": perf, "macro_keys": list((snap or {}).get("macro", {}).keys())}
        version = db.save_briefing(d, btype, text, config.LLM_MODEL, usage, inputs)
        log.info("已生成 %s 简报 %s v%s，usage=%s", btype, d, version, usage)


def run_briefing(btype: str) -> None:
    run_briefings([btype])
