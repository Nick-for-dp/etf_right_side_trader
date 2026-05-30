# ETF 右侧交易助手

ETF 右侧交易助手是一个面向 A 股和跨境 ETF 的趋势跟踪系统。它不预测行情，只在技术趋势确认后入场，在趋势走弱或风控触发时离场，并用长期赔率因子过滤追高建仓。

当前版本：`v2.1A`，已完成多指标评分、长期赔率门控、Streamlit 仪表盘、持仓管理、盈亏分析和赔率门控回测。

## 核心策略

生产策略是 `multi_indicator_scoring`：

```text
技术评分 = 0.35*S_trend + 0.25*S_macd + 0.15*S_rsi + 0.25*S_bb
Volume 仅作为置信度衰减，不放大信号
BUY  = score >= 50 且至少 2 个子信号为正
SELL = score <= -50 且至少 2 个子信号为负
```

`v2.1A` 新增长期赔率门控。它基于 ETF 自身历史 `nav/close` 计算 `CHEAP / FAIR / EXPENSIVE / INSUFFICIENT`，只拦截建仓和加仓，不影响卖出和风控清仓。

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
uv run python main.py backfill-tushare --symbol 588000 --start 20180101
uv run python main.py schedule
uv run python main.py backtest-odds --symbol 588000
uv run pytest
```

## 项目结构

```text
main.py                       统一 CLI 入口
init_db.py                    初始化和历史回填编排
src/
  config/                     settings.yaml + .env 配置读取
  fetcher/                    BaoStock、AKShare、Tushare 数据采集
  indicators/                 MA、MACD、Bollinger、RSI、Volume、LongTermOdds
  strategy/                   交易信号生成，当前生产为 multi_indicator_scoring
  risk/                       止损、回撤止盈等风控规则链
  advisor/                    信号 x 持仓 x 赔率门控 -> 操作建议
  runner/                     每日 STEP 1-5 编排
  service/                    指标、持仓、日历、回测、盈亏等业务服务
  database/                   SQLAlchemy schema + repository
  models/                     Pydantic 业务模型
  dashboard/                  Streamlit 五页仪表盘
  backtest/                   v2.0 vs v2.1A 赔率门控对比
tests/                        指标和策略单元测试
docs/history/                 历史技术报告
```

## 数据链路

每日流程由 `src/runner/daily_runner.py` 串联：

```text
STEP 1  同步 quote / nav / premium_rate
STEP 2  计算技术指标和长期赔率，写入 indicators.data
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

## 仪表盘

```bash
uv run python main.py dashboard
```

默认地址为 `http://localhost:8501`。页面包含市场总览、我的持仓、ETF 详情、盈亏分析、策略对比。

## 文档

- [Agent.md](Agent.md)：给智能体和协作者的开发规范、代码风格、人设和工作流
- [Archi.md](Archi.md)：项目目标、架构分层、数据模型和关键流程
- [PLAN.md](PLAN.md)：当前推进状态和后续任务
- [docs/history/v2.1A_REPORT.md](docs/history/v2.1A_REPORT.md)：v2.1A 历史技术报告归档

## 免责声明

本项目用于个人研究和辅助决策，不构成投资建议。实际交易前请自行验证数据质量、滑点、费用、交易规则和风险承受能力。
