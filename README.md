# ETF 策略校准工作台

单人自用的 H5 工具（移动优先 / PWA 可添加到桌面）。核心宗旨：**不预测、不荐股**，只做四件事——
记录交易流水、自动拉公开数据、生成三类简报、用【芒格 / 达利欧 / 格雷厄姆】框架校验每笔操作是否违背你预设的纪律；
并把**已兑现落袋收益**与**账面浮动盈亏**在视觉上强制隔离，对抗浮盈浮亏带来的情绪化操作。

## 架构
```
前端 H5 (Vue3 + Vite + PWA)  ── 只读 Supabase 缓存，浏览零 LLM token
        │  登录/读写(RLS)
        ▼
Supabase (Postgres + Auth)  ── 配置/流水/行情缓存/简报
        ▲  service_role 写入
        │
GitHub Actions (三条 cron) ── 盘前/盘中/盘后
  拉公开数据(akshare/yfinance) → 读配置+流水 → 权威纪律校验 → 组Prompt → DeepSeek → 简报入库
```

## 目录
```
supabase/      schema.sql（建表+RLS+视图）、seed.sql（示例数据）
jobs/          Python 定时任务
  common/      config/db/datasource/finance/discipline/llm/prompts/assemble/runner
  premarket.py intraday.py postmarket.py
web/           Vue3 前端（六模块 + PWA）
  src/views/   Portfolio/TradeEntry/Briefings/DataBoard/ConfigPanel/History
  src/lib/     finance.js / discipline.js（Python 引擎的前端镜像）
.github/workflows/  briefings.yml（三简报）/ deploy-web.yml（Pages）/ keepalive.yml
docs/          DEPLOY.md（部署）/ USAGE.md（使用）
```

## 六大模块
1. 策略配置面板（基准契约）  2. 交易流水录入（即时纪律预检，只增不删）
3. 持仓绩效看板（已兑现/浮动强制隔离 + MWR/执行率/子弹池/分标的台账）
4. 自动数据看板（估值分位/宏观/基准/新闻缓存）  5. 简报中心（盘前/盘中/盘后，可复制）
6. 历史回溯（任意日期的简报与当时结论）

## 边界（固化在系统里，不可突破）
- 不预测涨跌、不荐股、不给个性化投资建议；操作预案只复述用户写死的规则。
- 不自动交易、不挂单、不连券商。
- 纪律违规判定以内置引擎为唯一权威，LLM 只转述；每篇简报强制挂免责声明。

## 快速开始
见 [docs/DEPLOY.md](docs/DEPLOY.md)（部署）与 [docs/USAGE.md](docs/USAGE.md)（使用）。

---
> 本项目仅为个人策略复盘与纪律校验工具，不构成任何投资建议，不预测市场涨跌。
