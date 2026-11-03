"""盘前入口：同时生成 盘前简报 + 每日研判条。用法：python -m jobs.premarket（手动：加 force）"""
from jobs.common.runner import run_briefings

if __name__ == "__main__":
    run_briefings(["pre", "daily"])
