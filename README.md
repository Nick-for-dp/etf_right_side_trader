# ETF 右侧交易助手

ETF 右侧交易助手是一个面向 A 股和跨境 ETF 的趋势跟踪系统。它不预测行情，只在技术趋势确认后入场，在趋势走弱或风控触发时离场，并用高溢价和极端市场状态做买入类建议门控。

当前生产基线：`v2.3 gate-lite`。已完成多指标评分、ADX 趋势强度过滤、长期赔率因子、市场热度状态、真实账户净值回测、归因分析、信号重算、Streamlit 仪表盘和持仓管理。

## 核心策略

生产策略是 `multi_indicator_scoring`：

```text
raw_score = 0.35*S_trend + 0.25*S_macd + 0.15*S_rsi + 0.25*S_bb
score = raw_score * vol_mult * adx_mult * 100
BUY  = score >= 50 且至少 2 个子信号为正
SELL = score <= -50 且至少 2 个子信号为负
```

`gate-lite` 当前门控口径：

| 模块 | 处理 |
|---|---|
| 长期赔率 | `EXPENSIVE` 不硬拦截，仅保留为解释和后续软门控实验字段 |
| 溢价风险 | `odds_premium_blocked=True` 硬拦截建仓/加仓 |
| 市场热度 | 仅 `HOT_FALLING / BEAR_TREND / PANIC` 硬拦截建仓/加仓 |
| 卖出和风控 | 不受赔率或市场门控拦截 |

当前基线结果（27 ETF，2024-06-01 ~ 2026-06-03，100,000 元，真实账户净值口径）：

| 版本 | 年化收益 | 最大回撤 | Calmar | Sharpe | 胜率 | 利润因子 | 交易次数 |
|---|---:|---:|---:|---:|---:|---:|---:|
| v2.3 技术信号 | 10.27% | 21.83% | 0.4704 | 0.5428 | 47.06% | 1.6947 | 34 |
| v2.3 gate-lite | 10.55% | 21.43% | 0.4923 | 0.5540 | 47.06% | 1.7225 | 34 |

## 快速开始

```bash
# 安装依赖
uv sync

# 配置数据库和 Tushare Token（Tushare 仅历史回填需要）
cp .env.example .env

# 配置 ETF 列表、策略参数和调度时间
cp settings.yaml.example settings.yaml

# 首次初始化：建表、回填、计算指标、生成信号
uv run python main.py init

# 日常执行一次 T-1 流程
uv run python main.py run

# 启动仪表盘
uv run python main.py dashboard
```

常用命令：

```bash
uv run python main.py init --symbol 588000 --start 2024-01-01
uv run python main.py init-market --start 2024-06-01
uv run python main.py backfill-tushare --symbol 588000 --start 20180101
uv run python main.py schedule
uv run python main.py check-data

# 真实账户净值口径回测
uv run python main.py backtest-portfolio --start 2024-06-01 --end 2026-06-03

# 市场门控归因和亏损交易误判分析
uv run python main.py backtest-attribution --start 2024-06-01 --end 2026-06-03
uv run python main.py backtest-misjudge --start 2024-06-01 --end 2026-06-03

# 只重算 signals，不影响 quote / indicators
uv run python main.py rebuild-signals --start 2024-06-01 --end 2026-06-03

uv run pytest -q
```

## 项目结构

```text
main.py                       统一 CLI 入口
init_db.py                    初始化和历史回填编排
src/
  config/                     settings.yaml + .env 配置读取
  fetcher/                    BaoStock、AKShare、Tushare 数据采集
  indicators/                 MA、MACD、Bollinger、RSI、Volume、ADX、LongTermOdds
  strategy/                   交易信号生成，当前生产为 multi_indicator_scoring
  risk/                       止损、回撤止盈等风控规则链
  advisor/                    信号 x 持仓 x 溢价/市场门控 -> 操作建议
  runner/                     每日 STEP 1-5 编排
  service/                    指标、持仓、日历、信号重算、回测、盈亏等业务服务
  database/                   SQLAlchemy schema + repository
  models/                     Pydantic 业务模型
  dashboard/                  Streamlit 五页仪表盘
  backtest/                   净值回测、归因分析、误判分析、历史赔率门控回测
tests/                        指标和策略单元测试
```

## 数据链路

每日流程由 `src/runner/daily_runner.py` 串联：

```text
STEP 1  同步 quote / nav / premium_rate
STEP 2  计算技术指标和长期赔率，写入 indicators.data
STEP 2B 计算 market_regime
STEP 3  生成 BUY / SELL / HOLD，写入 signals
STEP 4  检查止损和回撤止盈
STEP 5  生成 operation_advice
```

数据源分工：

| 数据 | 来源 | 用途 |
|---|---|---|
| 历史 OHLCV | Tushare `fund_daily` + `fund_adj` | 上市以来前复权历史回填 |
| 日常 OHLCV | BaoStock | T-1 日线增量 |
| NAV/溢价率 | AKShare/EastMoney | 赔率价格基准和高溢价过滤 |
| 宽基指数 | BaoStock、AKShare、Tushare | 市场热度状态和 gate-lite 门控 |

## 仪表盘

```bash
uv run python main.py dashboard
```

默认地址为 `http://localhost:8501`。页面包含市场总览、我的持仓、ETF 详情、盈亏分析、策略对比。

## 免责声明

本项目用于个人研究和辅助决策，不构成投资建议。实际交易前请自行验证数据质量、滑点、费用、交易规则和风险承受能力。
