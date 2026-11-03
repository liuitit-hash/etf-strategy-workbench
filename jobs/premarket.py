"""盘前简报入口。用法：python -m jobs.premarket  （手动跳过交易日判断：加 force）"""
from jobs.common.runner import run_briefing

if __name__ == "__main__":
    run_briefing("pre")
