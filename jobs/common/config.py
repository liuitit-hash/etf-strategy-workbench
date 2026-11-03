"""运行时配置：从环境变量读取。本地可放 .env（python-dotenv 可选）。"""
import os

# 本地调试时若装了 python-dotenv 则自动加载 .env；GitHub Actions 走 Secrets，无需此包。
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass


def _req(key: str) -> str:
    v = os.getenv(key)
    if not v:
        raise RuntimeError(f"缺少环境变量 {key}")
    return v


SUPABASE_URL = _req("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = _req("SUPABASE_SERVICE_ROLE_KEY")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))

MARKET = os.getenv("MARKET", "a-share")
TZ = os.getenv("TZ", "Asia/Shanghai")
