"""盘后完整复盘简报入口。用法：python -m jobs.postmarket  （手动复盘：加 force）"""
from jobs.common.runner import run_briefing

if __name__ == "__main__":
    run_briefing("post")
