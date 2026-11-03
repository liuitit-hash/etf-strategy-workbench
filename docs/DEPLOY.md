# 部署文档（一步一步）

整套由三块组成：**Supabase（数据库+登录）**、**前端 H5（GitHub Pages）**、**定时任务（GitHub Actions + DeepSeek）**。
预计 30–45 分钟。全部免费额度即可自用。

---

## 0. 准备账号
- GitHub 账号（放代码 + 跑定时任务 + 托管前端）
- Supabase 账号：https://supabase.com （免费版够用）
- DeepSeek 账号 + API Key：https://platform.deepseek.com

先把本项目推到你自己的一个 GitHub 仓库（设为 **private** 更稳妥）。

```bash
cd etf-strategy-workbench
git init && git add . && git commit -m "init"
git branch -M main
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

---

## 1. Supabase：建库 + 登录

1. 新建一个 Supabase 项目，记下 **Project URL** 和两把 Key：
   - `anon`（公开 key，前端用）
   - `service_role`（高权限，只给定时任务用，**绝不进前端**）
   位置：Project Settings → API。
2. 打开 **SQL Editor**，把 [`supabase/schema.sql`](../supabase/schema.sql) 全文粘贴执行。
3. （可选）再执行 [`supabase/seed.sql`](../supabase/seed.sql) 灌入示例标的，方便先跑通。
4. 开启邮箱登录：Authentication → Providers → Email 打开（Magic Link 即可）。
5. 建你自己的账号：Authentication → Users → Add user，填你的邮箱。
   （也可以等前端上线后，在登录页用邮箱收 Magic Link 自助登录。）
6. 配置回跳地址：Authentication → URL Configuration →
   把 **Site URL** 和 **Redirect URLs** 填成你的前端地址（见第 2 步拿到的 Pages 地址，形如
   `https://<用户名>.github.io/<仓库名>/`）。

> RLS 已内置：登录账号只能读写数据，`trades` 表禁止删除；缓存/简报表登录账号只读，由定时任务写入。

---

## 2. 前端：发布到 GitHub Pages

**方式 A（推荐，自动）**：用内置 workflow。
1. 仓库 Settings → Pages → Source 选 **GitHub Actions**。
2. 仓库 Settings → Secrets and variables → Actions → **Variables** 里新增：
   - `VITE_SUPABASE_URL` = 你的 Project URL
   - `VITE_SUPABASE_ANON_KEY` = anon key
   （anon 是公开 key，放 Variables 没问题。）
3. 推一次代码或在 Actions 里手动运行 **deploy-web**，完成后 Pages 地址即上线。
4. 回到第 1.6 步把这个 Pages 地址填进 Supabase 的 Redirect URLs。

**方式 B（本地构建自测）**：
```bash
cd web
cp .env.example .env.local   # 填 VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY
npm install
npm run dev                  # 本地预览 http://localhost:5173
npm run build                # 产物在 web/dist
```

手机打开 Pages 地址 → 浏览器菜单「添加到主屏幕」即成为桌面 App（PWA）。

---

## 3. 定时任务：GitHub Actions + DeepSeek

1. 仓库 Settings → Secrets and variables → Actions → **Secrets** 新增（敏感，必须放 Secrets）：
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `DEEPSEEK_API_KEY`
2. 同页 **Variables**（非敏感，可选，有默认值）：
   - `LLM_MODEL` = `deepseek-chat`（需要更强推理可填 `deepseek-reasoner`）
   - `LLM_BASE_URL` = `https://api.deepseek.com`
   - `LLM_TEMPERATURE` = `0.3`
   - `MARKET` = `a-share`
3. 打开 Actions 页，确认 **briefings** 工作流已启用。
4. 先手动测试：Actions → briefings → **Run workflow** → type 选 `post`、force 勾上 → 运行。
   成功后，前端「简报」页就能看到当天盘后复盘。

**三条定时（已配好，北京时间）**：
| 简报 | 北京时间 | cron(UTC) |
|---|---|---|
| 盘前 | 08:40 | `40 0 * * 1-5` |
| 盘中 | 13:30 | `30 5 * * 1-5` |
| 盘后 | 15:40 | `40 7 * * 1-5` |

> 说明：GitHub 定时是"尽力而为"，可能延迟几到十几分钟，属正常。非交易日脚本会自动跳过（用 akshare 交易日历判断）。
> 仓库连续 60 天无提交，定时会被 GitHub 自动停用——内置 `keepalive` 工作流每周提交一次时间戳来保活。

---

## 4. 本地跑定时任务（可选，用于调试数据源）
```bash
cd etf-strategy-workbench
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r jobs/requirements.txt
cp jobs/.env.example jobs/.env                       # 填 Supabase + DeepSeek
python -m jobs.postmarket force                      # force=跳过交易日判断
```

---

## 5. 省钱与安全要点
- **页面浏览零 token**：简报后台预生成入库，前端只读缓存；只有定时任务/手动 dispatch 才调用 DeepSeek。
- **DeepSeek 自动缓存**：System Prompt 作为稳定前缀，命中上下文缓存自动降价，无需手动配置。
- `service_role` / `DEEPSEEK_API_KEY` 只在 GitHub Secrets 与本地 `.env`；`.gitignore` 已排除 `.env*`。
- 数据源全部公开免费（akshare / yfinance），不接券商、不自动交易、不挂单。
