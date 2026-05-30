# Architecture

## 项目目标

ETF 右侧交易助手用于跟踪一组 ETF 的日线趋势，生成技术信号、风控信号和操作建议。系统定位是个人交易辅助工具：

- 不做价格预测，只做趋势确认后的右侧跟随。
- 用多指标评分降低单一均线策略的误判。
- 用长期赔率门控减少高位追涨建仓。
- 用市场热度门控减少全市场过热追高和过冷弱反弹买入。
- 用可复盘的数据库记录支撑 Dashboard、盈亏分析和回测比较。

## 总体架构

```text
main.py / init_db.py
  -> runner / scheduler / dashboard
    -> service
      -> fetcher / indicators / strategy / risk / advisor
        -> database repository
          -> SQLAlchemy schema
            -> PostgreSQL
```

分层职责：

| 层 | 路径 | 职责 |
|---|---|---|
| CLI | `main.py` | 统一命令入口：初始化、每日运行、调度、仪表盘、回测 |
| 初始化 | `init_db.py` | 建表、历史回填、指标回填、信号生成 |
| 编排 | `src/runner/` | 每日 STEP 1-5 主流程 |
| 采集 | `src/fetcher/` | BaoStock、AKShare/EastMoney、Tushare 数据源封装 |
| 指标 | `src/indicators/` | MA、MACD、Bollinger、RSI、Volume、LongTermOdds |
| 策略 | `src/strategy/` | 技术评分并映射 `BUY / SELL / HOLD` |
| 风控 | `src/risk/` | 止损、回撤止盈规则链 |
| 建议 | `src/advisor/` | 持仓、信号、赔率、市场热度和风控合成为操作建议 |
| 服务 | `src/service/` | 指标、持仓、行情、日历、回测等业务编排 |
| 数据 | `src/database/` | ORM schema 与 repository |
| 模型 | `src/models/` | Pydantic 业务模型 |
| UI | `src/dashboard/` | Streamlit 五页仪表盘 |

## 每日流程

`src/runner/daily_runner.py` 是生产主链路：

```text
STEP 1: DataManager.sync_daily()
        补齐配置 ETF 到 T-1 交易日的 quote / nav / premium_rate
        同步宽基指数到 T-1 交易日的 market_index_quote

STEP 2: IndicatorService.calculate_and_save()
        计算技术指标和 LongTermOdds，写入 indicators.data

STEP 2B: MarketRegimeService.calculate_and_save()
         计算 T-1 市场热度，写入 market_regime

STEP 3: create_strategy(config).generate()
        从指标生成 BUY / SELL / HOLD，写入 signals

STEP 4: RiskController.check_position()
        对当前 positions 检查止损和回撤止盈

STEP 5: generate_advice()
        风控 > 赔率门控 > 市场热度门控 > 加仓冷却 > 技术信号，生成 operation_advice
```

## 策略模型

当前生产策略：`multi_indicator_scoring`。

四个子信号：

| 子信号 | 数据 | 含义 |
|---|---|---|
| `S_trend` | `ma20/ma60/close` | 均线排列和价格相对短均线位置 |
| `S_macd` | `dif/dea/close` | 动能方向和柱线变化 |
| `S_rsi` | `rsi` | 相对强弱，极端值用衰减函数降权 |
| `S_bb` | `bb_upper/bb_lower/close` | 价格在布林带中的位置 |

评分：

```text
raw_score = 0.35*S_trend + 0.25*S_macd + 0.15*S_rsi + 0.25*S_bb
score = raw_score * vol_mult * 100
```

`vol_mult` 只衰减不放大，避免单纯放量推高信号强度。

信号映射：

```text
BUY  = score >= +50 且至少 2 个子信号为正
SELL = score <= -50 且至少 2 个子信号为负
HOLD = 其他情况
```

## 长期赔率门控

`LongTermOdds` 是 `v2.1A` 的核心增量。它不产生交易信号，只影响 advisor 对买入类建议的处理。

价格基准：

```text
P_t = nav if nav exists else close
```

子因子：

| 字段 | 含义 |
|---|---|
| `odds_price_pct` | 当前价格在长期窗口中的分位 |
| `odds_drawdown` | 当前价格相对长期窗口高点的回撤 |
| `odds_zscore` | 当前价格相对长期均值的偏离 |
| `odds_hold_winrate_1y` | 历史任意时点持有 1 年的胜率 |
| `odds_hold_avg_return_1y` | 历史任意时点持有 1 年的平均收益 |
| `odds_risk_penalty` | 年化波动和最大回撤惩罚 |
| `odds_premium_blocked` | 溢价率超过阈值时的硬过滤标记 |

状态：

```text
CHEAP       odds_score >= +30
FAIR        -30 < odds_score < +30
EXPENSIVE   odds_score <= -30
INSUFFICIENT 历史数据不足
```

advisor 门控：

| 原建议 | 条件 | 新建议 |
|---|---|---|
| 建仓 | `EXPENSIVE` 或高溢价 | 观望 |
| 加仓 | `EXPENSIVE` 或高溢价 | 继续持有 |
| 卖出 | 任意赔率状态 | 不拦截 |

## 市场热度门控

`MarketRegimeService` 读取宽基指数日线行情，生成全市场状态快照。它不产生策略信号，只在 advisor 中对买入类建议做负向门控。

覆盖指数：

| 指数 | 代码 | 日常数据源 |
|---|---|---|
| 上证指数 | `000001` | BaoStock |
| 沪深300 | `000300` | BaoStock |
| 中证500 | `000905` | BaoStock |
| 中证1000 | `000852` | BaoStock |
| 创业板指 | `399006` | BaoStock |
| 科创50 | `000688` | AKShare，东方财富成交额尽力补充 |

历史数据：

```text
HistoryFetcher.get_index_history_from_tushare()
  -> index_daily
  -> market_index_quote
```

Tushare 单位转换：

```text
volume: 手 -> 股，乘以 100
amount: 千元 -> 元，乘以 1000
```

状态定义：

```text
COLD / NORMAL / HOT / UNKNOWN
```

第一版指标：

| 指标 | 用途 |
|---|---|
| 20/60 日涨跌幅 | 判断短中期涨跌速度 |
| close 相对 MA20/MA60 | 判断指数趋势结构 |
| RSI14 | 判断过热或极弱 |
| 成交额/成交量相对 20 日均值 | 判断市场活跃度 |
| 多指数一致性 | 判断全市场共振程度 |

advisor 门控：

| 市场状态 | 建仓 | 加仓 | 卖出 |
|---|---|---|---|
| `NORMAL` | 不拦截 | 不拦截 | 不拦截 |
| `HOT` | 降级为观望 | 降级为继续持有 | 不拦截 |
| `COLD` | 降级为观望 | 降级为继续持有 | 不拦截 |
| `UNKNOWN` | 不拦截 | 不拦截 | 不拦截 |

## 加仓冷却

`trade_records` 记录用户真实交易流水，advisor 用最近一次 `BUY / ADD` 日期控制加仓频率。默认冷却期由 `strategy.params.cooldown_days` 配置，当前模板为 5 天。

规则：

| 条件 | 处理 |
|---|---|
| 空仓 + BUY | 正常提示建仓 |
| 持仓 + BUY，冷却期外 | 正常提示加仓 |
| 持仓 + BUY，冷却期内 | 降级为继续持有，`signal_source=add_cooldown` |
| SELL 或风控信号 | 不受加仓冷却影响 |

## 数据模型

当前 schema 包含 9 张业务表。

| 表 | 主键 | 职责 |
|---|---|---|
| `quote` | `(code, date)` | ETF 日线 OHLCV、NAV、溢价率 |
| `indicators` | `(code, date)` | 技术指标和长期赔率 JSONB 快照 |
| `signals` | `(code, date)` | 策略信号和 `signal_meta` |
| `positions` | `id` | 当前真实/手动维护持仓 |
| `trade_records` | `id` | 用户真实建仓、加仓、减仓、卖出流水 |
| `market_index_quote` | `(index_code, date)` | 宽基指数日线 OHLCV 和成交额 |
| `market_regime` | `date` | 市场热度状态快照 |
| `operation_advice` | `(code, date)` | 每日操作建议、成本和浮动盈亏 |
| `index_valuation` | `(index_code, date)` | 预留的指数 PE/PB 估值历史 |

核心字段：

```text
quote:
  code, date, open, high, low, close, volume, nav, premium_rate

indicators:
  code, date, data
  data: ma20, ma60, dif, dea, macd, bb_mid, bb_upper, bb_lower,
        bb_width, rsi, vol_ma20, vol_ratio, odds_*

signals:
  code, date, signal, strategy_version, signal_meta

positions:
  id, code, cost, shares, entry_date

trade_records:
  id, code, action, trade_date, price, shares, created_at
  action: TradeAction = BUY / ADD / REDUCE / SELL

market_index_quote:
  index_code, date, open, high, low, close, volume, amount

market_regime:
  date, state, score, data
  state: MarketState = COLD / NORMAL / HOT / UNKNOWN

operation_advice:
  code, date, position_id, cost, pnl_pct, signal, advice, signal_source
```

核心业务枚举集中在 `src/models/enums.py`：

| 枚举 | 取值 | 用途 |
|---|---|---|
| `SignalType` | `BUY / SELL / HOLD` | 策略信号 |
| `TradeAction` | `BUY / ADD / REDUCE / SELL` | 用户真实交易流水 |
| `AdviceAction` | `建仓 / 加仓 / 观望 / 不操作 / 继续持有 / 卖出` | advisor 输出建议 |
| `SignalSource` | `trend / stop_loss / trailing_stop / add_cooldown / market_regime` | 建议来源 |
| `MarketState` | `COLD / NORMAL / HOT / UNKNOWN` | 市场热度状态 |

## 数据源

| 来源 | 模块 | 作用 |
|---|---|---|
| BaoStock | `DailyFetcher` | 日常 OHLCV 增量，自动前复权 |
| BaoStock | `MarketIndexFetcher` | 上证、沪深300、中证500、中证1000、创业板指日常指数行情 |
| AKShare/EastMoney | `DailyFetcher` | NAV 与溢价率 |
| AKShare/EastMoney | `MarketIndexFetcher` | 科创50日常行情与成交额补充 |
| Tushare | `HistoryFetcher` | ETF 历史 OHLCV、宽基指数历史 OHLCV |
| exchange_calendars | `TradingCalendarService` | 上交所交易日历 |

Tushare 前复权公式：

```text
adjusted_price = raw_price * current_adj_factor / latest_adj_factor
```

Tushare 不提供 NAV，因此历史回填不会覆盖已有带 NAV 的 `quote` 记录。

初始化入口：

```text
main.py init
  全量初始化：建表 -> ETF 行情 -> 指数行情 -> market_regime -> ETF 指标 -> 信号

main.py init-market
  仅初始化 market_index_quote 和 market_regime，适合 ETF 数据已完成的环境
```

## 扩展点

- 新指标：新增 `BaseIndicator`，注册到 `IndicatorService` 调用方，输出列自然落入 `indicators.data`。
- 新策略：新增 `BaseStrategy`，在 `factory.py` 和 `settings_reader.py` 注册，参数写入配置。
- 新风控：新增 `BaseRiskRule`，通过配置加入规则链。
- 新展示：Dashboard 从 service/repository 取数据，不在 UI 层写策略判断。

## 已知边界

- `index_valuation` 已建模但不是当前生产链路核心，PE/PB 估值分位计划放在 v3.0。
- `settings.yaml.example` 是模板，实际 ETF 列表和密钥在本地配置中维护。
- 回测结果依赖历史数据完整性，特别是 Tushare 回填覆盖范围和 NAV 缺失情况。
- 当前 `backtest-odds` 的组合最大回撤为多 ETF 盈亏累加口径，不是真实资金账户净值口径；适合版本相对比较，不适合直接作为账户回撤结论。
- Dashboard 建仓/加仓/减仓目前先更新 `positions`，再写入 `trade_records`，两步暂未放入同一个数据库事务；若第二步失败，可能出现持仓和交易流水短暂不一致。
