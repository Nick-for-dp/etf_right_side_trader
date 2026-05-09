# ETF 右侧交易助手 — 设计文档

> v1.0 MVP 已完成（2026-04-29），v1.1 已完成（2026-05-06），v1.2 已完成（2026-05-08），本文档聚焦架构设计 + 后续规划。

---

## 架构概要

```
dashboard/（Streamlit 3 页）
runner/（STEP 1-5 编排）
fetcher/ | indicators/ | strategy/ | risk/ | advisor/
service/（TradingCalendar | IndicatorService | PositionService | QuoteService）
database/（ORM schema ←→ pydantic models ←→ repository）
config/（YAML + .env）
```

三层扩展点（不动已有代码）：

| 扩展点 | 方式 | 示例 |
|--------|------|------|
| 新增指标 | 实现 `BaseIndicator.calculate(df) -> dict` | `macd.py` |
| 替换策略 | 实现 `BaseStrategy.generate(df) -> DataFrame`，yaml 改一行 | `ma_macd.py` |
| 新增风控 | 实现 `BaseRiskRule.check(pos, price) -> RiskResult`，yaml 加一项 | `take_profit.py` |

指标与信号分表（`indicators.data` JSONB + `signals`）：策略升级时指标无需重算，只重新生成信号。

---

## 版本演进

### v1.1 — MACD 辅助确认 + 工程改进 ✅（2026-05-06 完成）

**MACD 策略**（主线）：

```
金叉（MA20 > MA60）且 DIF > 0 → BUY（原逻辑加入 MACD 确认，过滤假突破）
死叉（MA20 < MA60）→ SELL（卖出不依赖 MACD，跟随趋势反转）
```

- 新增 `indicators/macd.py`：计算 DIF / DEA / MACD 柱
- 新增 `strategy/ma_cross_macd.py`：继承金叉/死叉逻辑，BUY 侧增加 `DIF > 0` 条件
- yaml 改一行 `type: "ma_cross_macd"`
- 历史 MACD 指标通过 `IndicatorService` 增量回填

实际实现：
- `indicators/macd.py` — MACD 三线（DIF / DEA / MACD 柱），Wilder 平滑
- `strategy/ma_cross_macd.py` — 独立策略类，BUY = 金叉 + DIF > 0，SELL = 死叉
- `strategy/factory.py` + `settings_reader.py` — 新增 `"ma_cross_macd"` 策略类型
- 所有模块注册 MACD 计算器（`daily_runner.py` / `init_db.py`）

**ETF 增量初始化**（工程改进）✅：

- `python main.py init --symbol 588000 --start 2024-01-01` 支持单只 ETF 回填
- 自动检测已有数据，跳过已覆盖的日期范围
- 回填逻辑已迁移到 `DataManager` 中，`init_system` 可直接传参调用

### v1.2 — 回撤止盈 + 盈利分析 ✅（2026-05-08 完成）

**Day 1：回撤止盈 ✅（2026-05-07 完成）**

新增 `risk/trailing_stop.py`：浮盈 10% 激活，从持仓期间最高点回撤 3% 触发 SELL。与止损规则在 `RiskController` 中链式执行，短路返回。新增 `service/quote_service.py`（`QuoteService.find_max_close_between`）+ `PositionService.get_holding_map` 为规则提供峰值数据，不改 `BaseRiskRule` 接口。

**Day 2：虚拟回测盈亏分析 ✅（2026-05-08 完成）**

基于 `operation_advice` 历史重建虚拟交易对，状态机遍历建仓→加仓→卖出周期，以 advice 生成当日收盘价作为虚拟成交价。纯分析层，不新增数据库表。

- `models/virtual_trade.py` — `VirtualTrade` pydantic 模型（exit_date 为空表示未平仓）
- `service/profit_analysis_service.py` — `reconstruct_trades(code, calendar)` 全量历史重建 + `calculate_equity_curve` + `get_summary`
- `dashboard/pnl.py` — 盈亏分析页：汇总指标 + 已平仓明细 + 当前持仓 + 资金曲线，日期过滤在展示层
- `advice_repo.find_by_code` / `quote_repo.find_by_code_in_range` — 按代码查询方法

### v2.0 — 多指标综合评分

- 新增布林带、RSI、成交量指标
- 七趋势状态机 + 加权评分策略
- 策略输出综合评分而非简单 BUY/SELL

### v2.1 — 待办

- **LLM 基本面分析**：引入 LLM 对 ETF 基本面（宏观经济、行业政策、资金流向等）进行分析，作为策略信号的辅助确认维度
- **完善操作建议映射**：补充 空仓 + SELL → 持有 映射（卖出信号但无持仓时不操作），确保四个组合全部覆盖

---

## 操作建议映射（策略无关，v1.0-v2.0 不变）

| 持仓 | 信号 | 建议 |
|------|------|------|
| 空仓 | BUY | 建仓 |
| 空仓 | HOLD | 观望 |
| 持仓 | SELL | 清仓 |
| 持仓 | HOLD | 继续持有 |
| 持仓 | BUY | 加仓 |
| 任意 | 止损/止盈触发 | 强制清仓 |

风控信号优先级高于策略信号，短路执行。

---

## 数据库（5 张表）

| 表 | 职责 | 关键设计 |
|----|------|----------|
| `quote` | OHLCV + NAV + 溢价率 | (code, date) 联合主键 |
| `indicators` | 技术指标快照 | `data` JSONB，新增指标无需 ALTER TABLE |
| `signals` | 策略信号 | `signal_meta` JSONB 记录决策依据，`strategy_version` 标记版本 |
| `positions` | 用户持仓 | `id` 自增主键，`code` 唯一 |
| `operation_advice` | 每日操作建议 | 信号 × 持仓查表结果，`signal_source` 标记来源 |
