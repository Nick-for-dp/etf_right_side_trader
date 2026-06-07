# ETF 右侧交易助手

ETF 右侧交易助手是一个面向 A 股和跨境 ETF 的趋势跟踪系统。它不预测行情，只在技术趋势确认后入场，在趋势走弱或风控触发时离场，并用高溢价和极端市场状态做买入类建议门控。

当前生产基线：`baseline-v2.4`。已完成多指标评分、ADX 趋势强度过滤、ATR(20) 指标、长期赔率因子、ETF 映射表、分市场热度门控、70/15/15 阶梯建仓加仓、分市场/分波动止损、90 日最大持有、真实账户净值回测、归因分析、信号重算、Streamlit 仪表盘和持仓管理。

文档入口：

| 文档 | 内容 |
|---|---|
| `RELEASE_NOTES.md` | 本次远程仓库更新说明 |

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
| 市场热度 | 按 ETF `regime_group` 获取市场状态，仅 `HOT_FALLING / BEAR_TREND / PANIC` 硬拦截建仓/加仓 |
| A 股 ETF | 使用 A 股宽基综合 `market_regime` |
| 美股 ETF | 使用 NDX 单指数 regime |
| 港股 ETF | 使用恒生科技 HZ5017 单指数 regime |
| 卖出和风控 | 不受赔率或市场门控拦截 |

`baseline-v2.4` 在 gate-lite + regime_group 之上增加：

| 模块 | 处理 |
|---|---|
| 建仓/加仓 | 单 ETF 目标预算内 70/15/15：70% 建仓，两次 15% 储备加仓 |
| 止损 | 按 ETF `stop_loss_profile` 执行分市场/分波动止损 |
| 持有周期 | 最长 90 个自然日 |

当前基线结果（27 ETF，100,000 元，真实账户净值口径，交易成本 0.0005 + 滑点 0.0001）：

| 版本 | 年化收益 | 最大回撤 | Calmar | Sharpe | 胜率 | 利润因子 | 交易次数 |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline-v2.4, 2016-2026 | 11.74% | 28.48% | 0.4121 | 0.6942 | 38.52% | 1.6638 | 283 |
| baseline-v2.4, 2024-2026 | 16.61% | 19.12% | 0.8685 | 0.8088 | 46.39% | 1.6752 | 97 |

当前数据状态：

| 数据 | 状态 |
|---|---|
| ETF 映射 | 27 只 ETF 已补齐 `market / tracking_index / sector / theme / category / regime_group`，并可同步到 `etf_mapping` 表 |
| 港股指数 | 恒生科技 HZ5017 使用 Tushare `index_global(HKTECH)`，已回填 2020-07-27 ~ 2026-06-03 共 1436 条 |
| 回归验证 | `uv run pytest -q` 通过 101 项 |

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
uv run python main.py sync-etf-mapping

# 真实账户净值口径回测（本地 backtest 模块；不上传远程）
uv run python main.py backtest-portfolio --start 2024-06-01 --end 2026-06-03 --cost 0.0005 --slippage 0.0001

# 市场门控归因和亏损交易误判分析（本地 backtest 模块；不上传远程）
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
  indicators/                 MA、MACD、Bollinger、RSI、Volume、ADX、ATR、LongTermOdds
  strategy/                   交易信号生成，当前生产为 multi_indicator_scoring
  risk/                       90 日最大持有、profile 止损等风控规则链
  advisor/                    信号 x 持仓 x 溢价/市场门控 -> 操作建议
  runner/                     每日 STEP 1-5 编排
  service/                    指标、持仓、日历、信号重算、回测、盈亏等业务服务
  database/                   SQLAlchemy schema + repository，含 ETF 映射表
  models/                     Pydantic 业务模型
  dashboard/                  Streamlit 五页仪表盘
tests/                        指标和策略单元测试
```

说明：`src/backtest/` 和 `src/ds_backtest/` 为本地实验目录，开发规划、实验记录和架构归档等本地资料已在 `.gitignore` 中排除，不上传远程仓库。

## 数据链路

每日流程由 `src/runner/daily_runner.py` 串联：

```text
STEP 1  同步 quote / nav / premium_rate
STEP 2  计算技术指标和长期赔率，写入 indicators.data
STEP 2B 计算 market_regime
STEP 3  生成 BUY / SELL / HOLD，写入 signals
STEP 4  检查 90 日最大持有和 profile 止损
STEP 5  生成 operation_advice
```

数据源分工：

| 数据 | 来源 | 用途 |
|---|---|---|
| 历史 OHLCV | Tushare `fund_daily` + `fund_adj` | 上市以来前复权历史回填 |
| 日常 OHLCV | BaoStock | T-1 日线增量 |
| NAV/溢价率 | AKShare/EastMoney | 赔率价格基准和高溢价过滤 |
| 宽基/跨市场指数 | BaoStock、AKShare、Tushare `index_daily/index_global` | 市场热度状态和 gate-lite 分市场门控 |

## 仪表盘

```bash
uv run python main.py dashboard
```

默认地址为 `http://localhost:8501`。页面包含市场总览、我的持仓、ETF 详情、盈亏分析、策略对比。

## 免责声明

本项目用于个人研究和辅助决策，不构成投资建议。实际交易前请自行验证数据质量、滑点、费用、交易规则和风险承受能力。
