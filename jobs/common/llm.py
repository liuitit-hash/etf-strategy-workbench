"""
LLM 对接层（OpenAI 兼容，默认 DeepSeek）。
省钱要点：System Prompt 作为稳定前缀，DeepSeek 自动命中上下文硬盘缓存（无需手动 cache 标记）；
变量数据放在 user 消息，保持 system 前缀逐字不变即可享受缓存降价。
切换厂商只需改 LLM_BASE_URL / LLM_MODEL / API Key。
"""
from __future__ import annotations
from openai import OpenAI

from . import config

_client: OpenAI | None = None


def client() -> OpenAI:
    global _client
    if _client is None:
        if not config.DEEPSEEK_API_KEY:
            raise RuntimeError("缺少 DEEPSEEK_API_KEY")
        _client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.LLM_BASE_URL)
    return _client


def generate(system: str, user: str) -> tuple[str, dict]:
    """返回 (markdown文本, usage字典)。失败抛异常由上层捕获。"""
    resp = client().chat.completions.create(
        model=config.LLM_MODEL,
        temperature=config.LLM_TEMPERATURE,
        messages=[
            {"role": "system", "content": system},   # 稳定前缀 → 命中缓存
            {"role": "user", "content": user},
        ],
        stream=False,
    )
    text = resp.choices[0].message.content or ""
    usage = {}
    try:
        u = resp.usage
        usage = {
            "prompt_tokens": u.prompt_tokens,
            "completion_tokens": u.completion_tokens,
            "total_tokens": u.total_tokens,
            # DeepSeek 返回的缓存命中/未命中 token（若有）
            "cache_hit": getattr(u, "prompt_cache_hit_tokens", None),
            "cache_miss": getattr(u, "prompt_cache_miss_tokens", None),
        }
    except Exception:
        pass
    return text, usage
