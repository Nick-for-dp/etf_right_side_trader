# ETF 右侧交易助手

> 多指标综合评分的 ETF 趋势跟踪系统，v2.1A 已完成（2026-05-24）。

## 交易策略

**V1.x（已存档）**：
```
趋势判断：MA20 > MA60 → 上升；MA20 < MA60 → 下降
买入信号：MA20 上穿 MA60（金叉）且 MACD DIF > 0（过滤无动能假突破）
卖出信号：MA20 下穿 MA60（死叉）
风控覆盖：① 止损 — 浮亏 ≥ 8% 强制卖出；② 回撤止盈 — 浮盈 10% 后回撤 3% 强制卖出
```

**V2.0（当前生产）**：多指标综合评分，趋势/动能/RSI/布林带四子信号加权求和（0.35/0.25/0.15/0.25）→ -100~+100 连续评分。Volume 作为置信度乘数（仅衰减不放大），连续函数直接算分不做状态机，±50 阈值 + ≥2 子信号一致性双重条件映射 BUY/SELL/HOLD。加仓冷却期 5 自然日。

操作建议映射：

| 持仓 | 信号 | 建议 |
|------|------|------|
| 空仓 | BUY | 建仓 |
| 空仓 | HOLD | 观望 |
| 持仓 | SELL | 清仓 |
| 持仓 | HOLD | 继续持有 |
| 持仓 | BUY | 加仓 |
| 任意 | 止损/止盈触发 | 强制清仓 |

## 项目结构

```
etf_right_side_trader/
├── main.py                     # 统一 CLI 入口
├── init_db.py                  # 系统初始化（全量 / 增量回填）
├── settings.yaml               # 策略参数 / ETF 列表 / 调度配置
├── .env                        # 数据库连接信息（不入库）
├── src/
│   ├── config/                 # YAML + .env 双源配置加载
│   ├── models/                 # pydantic 业务模型（5 张表）
│   ├── database/
│   │   ├── connection.py       # SQLAlchemy engine 单例 + scoped_session
│   │   ├── schema/             # ORM 映射（含 to_model / to_orm）
│   │   └── repository/         # 纯数据访问层，一张表一个文件
│   ├── fetcher/                # 数据采集（BaoStock + AKShare → OHLCV + NAV）
│   ├── indicators/             # 技术指标：MA / MACD / 布林带 / RSI / 成交量（DataFrame in/out）
│   ├── strategy/               # 策略信号生成（工厂模式，可替换）
│   ├── risk/                   # 风控规则链（插件模式）
│   ├── advisor/                # 信号 × 持仓 → 操作建议（策略无关）
│   ├── runner/                 # 核心编排：串联 STEP 1-5
│   ├── scheduler/              # APScheduler 定时任务
│   ├── service/                # 交易日历 / 指标编排 / 持仓管理 / 盈亏分析
│   ├── dashboard/              # Streamlit 仪表盘（5 个标签页）
│   └── utils/                  # 日志 / 限流
└── tests/
```

## 数据库（PostgreSQL，5 张表）

| 表 | 职责 | 核心字段 |
|----|------|----------|
| `quote` | 日线 OHLCV + NAV | code, date, open, high, low, close, volume, nav, premium_rate |
| `indicators` | 技术指标快照（JSONB） | code, date, data `{"ma20": ..., "ma60": ..., "dif": ..., "rsi": ..., "bb_mid": ..., "vol_ratio": ...}` |
| `signals` | 策略信号 + 决策依据 | code, date, signal, strategy_version, signal_meta |
| `positions` | 用户持仓 | id, code, cost, shares, entry_date |
| `operation_advice` | 每日操作建议 | code, date, advice, signal_source, pnl_pct |

指标与信号分表存储：策略切换时指标无需重算，只重新生成信号。

## 快速开始

```bash
# 1. 安装依赖
uv sync

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 PostgreSQL 连接信息

# 3. 配置策略和 ETF 列表
cp settings.yaml.example settings.yaml
# 编辑 settings.yaml

# 4. 首次初始化（建表 + 回填数据）
uv run python main.py init

# 增量添加单只 ETF（可选）
uv run python main.py init --symbol 588000 --start 2024-01-01

# 5. 日常使用
uv run python main.py run              # 手动执行一次
uv run python main.py schedule         # 启动每日 07:00 定时调度
uv run python main.py dashboard        # 启动仪表盘 → http://localhost:8501
uv run python main.py backtest-odds    # V2.0 vs V2.1A 赔率门控回测对比
```

## 仪表盘

| 页面 | 功能 |
|------|------|
| 市场总览 | 全部 ETF 最新信号表格，分类筛选，BUY/SELL 颜色高亮 |
| 我的持仓 | 建仓/加仓（均价自动重算）/减仓，实时浮动盈亏，操作建议 |
| ETF 详情 | K线图 + MA20/MA60 + BUY/SELL 信号标记 + 成交量 + 指标卡片 |
| 盈亏分析 | 基于策略建议的虚拟回测：汇总指标、已平仓交易明细、当前持仓、资金曲线 |
| 策略对比 | V1.2 vs V2.0 同数据源双策略回测：汇总卡片、资金曲线叠加、按 ETF 明细、交易散点图 |

## 已实现

- [x] 配置层：YAML + .env 双源加载
- [x] 数据层：5 张表 ORM + pydantic 双向转换 + Repository 纯数据访问
- [x] 连接池：SQLAlchemy engine 单例，pool_pre_ping + scoped_session
- [x] 数据采集：BaoStock OHLCV + AKShare NAV 合并，溢价率计算
- [x] 交易日历：exchange_calendars 封装
- [x] 指标计算：MA20/MA60 + MACD（DIF/DEA/MACD柱） + 布林带 + RSI-14 + 成交量，BaseIndicator 抽象，IndicatorService 编排
- [x] 信号生成：双均线交叉 + MACD 确认策略（金叉+DIF>0→BUY / 死叉→SELL），工厂模式
- [x] 风控系统：8% 止损 + 回撤止盈（10%/3%），插件链模式
- [x] 操作建议：持仓 × 信号查表映射，风控信号优先
- [x] 核心编排：STEP 1-5 自动化
- [x] 定时调度：APScheduler 每日 07:00
- [x] 数据初始化：一键建表 + 全量/增量回填（`--symbol` + `--start`）
- [x] 仪表盘：5 标签页 Streamlit UI
- [x] 策略对比回测：V1.2 vs V2.0 同数据源双策略对比（BacktestComparison 引擎）
- [x] 持仓管理：建仓/加仓均价重算/减仓
- [x] MACD 指标全量落地：dif / dea / macd 三线存入 JSONB
- [x] 盈亏分析：基于策略建议的虚拟回测（建仓→卖出配对、资金曲线、胜率统计）

## 三个扩展点

1. **策略可替换**：新增 `strategy/ma_macd.py` + 改一行 yaml，已有指标直接复用
2. **风控可插拔**：新增 `risk/take_profit.py` + yaml 加一项 rule，规则链自动执行
3. **指标可追加**：新增 `indicators/macd.py`，返回的 DataFrame 列 merge 进 JSONB，无需 ALTER TABLE

## 版本演进

| 版本 | 目标 | 状态 |
|------|------|------|
| v1.1 | MACD 辅助确认（金叉 + DIF > 0 才买）+ ETF 增量初始化 | ✅ |
| v1.2 | 回撤止盈（浮盈 10% 后回撤 3% 触发）+ 虚拟回测盈亏分析 | ✅ |
| v2.0 | 多指标综合评分（趋势/动能/RSI/布林带 → 连续评分 -100~+100） + 策略对比回测 | ✅ 已完成（2026-05-14） |
| v2.1A | 长期赔率因子 + 开仓门控（5 子因子加权 → CHEAP/FAIR/EXPENSIVE） | ✅ 已完成（2026-05-24） |
| v2.1B | 轻量持有体验辅助（`fund_individual_profit_probability_xq`） | 规划中 |
| v3.0 | PE/PB 估值分位 + 回测框架参数优化 | 规划中 |
