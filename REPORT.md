# ETF 右侧交易助手 — MVP 技术报告

> 版本 v2.1A 已完成 | 2026-05-24

---

## 1. 项目概述

ETF 右侧交易助手是一个基于 MA 双均线交叉的趋势跟踪量化系统。核心理念：不做预测，只做跟随 — 在趋势确认后入场（右侧交易），在趋势反转时离场。

**当前策略（v2.0，生产环境）**：四子信号加权求和（0.35/0.25/0.15/0.25），趋势/动能/RSI/布林带 → -100~+100 连续评分。Volume 作为置信度乘数（仅衰减不放大），±50 阈值 + ≥2 子信号一致性双重条件映射 BUY/SELL/HOLD。加仓冷却期 5 自然日。

**V2.0 策略（当前生产）**：多指标综合评分，四个子信号（趋势/动能/RSI/布林带）加权求和 → -100~+100 连续评分。Volume 作为置信度乘数，连续函数直接算分不做状态机。±50 阈值 + ≥2 子信号一致性双重条件映射 BUY/SELL/HOLD。

**风控（v1.2）**：两条规则链式执行 — ① 止损：浮亏 ≥ 8% 强制卖出；② 回撤止盈：浮盈触及 10% 后从最高点回撤 ≥ 3% 触发卖出。

---

## 2. 系统架构

```
┌─────────────────────────────────────────────────────┐
│                   main.py（统一入口）                  │
│          init / run / schedule / dashboard           │
├─────────────────────────────────────────────────────┤
│  dashboard/（Streamlit UI）                           │
│  overview.py | positions.py | detail.py | pnl.py     │
├─────────────────────────────────────────────────────┤
│  runner/（核心编排）                                   │
│  STEP 1-5: 同步 → 指标 → 信号 → 风控 → 建议           │
├──────────┬──────────┬──────────┬────────────────────┤
│ fetcher/ │indicators│ strategy/│ risk/              │
│ 数据采集  │ 指标计算  │ 信号生成  │ 风控规则             │
├──────────┴──────────┴──────────┴────────────────────┤
│  advisor/（操作建议查表映射）                           │
├─────────────────────────────────────────────────────┤
│  service/（业务编排）                                                       │
│  TradingCalendar | IndicatorService | PositionService | QuoteService | ProfitAnalysis │
├─────────────────────────────────────────────────────┤
│  database/                                           │
│  ORM schema ←→ pydantic models ←→ repository        │
├─────────────────────────────────────────────────────┤
│  config/（YAML + .env 双源加载）                       │
└─────────────────────────────────────────────────────┘
```

**分层原则**：
- `models/` — pydantic 业务模型，与 ORM 双向转换（`to_orm()` / `to_model()`）
- `database/schema/` — SQLAlchemy ORM 映射，纯表结构
- `database/repository/` — 纯数据访问，一张表一个文件，不含业务逻辑
- `service/` — 业务编排，调用 repository，可被 runner 和 dashboard 共用
- `dashboard/` — Streamlit UI，只做交互和数据展示，不写业务逻辑
- `runner/` — 核心编排，串联每日 5 步流程

---

## 3. 数据库设计

| 表 | 职责 | 核心字段 |
|----|------|----------|
| `quote` | 日线 OHLCV + NAV | code, date, open, high, low, close, volume, nav, premium_rate |
| `indicators` | 技术指标快照（JSONB） | code, date, data `{"ma20": ..., "ma60": ..., "dif": ..., "dea": ..., "macd": ..., "bb_mid": ..., "rsi": ..., "vol_ratio": ...}` |
| `signals` | 策略信号 + 决策依据 | code, date, signal, strategy_version, signal_meta |
| `positions` | 用户持仓 | id, code, cost, shares, entry_date |
| `operation_advice` | 每日操作建议 | code, date, advice, signal_source, pnl_pct |

**设计动机**：
- `indicators` 独立于 `signals`：策略切换时指标无需重算，只重新生成信号
- `indicators.data` 使用 JSONB：新增指标列时无需 ALTER TABLE，直接写入 JSON 字段
- `signals.signal_meta` 同样 JSONB：记录 trend、交叉点等决策上下文，便于调试和回测

---

## 4. 策略引擎

### 4.1 信号生成（v2.0）

四子信号加权求和（0.35/0.25/0.15/0.25）→ -100~+100 连续评分。Volume 置信度乘数（0.85~1.0，仅衰减不放大）。±50 阈值 + ≥2 子信号一致性双重条件映射 BUY/SELL/HOLD。S_trend 系数 15/10（延缓饱和），S_macd 系数 60/30（真实参与评分）。加仓冷却期 5 自然日。详见 PLAN.md 子信号设计章节。

### 4.2 风控规则链

```
for rule in risk_rules:
    result = rule.check(position, current_price)
    if result.triggered:
        return result  # 短路，优先匹配的规则生效
```

当前规则（两条，按配置顺序执行）：

| 规则 | 类型 | 触发条件 | 职责 |
|------|------|----------|------|
| 硬止损 | `stop_loss` | 浮亏 ≥ 8% | 防止亏损扩大 |
| 回撤止盈 | `trailing_stop` | 浮盈先触 10%，再从高点回撤 3% | 防止盈利变亏损 |

规则链采用插件模式，新增规则只需实现 `BaseRiskRule` 并注册到 yaml。`trailing_stop` 通过 `QuoteService.find_max_close_between` 获取持仓期间最高点，`PositionService.get_holding_map` 提供建仓日映射，规则本体保持无状态。

### 4.3 操作建议映射

| 当前持仓 | 信号 | 建议 |
|----------|------|------|
| 空仓 | BUY | 建仓 |
| 空仓 | HOLD | 观望 |
| 空仓 | SELL | 观望 |
| 有仓 | BUY | 加仓 |
| 有仓 | HOLD | 继续持有 |
| 有仓 | SELL | 清仓 |
| 任意 | 止损/止盈触发 | 强制清仓 |

风控信号优先级高于策略信号。

---

## 5. 数据采集

三数据源分层方案：

```
Tushare fund_daily + fund_adj       ← 全量历史 OHLCV（手动前复权）
BaoStock query_history_k_data_plus  ← 日常增量 OHLCV（自动前复权）
AKShare/EastMoney                   ← NAV 净值 + 溢价率
```

| 数据项 | 来源 | 说明 |
|--------|------|------|
| OHLCV（历史回填） | Tushare `fund_daily` + `fund_adj` | 不复权原始数据 + 复权因子 → 手动前复权，覆盖 ETF 上市以来全量历史 |
| OHLCV（日常增量） | BaoStock | 日线行情，自动前复权，覆盖近 ~6 个月 |
| NAV（净值） | AKShare / EastMoney | 用于计算溢价率，Tushare 不提供此字段 |

### Tushare 历史回填链路（v2.1-prep，2026-05-23）

`HistoryFetcher` 封装 Tushare 数据拉取，核心流程：

```
fund_daily（不复权 OHLCV） + fund_adj（复权因子）
    → left merge + ffill 补齐缺失因子
    → 前复权 = 原始价格 × 当日因子 / 最新因子
    → 单位转换：amount 千元→元
    → 写入 quote 表（ON CONFLICT DO NOTHING，已有 NAV 不覆盖）
```

CLI 命令：`python main.py backfill-tushare [--symbol X] [--start YYYYMMDD]`

### 前复权验证：515050 通信ETF华夏 拆分

2026-05-13 发生 3:1 拆分（量扩大三倍，价格变为 1/3）。Tushare `fund_adj` 正确记录：
- 上市 ~ 2026-05-12：`adj_factor = 1.0`
- 2026-05-13 起：`adj_factor = 3.0`

全量 5 年交叉验证（2019-10 ~ 2026-05，5 个时间点）：diff=0.0000，价格序列连续无断崖。

溢价率公式：`(close - nav) / nav × 100%`。NAV 空值/异常值（空字符串、NaN）已做防御处理，入库前转为 None。

---

## 6. 扩展点设计

系统预设三个标准化扩展点（v1.0 设计，v1.1 已验证）：

1. **策略可替换** — 新增 `strategy/ma_cross_macd.py`，实现 `BaseStrategy` 接口，yaml 改一行 `type: "ma_cross_macd"`，已有指标数据直接复用 ✅
2. **风控可插拔** — 新增 `risk/take_profit.py`，实现 `BaseRiskRule`，yaml 加一项 rule，链式自动执行
3. **指标可追加** — 已有 `indicators/macd.py`，实现 `BaseIndicator`，返回的 DataFrame 列自动 merge 进 JSONB ✅

---

## 7. API 设计（命令行）

```bash
python main.py init                              # 首次初始化：建表 + 回填 + 指标 + 信号
python main.py init --symbol 588000              # 增量回填单只 ETF
python main.py init --symbol 588000 --start 2024-01-01
python main.py run                               # 执行一次每日流程（STEP 1-5）
python main.py schedule                          # 启动每日 07:00 定时调度（APScheduler）
python main.py dashboard                         # 启动 Streamlit 仪表盘（localhost:8501）
```

---

## 8. 仪表盘

| 页面 | 功能 |
|------|------|
| 市场总览 | 全部 ETF 最新信号表格，分类筛选，BUY/SELL 颜色高亮 |
| 我的持仓 | 建仓/加仓/减仓，均价自动重算，实时浮动盈亏 |
| ETF 详情 | K 线图 + MA20/MA60 + 信号标记 + 成交量 + 指标卡片 |
| 盈亏分析 | 虚拟回测：汇总指标、已平仓交易明细、当前虚拟持仓、资金曲线 |
| 策略对比 | V1.2 vs V2.0 同数据源双策略回测：汇总卡片、资金曲线叠加、按 ETF 明细、交易散点图 |

---

## 9. 技术栈

| 类别 | 选型 | 理由 |
|------|------|------|
| 语言 | Python 3.13 | — |
| 数据库 | PostgreSQL + SQLAlchemy 2.0 | ORM + 连接池，Streamlit 线程安全 |
| 前端 | Streamlit 1.56 | 纯 Python，MVP 快速交付 |
| 图表 | Plotly 5.24 | K 线图 + 指标叠加，交互式 |
| 定时 | APScheduler 3.10 | 轻量，CronTrigger 每日调度 |
| 数据源 | BaoStock + AKShare | 免费，覆盖 OHLCV + NAV |
| 交易日历 | exchange_calendars | XSHG 交易所日历 |
| 配置 | YAML + python-dotenv | 策略配置公开，密钥私密 |
| 包管理 | uv | 速度快，lock 文件可复现 |

---

## 10. 待完成

### 10.1 回撤止盈 ✅（v1.2 Day 1，2026-05-07 完成）

新增 `risk/trailing_stop.py` + `service/quote_service.py`，浮盈 10% 后回撤 3% 触发止盈。与止损规则链式执行。

### 10.2 虚拟回测盈亏分析 ✅（v1.2 Day 2，2026-05-08 完成，2026-05-09 优化）

基于 `operation_advice` 历史记录重建虚拟交易对：遍历 advice → 状态机匹配建仓/加仓/卖出 → 以 advice 生成当日收盘价作为虚拟成交价 → 结算已平仓交易盈亏 + 追踪未平仓浮动盈亏。

纯分析层，不新增数据库表。输出：
- `VirtualTrade` 模型（`exit_date` 为空 = 未平仓，有值 = 已平仓）
- `reconstruct_trades(code, calendar)` — 按 ETF 全量历史重建，无需指定日期范围；dashboard 层按需过滤
- `calculate_equity_curve(codes, calendar, start, end)` — 逐日模拟资金曲线
- `get_summary(trades)` — 胜率 / 累计盈亏 / 最大盈亏等指标
- Dashboard "盈亏分析"页：汇总卡片 + 已平仓明细表 + 当前虚拟持仓 + 资金曲线图

### 10.3 多指标综合评分（v2.0 S1-S3 ✅，S4 待实施）

**S1-S3 新增指标 ✅（2026-05-12 完成）**：
- `indicators/bollinger.py` — MA20 中轨 + 2σ 通道 + bb_width 带宽
- `indicators/rsi.py` — Wilder 平滑 RSI-14
- `indicators/volume.py` — 20 日均量 + vol_ratio 量比
- `IndicatorService` 改造传入完整 OHLCV（含 volume），向后兼容
- 9 个单元测试全部通过

**S4 综合评分 ✅（2026-05-13 完成，2026-05-14 参数调优）**：`strategy/multi_indicator_scoring.py`，四子信号加权求和 + Volume 置信度乘数（仅衰减不放大）→ -100~+100 连续评分。策略内部做 ±50 阈值 + ≥2 子信号一致性双重条件映射为 BUY/SELL/HOLD，下游 advisor 无需改动。权重 0.35/0.25/0.15/0.25，S_trend 系数 15/10，S_macd 系数 60/30。`settings.yaml` 切换 type 为 `"multi_indicator_scoring"` 后即刻生效，2026-05-14 已投产。

**S5 历史回填 ✅（2026-05-12 完成）**：用户通过 `init --symbol` 增量回填全部 ETF，新指标（bb_mid/bb_upper/bb_lower/bb_width/rsi/vol_ma20/vol_ratio）均已落库。

**S6 Dashboard 更新 ✅（2026-05-12 完成）**：详情页 K 线图叠加布林带 + MACD + RSI 副图 + 成交量副图，8 个指标卡片，V2.0 评分展示。

**S7 回测对比 ✅（2026-05-14 完成）**：`BacktestComparison` 引擎 + `comparison.py` 策略对比页面。同数据源运行 V1.2 vs V2.0，对比交易次数/胜率/累计收益/最大回撤，资金曲线叠加图 + 按 ETF 明细表 + 已平仓交易散点图。

### 10.4 Tushare 历史行情回填（v2.1-prep ✅，2026-05-23）

新增 `fetcher/history_fetcher.py` — Tushare `fund_daily` + `fund_adj` 手动前复权链路，作为 BaoStock+AKShare 的历史数据补充：

- `HistoryFetcher.get_etf_history_from_tushare()` — 调 Tushare API，拉取不复权日线 + 复权因子，手动计算前复权，单位转换（amount 千元→元，vol 手保持不变），输出列对齐 `Quote` 模型
- `DataManager.backfill_tushare()` — 全量/单只 ETF 一键回填，`ON CONFLICT DO NOTHING` 保护已有 NAV 不被覆盖
- CLI 命令：`python main.py backfill-tushare [--symbol X] [--start YYYYMMDD] [--end YYYYMMDD]`
- 515050 拆分验证：2026-05-13 3:1 拆分，`adj_factor` 1.0→3.0，全量 5 年交叉验证 diff=0.0000，价格连续

前复权公式：`前复权价格 = 原始价格 × 当日复权因子 / 最新复权因子`

### 10.5 长期赔率因子 + 开仓门控（v2.1A ✅，2026-05-24）

V2.1A 在 v2.0 多指标评分基础上新增**长期赔率门控**，基于 ETF 自身 3 年历史价格行为评估入场赔率，过滤追高交易。

**核心链路**：

```
LongTermOdds 指标（5 子因子加权）→ indicators.data JSONB
    → daily_runner STEP 5 提取 odds_state/score/premium_blocked
    → generate_advice(odds_map=...) 拦截 EXPENSIVE/高溢价时的建仓和加仓
```

**新增/修改文件**：

| 文件 | 变更 |
|------|------|
| `src/indicators/long_term_odds.py` | 新增：价格分位/回撤/Z-score/持有胜率/风险惩罚 5 因子加权，输出 CHEAP/FAIR/EXPENSIVE 三态 |
| `src/advisor/operation_advisor.py` | 修改：新增 `odds_map` 参数，EXPENSIVE/高溢价 → 建仓→观望、加仓→继续持有 |
| `src/service/indicator_service.py` | 修改：`_LOOKBACK_PADDING` 120→1500，price_df 新增 nav/premium_rate 列 |
| `src/runner/daily_runner.py` | 修改：STEP2 注册 LongTermOdds，STEP5 提取赔率数据传入 advisor |
| `src/dashboard/detail.py` | 修改：新增赔率评分/状态卡片 + odds_score 历史曲线副图（含三色背景带） |
| `src/backtest/odds_gate_backtest.py` | 新增：v2.0 vs v2.1A 同信号双 advisor 回测对比引擎 |
| `main.py` | 修改：新增 `backtest-odds` CLI 命令 |
| `src/fetcher/data_manager.py` | 修改：关闭 backfill() 东方财富向前补逻辑，Tushare 已覆盖全量历史 |

**588000 回测验证**（2024-01-02 ~ 2026-05-23）：

| 指标 | V2.0 (无门控) | V2.1A (有门控) |
|------|-------------|-------------|
| 已平仓交易 | 5 笔 | 4 笔 |
| 胜率 | 0% | 25% |
| 累计盈亏 | -30.8% | **+2.1%** |
| 最大回撤 | -30.7% | -23.6% |
| 买入拦截 | — | 117 次 |

赔率门控将 v2.0 追高导致的 -30.8% 累计亏损扭转为 +2.1% 正收益。

---

## 11. 文件清单

```
etf_right_side_trader/
├── main.py                         # 统一 CLI 入口
├── init_db.py                      # 首次初始化
├── daily_runner.py                 # 手动运行入口（兼容）
├── run_scheduler.py                # 定时调度入口（兼容）
├── settings.yaml                   # 策略参数 / ETF 列表 / 调度配置
├── settings.yaml.example           # 脱敏配置模板
├── .env.example                    # 环境变量模板
├── .gitignore
├── pyproject.toml
├── README.md
├── REPORT.md                       # 本报告
├── PLAN.md                         # 初始设计文档
├── src/
│   ├── config/                     # YAML + .env 双源配置加载
│   ├── models/                     # pydantic 业务模型（6 个）
│   ├── database/
│   │   ├── connection.py           # engine 单例 + scoped_session
│   │   ├── schema/                 # SQLAlchemy ORM（含 to_model / to_orm）
│   │   └── repository/             # 纯数据访问（一张表一个文件）
│   ├── fetcher/                    # 数据采集（BaoStock + AKShare + Tushare）
│   ├── indicators/                 # 技术指标：MA / MACD / 布林带 / RSI / 成交量（DataFrame in/out）
│   ├── strategy/                   # 策略信号（工厂模式，ma_cross / ma_cross_macd）
│   ├── risk/                       # 风控规则链（插件模式）
│   ├── advisor/                    # 操作建议（持仓 × 信号 查表）
│   ├── runner/                     # 核心编排 STEP 1-5
│   ├── scheduler/                  # APScheduler 定时调度
│   ├── service/                    # 日历 / 指标编排 / 持仓管理 / 行情查询 / 盈亏分析（5 个 service）
│   ├── dashboard/                  # Streamlit 仪表盘（5 页）
│   └── utils/                      # 日志 / 限流工具
└── tests/
```
