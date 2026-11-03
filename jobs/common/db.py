"""Supabase 访问层（service_role，绕过 RLS）。只被定时任务使用。"""
from __future__ import annotations
from datetime import date
from typing import Any

from supabase import create_client, Client

from . import config

_client: Client | None = None


def db() -> Client:
    global _client
    if _client is None:
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)
    return _client


# ---------- 读取配置（基准契约） ----------

def load_config() -> dict[str, Any]:
    """一次性读出策略配置、储备池。返回以 instrument_id 组织的结构。"""
    c = db()
    instruments = c.table("instruments").select("*").eq("active", True).order("sort_order").execute().data
    graham_rules = {r["instrument_id"]: r for r in c.table("graham_rules").select("*").execute().data}
    tiers: dict[str, list] = {}
    for t in c.table("graham_tiers").select("*").order("tier_index").execute().data:
        tiers.setdefault(t["instrument_id"], []).append(t)
    tp = {r["instrument_id"]: r for r in c.table("take_profit_rules").select("*").execute().data}
    reserve = (c.table("reserve").select("*").eq("id", 1).execute().data or [{}])[0]
    alloc = {r["instrument_id"]: r["allocated"] for r in c.table("reserve_allocations").select("*").execute().data}
    return {
        "instruments": instruments,
        "graham_rules": graham_rules,
        "tiers": tiers,
        "take_profit": tp,
        "reserve": reserve,
        "allocations": alloc,
    }


def load_trades() -> list[dict]:
    return db().table("trades").select("*").order("trade_time").execute().data


def latest_quotes() -> dict[str, dict]:
    rows = db().table("v_latest_quote").select("*").execute().data
    return {r["instrument_id"]: r for r in rows}


def quote_history(instrument_id: str, limit: int = 250) -> list[dict]:
    return (
        db().table("market_quotes").select("*")
        .eq("instrument_id", instrument_id).order("date", desc=True).limit(limit).execute().data
    )


def latest_macro() -> dict[str, dict]:
    rows = db().table("macro_data").select("*").order("date", desc=True).limit(50).execute().data
    out: dict[str, dict] = {}
    for r in rows:                      # 每个 metric 保留最近一条
        out.setdefault(r["metric"], r)
    return out


def recent_news(d: date, days: int = 1) -> list[dict]:
    return (
        db().table("news_items").select("*")
        .gte("date", str(d)).order("date", desc=True).limit(40).execute().data
    )


def execution_rate() -> dict:
    data = db().table("v_execution_rate").select("*").execute().data
    return data[0] if data else {}


# ---------- 写入缓存/简报 ----------

def upsert_quote(row: dict):
    db().table("market_quotes").upsert(row, on_conflict="instrument_id,date").execute()


def upsert_macro(row: dict):
    db().table("macro_data").upsert(row, on_conflict="date,metric").execute()


def upsert_benchmark(row: dict):
    db().table("benchmarks").upsert(row, on_conflict="date,index_code").execute()


def insert_news(rows: list[dict]):
    if rows:
        db().table("news_items").insert(rows).execute()


def update_trade_discipline(trade_id: str, discipline: dict):
    db().table("trades").update({"discipline": discipline}).eq("id", trade_id).execute()


def save_briefing(d: date, btype: str, markdown: str, model: str, usage: dict, inputs: dict):
    """同日同类型存多版本（version 自增），前端默认取最新版。"""
    c = db()
    existing = (
        c.table("briefings").select("version")
        .eq("date", str(d)).eq("type", btype).order("version", desc=True).limit(1).execute().data
    )
    version = (existing[0]["version"] + 1) if existing else 1
    c.table("briefings").insert({
        "date": str(d), "type": btype, "version": version,
        "markdown": markdown, "model": model, "token_usage": usage, "inputs": inputs,
    }).execute()
    return version
