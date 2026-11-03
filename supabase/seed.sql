-- ======================================================================
-- 可选示例数据（seed）。演示三类标的 + 军工黑名单 + 格雷厄姆档位。
-- 执行前请确认 schema.sql 已跑过。可按需修改/删除。
-- ======================================================================

-- 标的池
insert into instruments (code, name, currency, channel, frameworks, in_circle, blacklist, dividend_tax_rate, benchmark_index, sort_order) values
  ('510300.SH', '沪深300ETF',     'CNY', 'a_etf',      '{munger,dalio,graham}', true,  false, 0,    'hs300',   10),
  ('513180.SH', '恒生科技指数ETF', 'CNY', 'qdii',       '{munger,dalio,graham}', true,  false, 0,    'hstech',  20),  -- 人民币跨境ETF：投资人层面无红利税/汇兑
  ('510880.SH', '红利ETF',        'CNY', 'a_etf',      '{munger,graham}',       true,  false, 0,    'dividend',30),
  ('512660.SH', '军工ETF',        'CNY', 'a_etf',      '{graham}',              false, true,  0,    null,      40)   -- 黑名单：永久禁止加仓
on conflict (code) do nothing;

-- 若你是通过【港股通直接持有港股/港股ETF】，示例（HKD + 20%红利税 + 需汇兑拆分）：
-- insert into instruments (code, name, currency, channel, frameworks, in_circle, blacklist, dividend_tax_rate, benchmark_index, sort_order)
-- values ('03033.HK', '南方恒生科技(港股通)', 'HKD', 'hk_connect', '{munger,dalio,graham}', true, false, 0.20, 'hstech', 25)
-- on conflict (code) do nothing;

-- 格雷厄姆标的级规则 + 档位（以沪深300ETF为例）
do $$
declare hs uuid; qd uuid;
begin
  select id into hs from instruments where code='510300.SH';
  select id into qd from instruments where code='513180.SH';

  insert into graham_rules (instrument_id, max_capital, cooldown_days, anchor_mode, recent_high_lookback)
  values (hs, 100000, 5, 'cost', 60), (qd, 60000, 7, 'recent_high', 60)
  on conflict (instrument_id) do nothing;

  insert into graham_tiers (instrument_id, tier_index, drawdown_pct, add_amount) values
    (hs, 1, 5,  10000), (hs, 2, 10, 15000), (hs, 3, 18, 20000),
    (qd, 1, 8,  8000),  (qd, 2, 15, 12000), (qd, 3, 25, 15000)
  on conflict (instrument_id, tier_index) do nothing;

  insert into take_profit_rules (instrument_id, target_return_pct, batches) values
    (hs, 30, '[{"trigger_return":20,"sell_ratio":0.25},{"trigger_return":35,"sell_ratio":0.5}]'::jsonb)
  on conflict (instrument_id) do nothing;

  insert into reserve_allocations (instrument_id, allocated) values (hs, 45000), (qd, 35000)
  on conflict (instrument_id) do nothing;
end $$;

update reserve set total_reserve = 150000, updated_at = now() where id = 1;

-- 对应估值基准指数（供数据任务抓取 PE/PB/分位）
insert into benchmarks (date, index_code, close, source) values
  (current_date, 'hs300',    0, 'seed'),
  (current_date, 'hstech',   0, 'seed'),
  (current_date, 'dividend', 0, 'seed')
on conflict (date, index_code) do nothing;
