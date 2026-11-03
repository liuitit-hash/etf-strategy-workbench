"""运行时配置：从环境变量读取。本地可放 .env（python-dotenv 可选）。"""
import os

# 本地调试时若装了 python-dotenv 则自动加载 .env；GitHub Actions 走 Secrets，无需此包。
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass


def _opt(key: str, default: str) -> str:
    """读取环境变量；空字符串（GitHub 未设的 vars 会传 ""）也视为未设，回退默认。"""
    v = os.getenv(key)
    return v if v not in (None, "") else default


def _req(key: str) -> str:
    v = os.getenv(key)
    if not v:
        raise RuntimeError(f"缺少环境变量 {key}")
    return v


SUPABASE_URL = _req("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = _req("SUPABASE_SERVICE_ROLE_KEY")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
LLM_BASE_URL = _opt("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = _opt("LLM_MODEL", "deepseek-chat")
LLM_TEMPERATURE = float(_opt("LLM_TEMPERATURE", "0.3"))

MARKET = _opt("MARKET", "a-share")
TZ = _opt("TZ", "Asia/Shanghai")
