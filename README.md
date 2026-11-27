# ETF 右侧交易助手

面向 A 股和跨境 ETF 的日线趋势跟踪系统。不预测行情，只在技术趋势确认后入场，在趋势走弱或风控触发时离场，并用市场门控拦截极端下行状态下的买入建议。人工确认执行。

> 状态：**已封版**（tag `v2026-final`，2026-11-27）。以下为封版形态。

## 核心规则

生产策略 `multi_indicator_scoring`，按 ETF 的 `volatility_group` 选择信号 profile。

```text
low_vol  (v2.3)  raw_score = 0.35*趋势 + 0.25*MACD + 0.15*RSI + 0.25*布林
                 BUY >= +50 且至少 2 个子信号为正；SELL <= -50 且至少 2 个为负

high_vol (v2.5)  趋势 30%、MACD 25%、RSI 15%、布林 15%、成交量 10%、ATR 5%
                 BUY >= 45 且趋势门槛通过、MACD 不明显为负、ADX >= 18、至少 3 个正向确认
                 SELL <= -35，或跌破 MA20/MA60 且 MACD 转负
```

| 模块 | 口径 |
|---|---|
| 建仓加仓 | 单 ETF 目标预算内 70/15/15；两次加仓各要求浮盈且 score >= 60 / 70；冷却 5 天 |
| high_vol 预算 | score >= 65 满额，55–65 为 80%，< 55 为 60% |
| 止损 | 按市场、按波动分 profile：A 股高波用 2.5 倍 ATR，跨境 -8%，A 股低波不设 |
| 持有周期 | 自首次建仓起最长 90 个自然日 |
| 市场门控 | A 股、美股、港股分别取宽基合成、NDX、恒生科技状态；`RISK_OFF` 时建仓降为观望、加仓降为继续持有；卖出和风控不受影响 |

## 基线结果

27 只 ETF，100,000 元，真实账户净值口径，交易成本 0.0005 + 滑点 0.0001。

| 版本 | 区间 | 年化 | 最大回撤 | Calmar | Sharpe | 胜率 | 利润因子 | 交易 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| v2026-final | 2016-2026 | 14.58% | 25.63% | 0.5687 | 0.8385 | 37.67% | 1.8126 | 430 |
| v2026-final | 2024-2026 | 38.96% | 15.75% | 2.4735 | 1.5593 | 40.91% | 2.8714 | 154 |
| v2026-final | 2021-2026（有效样本 ≥20 只） | 12.89% | 30.11% | 0.4282 | 0.7005 | 36.81% | 1.5934 | 288 |
| v2026-final | 2026 至今（01-01 ~ 11-25） | -11.91% | 27.58% | -0.4318 | -0.4243 | 26.92% | 0.6889 | 52 |

注意两点：27 只 ETF 中 21 只在 2019 年后上市，2016-2019 年可交易标的只有 3–6 只，长区间收益被早期小池放大；从 2021-05-25（第 20 只上市）起算，年化降到 12.89%，2026 年是亏损年。收尾前的旧引擎数字（15.12% / 22.06%）只作参照，见 `EXPERIMENT.md`。

## 快速开始

```bash
uv sync                                 # 依赖按 uv.lock 安装
cp .env.example .env                    # 数据库连接、Tushare Token
cp settings.yaml.example settings.yaml  # ETF 列表、策略参数、调度时间

uv run python main.py init              # 建表、历史回填、指标、信号
uv run python main.py run               # 执行到 T-1，漏跑会自动补齐
uv run python main.py dashboard         # http://localhost:18501
```

常用命令：

```bash
uv run python main.py schedule                    # 定时调度
uv run python main.py check-data                  # 数据健康检查，异常时非零退出
uv run python main.py rebuild-signals --start 2024-06-01 --end 2026-12-31
uv run python main.py backtest-portfolio --start 2016-01-01 --end 2026-12-31 --capital 100000 --cost 0.0005 --slippage 0.0001
uv run python main.py backtest-misjudge           # 亏损交易归因
uv run python main.py backtest-stop-loss          # 止损事件与止损后走势
uv run pytest -q
```

## 项目结构

```text
main.py / init_db.py           CLI 入口与初始化
src/
  fetcher/                     BaoStock、AKShare、Tushare 采集
  indicators/                  MA、MACD、Bollinger、RSI、Volume、ADX、ATR
  strategy/                    multi_indicator_scoring
  risk/                        RiskController、profile 止损、90 日最大持有
  advisor/                     信号 x 持仓 x 门控 x 预算 -> 操作建议
  runner/ scheduler/           每日流程与调度
  service/                     指标、持仓、日历、市场状态、信号重算、盈亏分析
  backtest/                    净值口径组合回测与归因报告
  database/ models/            schema、repository、业务模型
  dashboard/                   Streamlit 四页仪表盘
tests/                         单元测试与端到端契约测试
```

## 数据流

```text
STEP 1  同步 ETF 日线和指数行情到 T-1
STEP 2  计算技术指标
STEP 3  计算市场状态
STEP 4  生成 BUY / SELL / HOLD
STEP 5  检查止损和 90 日最大持有
STEP 6  生成操作建议：风控 > 市场门控 > 加仓冷却 > 加仓预算 > 技术信号
```

| 数据 | 来源 |
|---|---|
| 历史 OHLCV | Tushare `fund_daily` + `fund_adj` |
| 日常 OHLCV | BaoStock |
| A 股宽基指数 | BaoStock；科创50 走 AKShare |
| 纳指100、恒生科技 | AKShare、Tushare `index_global` |
| 交易日历 | exchange_calendars |

## 免责声明

本项目用于个人研究和辅助决策，不构成投资建议。实际交易前请自行验证数据质量、滑点、费用、交易规则和风险承受能力。
