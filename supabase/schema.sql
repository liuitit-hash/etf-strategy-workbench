-- ======================================================================
-- ETF 策略校准工作台 — Supabase 数据库结构
-- ----------------------------------------------------------------------
-- 单人自用。写入走 Supabase Auth 登录账号 + RLS；
-- 定时任务（GitHub Actions）用 service_role key 绕过 RLS 写缓存/简报。
-- 核心约束：trades（交易流水）禁止 DELETE，只允许 INSERT 与备注更正。
-- 在 Supabase 控制台 SQL Editor 一次性粘贴执行即可。
-- ======================================================================

-- ---------- 枚举 ----------
do $$ begin
  create type currency_t   as enum ('CNY','HKD');
  create type channel_t    as enum ('a_etf','hk_connect','qdii');   -- A股上市ETF / 港股通直接持股 / QDII跨境
  create type framework_t  as enum ('munger','dalio','graham');
  create type side_t        as enum ('buy','sell');
  create type action_tag_t as enum ('strategy','emotional','planned_tp'); -- 按策略触发/情绪化提前/计划内止盈
  create type briefing_t   as enum ('pre','intra','post');
  create type anchor_mode_t as enum ('cost','recent_high','manual');
exception when duplicate_object then null; end $$;

-- ======================================================================
-- 模块1：策略配置（基准契约，一旦保存即永久校验基准）
-- ======================================================================

create table if not exists instruments (
  id                uuid primary key default gen_random_uuid(),
  code              text not null unique,            -- ETF代码，如 510300.SH / 513180.SH
  name              text not null,
  currency          currency_t  not null default 'CNY',
  channel           channel_t   not null default 'a_etf',
  frameworks        framework_t[] not null default '{munger,dalio,graham}',
  in_circle         boolean not null default true,   -- 能力圈标记（芒格框架校验读取）
  blacklist         boolean not null default false,  -- 永久禁止加仓，仅可止盈减仓（如军工ETF）
  dividend_tax_rate numeric not null default 0,       -- 港股通直接持股=0.20；人民币ETF=0
  benchmark_index   text,                             -- 该标的对应的估值指数代码（取PE/PB/分位），如 hstech/hs300/dividend
  active            boolean not null default true,
  sort_order        int not null default 0,
  note              text,
  created_at        timestamptz not null default now()
);

-- 格雷厄姆梯度加仓 —— 标的级参数
create table if not exists graham_rules (
  instrument_id        uuid primary key references instruments(id) on delete cascade,
  max_capital          numeric not null,              -- 单标的总资金上限（投入本金口径）
  cooldown_days        int not null default 0,        -- 加仓冷却间隔（天）
  anchor_mode          anchor_mode_t not null default 'cost', -- 回撤基准：持仓成本/近期高点/手动锚
  anchor_price         numeric,                        -- anchor_mode='manual' 时使用
  recent_high_lookback int not null default 60         -- anchor_mode='recent_high' 回看交易日数
);

-- 格雷厄姆梯度加仓 —— 档位（按回撤浮亏百分比，逐档加仓）
create table if not exists graham_tiers (
  id            uuid primary key default gen_random_uuid(),
  instrument_id uuid not null references instruments(id) on delete cascade,
  tier_index    int not null,                          -- 第几档，从1开始
  drawdown_pct  numeric not null,                      -- 触发回撤%（正数，8 表示较锚点回撤8%）
  add_amount    numeric not null,                      -- 到达本档允许加仓的金额
  unique (instrument_id, tier_index)
);

-- 止盈规则
create table if not exists take_profit_rules (
  instrument_id     uuid primary key references instruments(id) on delete cascade,
  target_price      numeric,                            -- 止盈目标价（可空）
  target_return_pct numeric,                            -- 止盈目标收益率%（可空）
  batches           jsonb not null default '[]'::jsonb  -- 分批止盈 [{"trigger_return":20,"sell_ratio":0.3}, ...]
);

-- ======================================================================
-- 子弹储备池（资金分配）
-- ======================================================================

create table if not exists reserve (
  id            int primary key default 1 check (id = 1),  -- 固定单行
  total_reserve numeric not null default 0,                -- 总预备资金
  updated_at    timestamptz not null default now()
);
insert into reserve (id, total_reserve) values (1, 0) on conflict (id) do nothing;

create table if not exists reserve_allocations (
  instrument_id uuid primary key references instruments(id) on delete cascade,
  allocated     numeric not null default 0                 -- 分配给该标的的加仓额度
);

-- ======================================================================
-- 模块2：交易流水（只增不删；更正仅限备注）
-- ======================================================================

create table if not exists trades (
  id                uuid primary key default gen_random_uuid(),
  trade_time        timestamptz not null,
  instrument_id     uuid not null references instruments(id),
  side              side_t not null,
  shares            numeric not null check (shares > 0),
  price             numeric not null check (price > 0),     -- 成交单价（计价币种）
  fee               numeric not null default 0,
  fx_rate           numeric,                                 -- 成交时对CNY汇率（HKD标的用于汇兑拆分，CNY标的=1）
  dividend_cash     numeric not null default 0,              -- 本笔为现金分红事件时填写（税前）
  dividend_reinvest boolean not null default false,          -- 分红再投
  action_tag        action_tag_t not null,
  note              text,
  correction_note   text,                                    -- 只允许备注更正，不删历史流水
  discipline        jsonb,                                   -- 校验结果 {ok, flags:[], reason, checked_by}
  created_at        timestamptz not null default now()
);
create index if not exists idx_trades_inst_time on trades (instrument_id, trade_time);

-- ======================================================================
-- 模块4：自动数据看板缓存（定时任务写入）
-- ======================================================================

create table if not exists market_quotes (
  instrument_id        uuid not null references instruments(id) on delete cascade,
  date                 date not null,
  close                numeric,            -- 场内收盘价（计价币种）
  nav                  numeric,            -- 基金净值（若可得）
  pe                   numeric,            -- 对应指数 PE
  pb                   numeric,            -- 对应指数 PB
  dividend_yield       numeric,            -- 股息率 %
  valuation_percentile numeric,            -- 估值历史分位 0-100
  source               text,
  fetched_at           timestamptz not null default now(),
  primary key (instrument_id, date)
);

create table if not exists macro_data (
  date       date not null,
  metric     text not null,   -- us10y / dxy / southbound_net / dr007 / usdcnh / hkdcnh
  value      numeric,
  source     text,
  fetched_at timestamptz not null default now(),
  primary key (date, metric)
);

create table if not exists benchmarks (
  date       date not null,
  index_code text not null,   -- hs300 / hstech / dividend / 自定义
  close      numeric,
  pct_change numeric,
  source     text,
  primary key (date, index_code)
);

create table if not exists news_items (
  id         uuid primary key default gen_random_uuid(),
  date       date not null,
  title      text not null,
  summary    text,            -- 只存摘要，不做主观解读
  source     text,
  url        text,
  matched    jsonb not null default '[]'::jsonb,  -- 命中的标的 code 列表
  created_at timestamptz not null default now()
);
create index if not exists idx_news_date on news_items (date);

-- ======================================================================
-- 模块5：简报（后台预生成入库；前端只读，不消耗 token）
-- ======================================================================

create table if not exists briefings (
  id          uuid primary key default gen_random_uuid(),
  date        date not null,
  type        briefing_t not null,
  version     int not null default 1,
  markdown    text not null,
  model       text,
  token_usage jsonb,
  inputs      jsonb,          -- 生成时的数据/校验快照，供模块6历史回溯
  created_at  timestamptz not null default now(),
  unique (date, type, version)
);
create index if not exists idx_briefings_date_type on briefings (date, type);

-- ======================================================================
-- 视图
-- ======================================================================

-- 每个标的最近一条行情
create or replace view v_latest_quote as
select distinct on (instrument_id) *
from market_quotes
order by instrument_id, date desc;

-- 策略执行率：买入笔数中符合纪律（discipline.ok 为真或未校验）的占比
create or replace view v_execution_rate as
select
  count(*) filter (where side='buy')                                                      as total_buys,
  count(*) filter (where side='buy' and coalesce((discipline->>'ok')::boolean, true))      as ok_buys,
  count(*) filter (where side='buy' and action_tag='emotional')                           as emotional_buys,
  round(100.0 * count(*) filter (where side='buy' and coalesce((discipline->>'ok')::boolean, true))
        / nullif(count(*) filter (where side='buy'), 0), 1)                               as execution_rate_pct
from trades;

-- ======================================================================
-- RLS（行级安全）
-- 配置表：登录账号可增删改查（含删除标的/档位）。
-- trades：登录账号只可 select / insert / update（无 delete policy => 无法删除）。
-- 缓存与简报表：登录账号只读；写入由定时任务 service_role（自动绕过 RLS）完成。
-- ======================================================================

-- 配置类（全权限）
do $$
declare t text;
begin
  foreach t in array array[
    'instruments','graham_rules','graham_tiers','take_profit_rules',
    'reserve','reserve_allocations'
  ] loop
    execute format('alter table %I enable row level security;', t);
    execute format($p$create policy "auth_all" on %I for all to authenticated using (true) with check (true);$p$, t);
  end loop;
exception when duplicate_object then null; end $$;

-- trades：可读、可插、可改备注；禁止删除
do $$ begin
  alter table trades enable row level security;
  create policy "trades_select" on trades for select to authenticated using (true);
  create policy "trades_insert" on trades for insert to authenticated with check (true);
  create policy "trades_update" on trades for update to authenticated using (true) with check (true);
  -- 故意不建 delete policy
exception when duplicate_object then null; end $$;

-- 缓存/简报：登录账号只读
do $$
declare t text;
begin
  foreach t in array array['market_quotes','macro_data','benchmarks','news_items','briefings'] loop
    execute format('alter table %I enable row level security;', t);
    execute format($p$create policy "auth_read" on %I for select to authenticated using (true);$p$, t);
  end loop;
exception when duplicate_object then null; end $$;

-- 完成。seed 示例数据见 supabase/seed.sql（可选）。
