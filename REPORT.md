# ETF 右侧交易助手 — MVP 技术报告

> 版本 v1.0 MVP | 2026-04-29

---

## 1. 项目概述

ETF 右侧交易助手是一个基于 MA 双均线交叉的趋势跟踪量化系统。核心理念：不做预测，只做跟随 — 在趋势确认后入场（右侧交易），在趋势反转时离场。

**MVP 策略**：MA20 上穿 MA60（金叉）→ 买入；MA20 下穿 MA60（死叉）→ 卖出；持仓浮亏 ≥ 8% → 强制止损。

---

## 2. 系统架构

```
┌─────────────────────────────────────────────────────┐
│                   main.py（统一入口）                  │
│          init / run / schedule / dashboard           │
├─────────────────────────────────────────────────────┤
│  dashboard/（Streamlit UI）                           │
│  overview.py | positions.py | detail.py              │
├─────────────────────────────────────────────────────┤
│  runner/（核心编排）                                   │
│  STEP 1-5: 同步 → 指标 → 信号 → 风控 → 建议           │
├──────────┬──────────┬──────────┬────────────────────┤
│ fetcher/ │indicators│ strategy/│ risk/              │
│ 数据采集  │ 指标计算  │ 信号生成  │ 风控规则             │
├──────────┴──────────┴──────────┴────────────────────┤
│  advisor/（操作建议查表映射）                           │
├─────────────────────────────────────────────────────┤
│  service/（业务编排）                                  │
│  TradingCalendar | IndicatorService | PositionService │
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
| `indicators` | 技术指标快照（JSONB） | code, date, data `{"ma20": ..., "ma60": ...}` |
| `signals` | 策略信号 + 决策依据 | code, date, signal, strategy_version, signal_meta |
| `positions` | 用户持仓 | id, code, cost, shares, entry_date |
| `operation_advice` | 每日操作建议 | code, date, advice, signal_source, pnl_pct |

**设计动机**：
- `indicators` 独立于 `signals`：策略切换时指标无需重算，只重新生成信号
- `indicators.data` 使用 JSONB：新增指标列时无需 ALTER TABLE，直接写入 JSON 字段
- `signals.signal_meta` 同样 JSONB：记录 trend、交叉点等决策上下文，便于调试和回测

---

## 4. 策略引擎

### 4.1 信号生成

```
MA20 > MA60 且前一日 MA20 ≤ MA60 → BUY（金叉）
MA20 < MA60 且前一日 MA20 > MA60 → SELL（死叉）
其他 → HOLD
```

按 ETF 代码分组后逐组 shift 判断，避免跨 ETF 的伪交叉。

### 4.2 风控规则链

```
for rule in risk_rules:
    result = rule.check(position, current_price)
    if result.triggered:
        return result  # 短路，优先匹配的规则生效
```

当前规则：**硬止损** — 浮亏 ≥ 8% 触发强制卖出。规则链采用插件模式，新增规则只需实现 `BaseRiskRule` 并注册到 yaml。

### 4.3 操作建议映射

| 当前持仓 | 信号 | 建议 |
|----------|------|------|
| 空仓 | BUY | 建仓 |
| 空仓 | HOLD | 观望 |
| 空仓 | SELL | 观望 |
| 有仓 | BUY | 加仓 |
| 有仓 | HOLD | 继续持有 |
| 有仓 | SELL | 清仓 |
| 任意 | 止损触发 | 强制清仓 |

风控信号优先级高于策略信号。

---

## 5. 数据采集

双数据源合并方案：

| 数据项 | 来源 | 说明 |
|--------|------|------|
| OHLCV | BaoStock | 日线行情，免费但需登录 |
| NAV（净值） | AKShare / EastMoney | 用于计算溢价率 |

溢价率公式：`(close - nav) / nav × 100%`。NAV 空值/异常值（空字符串、NaN）已做防御处理，入库前转为 None。

---

## 6. 扩展点设计

系统预设三个标准化扩展点：

1. **策略可替换** — 新增 `strategy/ma_macd.py`，实现 `BaseStrategy` 接口，yaml 改一行 `type: "ma_macd"`，已有指标数据直接复用
2. **风控可插拔** — 新增 `risk/take_profit.py`，实现 `BaseRiskRule`，yaml 加一项 rule，链式自动执行
3. **指标可追加** — 新增 `indicators/macd.py`，实现 `BaseIndicator`，返回的 DataFrame 列自动 merge 进 JSONB

---

## 7. API 设计（命令行）

```bash
python main.py init         # 首次初始化：建表 + 回填行情 + 计算指标 + 生成信号
python main.py run          # 执行一次每日流程（STEP 1-5）
python main.py schedule     # 启动每日 07:00 定时调度（APScheduler）
python main.py dashboard    # 启动 Streamlit 仪表盘（localhost:8501）
```

---

## 8. 仪表盘

| 页面 | 功能 |
|------|------|
| 市场总览 | 全部 ETF 最新信号表格，分类筛选，BUY/SELL 颜色高亮 |
| 我的持仓 | 建仓/加仓/减仓，均价自动重算，实时浮动盈亏 |
| ETF 详情 | K 线图 + MA20/MA60 + 信号标记 + 成交量 + 指标卡片 |

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

### 10.1 盈利分析模块

当前系统能给出每日操作建议（建仓/加仓/清仓/观望），但缺少对建议的跟踪和评估：

- 缺少模拟盈亏跟踪：无法回答"如果按建议操作，当前盈亏是多少"
- 缺少胜率统计：无法统计 BUY 信号后实际上涨的概率
- 缺少信号评分：无法量化信号质量，不便于多策略对比

**建议方案**：新增 `performance` 模块，跟踪每条信号发出后 N 日的实际收益，生成信号准确率报表。可参考现有 `operation_advice` 表结构，增加 `pnl_after_n_days` 等跟踪字段。

### 10.2 ETF 列表扩充与完整初始化逻辑

当前系统通过 `init_db.py` 一次性回填所有 ETF 的历史数据。但 `init_db.py` 的 `backfill` 逻辑是针对 `settings.yaml` 中配置的全部 ETF 执行全量回填，缺少以下能力：

- **增量添加**：新增一只 ETF 到配置后，无法仅对该 ETF 执行回填，必须全量重跑
- **回填日期控制**：无法指定回填的起止日期，默认逻辑可能与已有数据冲突
- **缺少幂等性保证**：重复执行 `init` 可能产生重复数据（虽然 `ON CONFLICT DO NOTHING` 部分缓解，但指标和信号没有去重逻辑）

**建议方案**：
1. 重构 `init_db.py` 为 `python main.py init --symbol 588000 --start 2024-01-01` 形式，支持指定 ETF 和日期区间
2. `init` 命令检测已有数据，自动跳过已存在的日期范围
3. 将回填逻辑从 `init_db.py` 迁移到 `DataManager`，作为 `backfill(code, start, end)` 方法

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
│   ├── models/                     # pydantic 业务模型（5 表）
│   ├── database/
│   │   ├── connection.py           # engine 单例 + scoped_session
│   │   ├── schema/                 # SQLAlchemy ORM（含 to_model / to_orm）
│   │   └── repository/             # 纯数据访问（一张表一个文件）
│   ├── fetcher/                    # 数据采集（BaoStock + AKShare）
│   ├── indicators/                 # 技术指标（DataFrame in/out）
│   ├── strategy/                   # 策略信号（工厂模式）
│   ├── risk/                       # 风控规则链（插件模式）
│   ├── advisor/                    # 操作建议（持仓 × 信号 查表）
│   ├── runner/                     # 核心编排 STEP 1-5
│   ├── scheduler/                  # APScheduler 定时调度
│   ├── service/                    # 交易日历 / 指标编排 / 持仓管理
│   ├── dashboard/                  # Streamlit 仪表盘（3 页）
│   └── utils/                      # 日志 / 限流工具
└── tests/
```
