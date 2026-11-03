"""盘中快照简报入口。用法：python -m jobs.intraday"""
from jobs.common.runner import run_briefing

if __name__ == "__main__":
    run_briefing("intra")
