# Architecture

状态：**v2026-final 目标态**。落地进度见 `PLAN.md`；标注“收尾中”的内容尚未全部落地。

## 1. 定位

个人 ETF 右侧交易助手。跟踪一组 A 股和跨境 ETF 的日线趋势，生成信号、风控结果和操作建议，由人工确认执行。

- 不预测行情，只在趋势确认后跟随。
- 用多指标评分降低单一均线策略的误判。
- 用市场门控只拦截极端下行状态，不做全市场热度硬约束。
- 所有规则可回测、可解释、可从数据库复现。

不做的：日内、自动下单、LLM 生成信号、估值和赔率判断。

## 2. 分层

```text
main.py
  -> runner / scheduler / dashboard
    -> service
      -> fetcher / indicators / strategy / risk / advisor
        -> database repository
          -> SQLAlchemy schema -> PostgreSQL
```

| 层 | 路径 | 职责 |
|---|---|---|
| CLI | `main.py` | 唯一入口：初始化、每日运行、调度、仪表盘、信号重算、回测 |
| 初始化 | `init_db.py` | 建表、历史回填、调用与每日流程相同的计算 |
| 编排 | `src/runner/` | 每日流程，支持区间补算 |
| 调度 | `src/scheduler/` | 定时触发，启动即补跑，失败告警 |
| 采集 | `src/fetcher/` | BaoStock、AKShare、Tushare 数据源封装 |
| 指标 | `src/indicators/` | MA、MACD、Bollinger、RSI、Volume、ADX、ATR |
| 策略 | `src/strategy/` | `multi_indicator_scoring`，输出 `BUY / SELL / HOLD` |
| 风控 | `src/risk/` | `RiskController` + `profile_stop_loss`、`max_holding_days` |
| 建议 | `src/advisor/` | 风控、市场门控、加仓冷却、加仓预算、技术信号合成为操作建议 |
| 服务 | `src/service/` | 指标、持仓、日历、市场状态、ETF 映射、信号重算、盈亏分析 |
| 回测 | `src/backtest/` | 净值口径组合回测和四份归因报告，复用生产 advisor 与风控 |
| 数据 | `src/database/` | ORM schema 与 repository |
| 模型 | `src/models/` | Pydantic 业务模型和枚举 |
| UI | `src/dashboard/` | Streamlit 四页仪表盘 |

## 3. 每日流程

```text
STEP 1  DataManager.sync_daily()        同步 ETF 日线和 8 个指数到 T-1
STEP 2  IndicatorService                计算 7 个技术指标，写入 indicators.data
STEP 3  MarketRegimeService             计算 T-1 市场状态，写入 market_regime
STEP 4  策略                            生成 BUY / SELL / HOLD，写入 signals
STEP 5  RiskController                  对当前持仓检查 profile 止损和 90 日最大持有
STEP 6  generate_advice()               生成 operation_advice
```

区间补算：从最后一个完整派生日开始，逐日执行 STEP 2–6，直到 T-1。漏跑几天后执行一次 `run` 即可补齐。

## 4. 策略

唯一生产策略 `multi_indicator_scoring`，按 ETF 的 `volatility_group` 选择信号 profile。

low_vol（权重 35/25/15/25）：

```text
raw_score = 0.35*S_trend + 0.25*S_macd + 0.15*S_rsi + 0.25*S_bb
score = raw_score * vol_mult * adx_mult * 100
BUY  = score >= +50 且至少 2 个子信号为正
SELL = score <= -50 且至少 2 个子信号为负
```

high_vol，`high_vol_balanced`：

| 子信号 | 权重 | 依据 |
|---|---:|---|
| `S_trend` | 30% | MA20/MA60 趋势结构和价格相对短均线位置 |
| `S_macd` | 25% | DIF/DEA 动能方向 |
| `S_rsi` | 15% | RSI 修复、过热衰减 |
| `S_bb` | 15% | 布林带位置 |
| `S_volume` | 10% | 成交量相对 20 日均量 |
| `S_atr` | 5% | ATR 是否处于常态区间 |

```text
BUY  = score >= 45 且趋势门槛通过、MACD 不明显为负、ADX >= 18、至少 3 个正向确认
SELL = score <= -35，或跌破 MA20/MA60 且 MACD 转负
```

关键指标缺失时输出 HOLD，并在 `signal_meta.profile` 标注原因。

## 5. 执行规则

| 规则 | 口径 |
|---|---|
| 建仓 | 单 ETF 目标预算的 70% |
| 第一次加仓 | 15% 储备，要求浮盈且 score >= 60 |
| 第二次加仓 | 15% 储备，要求浮盈且 score >= 70 |
| 加仓次数上限 | 每个持仓周期 2 次，清仓后归零 |
| 加仓冷却 | 距最近一次买入满 5 个自然日 |
| high_vol 预算分层 | score >= 65 满额；55–65 为 80%；< 55 为 60% |
| 最长持有 | 自首次建仓起 90 个自然日 |

## 6. 风控

`RiskController` 按顺序执行两条规则，风控信号优先于策略信号。

| 规则 | 说明 |
|---|---|
| `max_holding_days` | 自 `first_entry_date` 起 ≥ 90 天强制卖出 |
| `profile_stop_loss` | 按 ETF 的 `stop_loss_profile` 判断 |

止损 profile：

| profile | 止损线 | 适用 |
|---|---|---|
| `atr_2_5` | `-clamp(2.5 × atr_pct, 8%, 15%)` | A 股高波动 |
| `fixed_8` | -8% | 跨境 ETF，默认值 |
| `none` | 不设止损 | A 股低波动 |

## 7. 市场门控

`MarketRegimeService` 读取指数日线生成市场状态，只在 advisor 中拦截买入类建议，不影响卖出和风控。

| ETF `regime_group` | 状态来源 |
|---|---|
| A 股 | 6 个宽基指数加权合成 |
| 美股 | NDX 单指数 |
| 港股 | HZ5017 单指数 |

状态：

| 状态 | 建仓 | 加仓 | `data.reason` |
|---|---|---|---|
| `NORMAL` | 不拦截 | 不拦截 | — |
| `RISK_OFF` | 降级为观望 | 降级为继续持有 | `hot_falling` / `bear_trend` / `panic` |
| `UNKNOWN` | 不拦截 | 不拦截 | 指数数据缺失 |

判定输入：20/60 日涨跌幅、close 相对 MA20/MA60、RSI14、成交额相对 20 日均值、多指数一致性。

## 8. 数据模型

9 张业务表。

| 表 | 主键 | 职责 |
|---|---|---|
| `quote` | `(code, date)` | ETF 日线 OHLCV |
| `indicators` | `(code, date)` | 技术指标 JSONB 快照 |
| `signals` | `(code, date)` | 策略信号和 `signal_meta` |
| `market_index_quote` | `(index_code, date)` | 指数日线 OHLCV 和成交额 |
| `market_regime` | `date` | 市场状态快照 |
| `operation_advice` | `(code, date)` | 每日操作建议、预算和拦截原因 |
| `positions` | `id` | 当前持仓 |
| `trade_records` | `id` | 真实交易流水 |
| `etf_mapping` | `symbol` | ETF 到市场、跟踪指数、行业、主题、`regime_group` 的映射 |

核心字段：

```text
quote:        code, date, open, high, low, close, volume

indicators:   code, date, data
data:         ma20, ma60, dif, dea, macd, bb_mid, bb_upper, bb_lower, bb_width,
              rsi, vol_ma20, vol_ratio, adx14, atr20, atr_pct

signals:      code, date, signal, strategy_version, signal_meta

market_regime: date, state, score, data

positions:    id, code, cost, shares, first_entry_date, entry_date, add_count
              first_entry_date 首次建仓日，用于 90 日持有
              entry_date       最近一次买入日，用于加仓冷却

trade_records: id, code, action, trade_date, price, shares, created_at

operation_advice: code, date, position_id, cost, pnl_pct, signal, advice,
              signal_source, target_position_ratio, target_budget_ratio,
              entry_add_step, score, market_state, stop_loss_profile,
              blocked_reason, advice_meta
```

记账约定：

- 加仓只更新成本和份额，不改动 `first_entry_date`。
- 减仓保持单位成本不变，卖出差额即已实现盈亏。
- `add_count` 从 `trade_records` 中当前持仓周期内的 ADD 计数得出。

枚举（`src/models/enums.py`）：

| 枚举 | 取值 |
|---|---|
| `SignalType` | `BUY / SELL / HOLD` |
| `TradeAction` | `BUY / ADD / REDUCE / SELL` |
| `AdviceAction` | `建仓 / 加仓 / 观望 / 不操作 / 继续持有 / 卖出` |
| `SignalSource` | `trend / stop_loss / max_holding / add_cooldown / add_budget / market_regime` |
| `MarketState` | `NORMAL / RISK_OFF / UNKNOWN` |

## 9. 数据源

| 数据 | 来源 | 说明 |
|---|---|---|
| 历史 OHLCV | Tushare `fund_daily` + `fund_adj` | 上市以来前复权回填 |
| 日常 OHLCV | BaoStock | T-1 增量，自动前复权 |
| A 股宽基指数 | BaoStock；科创50 走 AKShare | 5 + 1 个 |
| NDX | AKShare 新浪美股指数 | |
| HZ5017 | Tushare `index_global(HKTECH)`，失败回退 AKShare | |
| 交易日历 | exchange_calendars（XSHG） | |

Tushare 前复权：`adjusted_price = raw_price × current_adj_factor / latest_adj_factor`。

## 10. 命令

```bash
uv run python main.py init                    # 建表 + 历史回填 + 指标 + 信号
uv run python main.py init --symbol 588000 --start 2024-01-01
uv run python main.py run                     # 执行到 T-1，缺几天补几天
uv run python main.py schedule                # 定时调度
uv run python main.py check-data              # 数据健康，异常时非零退出
uv run python main.py dashboard               # http://localhost:18501
uv run python main.py rebuild-signals --start 2024-06-01 --end 2026-12-31
uv run python main.py backtest-portfolio --start 2016-01-01 --end 2026-12-31 --capital 100000 --cost 0.0005 --slippage 0.0001
uv run python main.py backtest-attribution    # 市场门控归因
uv run python main.py backtest-misjudge       # 亏损交易归因
uv run python main.py backtest-stop-loss      # 止损事件归因
uv run python main.py backtest-etf-tiers      # ETF A/B/C 分层
uv run pytest -q
```

## 11. 回测

唯一引擎 `src/backtest/portfolio_backtest.py`，真实账户净值口径（现金 + 持仓市值）。

- 数据来自数据库中的 `quote`、`indicators` 和 `signals`，与实盘 advisor 同源；`signals` 由生产策略生成并经 `rebuild-signals` 刷新。
- 逐日调用生产 `generate_advice` 和 `RiskController`，T+1 收盘价成交。
- 回测中的记账规则与实盘一致（持仓周期内加仓计数、首次建仓日起算持有期）。

## 12. 已知边界

- `settings.yaml`、`.env`、`docs/` 和四份本地文档不进入远程仓库。
- 27 只 ETF 中 21 只在 2019 年后上市，2016–2019 年实际可交易标的只有 3–6 只，长区间结果受渐进扩池影响。
- 回测数字随数据更新变化，以 `EXPERIMENT.md` 记录的口径和区间为准。
- 本项目用于个人研究和辅助决策，不构成投资建议。
