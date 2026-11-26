# PLAN — 2026 最终版收尾计划

状态：**进行中**（2026-11-26 起，目标 2026-12-31 封版为 `v2026-final`）。

本文档是收尾期唯一的任务清单。架构事实见 `Archi.md`，实验结论见 `EXPERIMENT.md`，问题证据见 `docs/功能瓶颈评估_2026-11-25.md`。

## 1. 目标

2027 年前把项目收口成一个**可信、可复现、能自己跑下去**的系统。策略冻结在 `v2.5 limited`，不加任何新因子、不做参数搜索；只做瘦身、口径对齐、链路自愈、封版。

## 2. 验收标准

全部满足才算封版。

| # | 标准 | 验证方式 |
|---|---|---|
| 1 | 文档 = 配置 = 数据库 | `create_strategy(config).version`、`signals.strategy_version`、README 三处一致 |
| 2 | 回测 = 实盘 | 信号和风控只有一套实现，回测直接调用生产 `RiskController` |
| 3 | 记账正确 | 加仓次数按持仓周期计；建仓日期不被加仓覆盖；减仓不改变单位成本 |
| 4 | 从零可复现 | 全新 clone → `init` → `run` → `backtest-portfolio` 不报错，数字与 `EXPERIMENT.md` 基线一致 |
| 5 | 断点自愈 | 人为停跑 5 个交易日后执行 `run`，派生数据补齐，`check-data` 通过 |
| 6 | 瘦身不改变行为 | 瘦身前后同口径回测数字一致 |

## 3. 原则

1. **奥卡姆剃刀**：没有证据支持、或生产不依赖的代码、数据、文档，一律删除。
2. **先删后修**：先清掉实验脚手架，再修口径，减少要改的代码量。
3. **删前留档**：删除前归档（归档分支 + tag，文档用 zip），仓库里只留有结论的东西。
4. **单一实现**：同一规则只允许存在一份代码。
5. **每阶段收口**：阶段结束跑全量 `pytest` 和一次标准回测，数字记入 `EXPERIMENT.md`。

## 4. 瘦身清单

| 层 | 删除 | 合并 | 保留 |
|---|---|---|---|
| 回测 `src/backtest/`（24 个 py） | 再入场 ×2、相对强弱 ×2、频控、质量控制、质量分层稳健性、资金再分配、高低波重心锚点、波动分组验证 ×3、odds_gate、`ablation_report`、`ablation_config` | — | 组合回测引擎、`portfolio_metrics`、门控归因、误判分析、止损归因、ETF 分层 |
| 回测引擎 `portfolio_backtest.py` | 频控过滤、再入场、相对强弱排序、质量日限额、组合风控缩放、实验风控 profile、`run_experiments` | 风控改为调用 `RiskController` | `run`（单一配置）：逐日推进 → advisor → 执行 → 净值 |
| 实验信号 `experimental_signals.py` | 整个文件 | 并入 `multi_indicator_scoring` | — |
| 策略 | `ma_cross`、`ma_cross_macd` | — | `multi_indicator_scoring` |
| 指标 | `LongTermOdds` | `init_db.py` 与 `daily_runner.py` 各写一遍的指标注册、信号生成，收成一处 | MA、MACD、BOLL、RSI、Volume、ADX、ATR |
| 风控 | `StopLossRule`、`TrailingStopRule` | — | `profile_stop_loss`、`max_holding_days` |
| 市场状态 | 9 态枚举 | 收敛为 `RISK_OFF / NORMAL / UNKNOWN`，细分原因留在 `data.reason` | gate-lite + 分市场 |
| 指数配置 | 13 个权重为 0 的行业指数 | — | 6 个 A 股宽基 + NDX + HZ5017 |
| 数据 | `quote.nav`、`quote.premium_rate` 两列；`indicators.data` 中的 `odds_*` 键；`index_valuation` 表及其 repo、model | — | 其余 9 张表 |
| Dashboard | 策略对比页 | 数据健康并入总览页顶部 | 总览、持仓、详情、盈亏 |
| 服务 | `BacktestComparison`（`backtest_comparison.py`） | — | — |
| 依赖 | `scikit-learn` | — | — |
| 入口 | `ablation.py`；根目录 `daily_runner.py`、`run_scheduler.py` | 回测报告命令并入 `main.py` | `main.py`、`init_db.py` |
| 杂项 | `src/ds_backtest/`、`src/fetcher/test_baostock_fallback.py`、`_tmp*.txt`、2 只孤儿 ETF 行情、168 条 v2.0 信号 | — | — |
| 测试 | 11 个实验测试文件（见 5.1） | — | 13 个生产口径测试 + 新增契约测试 |
| 文档 | `docs/` 下 9 份已失效文档 | — | 见第 9 节 |

预期效果：回测层 24 个 py → 6 个，引擎约 1,900 行 → 600 行左右，策略 3 → 1，风控规则 4 → 2，市场状态 9 → 3，每日同步指数 21 → 8，数据表 10 → 9。

**刻意保留**：市场门控、ATR 分 profile 止损、high_vol 质量分层预算。三者都有同口径对照证据，不属于冗余。

## 5. 阶段任务

### 5.0 阶段零：封存现状（开发前，约半天）

现状：`git status` 有 14 个已跟踪文件未提交（含 v2.5 的策略、advisor、配置读取改动），`src/backtest/`、`tests/`、`docs/`、四份根文档被 `.gitignore` 排除。**此时直接打 tag 封不住任何实验代码。**

| 任务 | 说明 | 状态 |
|---|---|---|
| 0.1 归档分支 | 新建 `archive/pre-slim-2026`，`git add -A` 后 `git add -f` 实验、测试、文档，提交 | 待办 |
| 0.2 打 tag | `archive/pre-slim-2026`，然后切回 `master` | 待办 |
| 0.3 瘦身前参照 | 用当前引擎跑 `v2.5 limited`（2016-2026、2024-2026），数字存入 `docs/瘦身前参照.md` | 待办 |

注意：`git` 不在 PATH，位于 `D:\Git\cmd\git.exe`。

### 5.1 阶段一：瘦身与口径对齐（11/26 – 12/02）

| # | 任务 | 状态 |
|---|---|---|
| 1.1 | 删除实验回测文件与 `ablation.py`；`main.py` 去掉 `backtest-odds` | 待办 |
| 1.2 | `portfolio_backtest.py` 去掉全部实验分支，只留 `run`；风控调用 `RiskController` | 待办 |
| 1.3 | `high_vol_balanced` 并入生产策略类，删除 `experimental_signals.py` | 待办 |
| 1.4 | 删除 `ma_cross`、`ma_cross_macd`、`BacktestComparison`、策略对比页 | 待办 |
| 1.5 | 删除 `LongTermOdds` 及 nav、溢价率全部管道；`quote` 删两列；清理 `indicators.data` 的 `odds_*` | 待办 |
| 1.6 | 删除 `StopLossRule`、`TrailingStopRule`；`MarketState` 收敛为 3 态并重算 `market_regime` | 待办 |
| 1.7 | 配置移除 13 个行业指数；删除 `index_valuation` | 待办 |
| 1.8 | 指标注册与信号生成合并为一处，`init_db.py` 与 `daily_runner.py` 共用 | 待办 |
| 1.9 | 记账修复：`count_adds` 按持仓周期；`positions.first_entry_date`；`reduce` 保持单位成本 | 待办 |
| 1.10 | 清理 `ds_backtest`、根目录两个壳、fetcher 测试脚本、`_tmp*`、孤儿行情、v2.0 信号、`scikit-learn` | 待办 |
| 1.11 | 确定生产基线并开启 `high_vol` profile，全量 `rebuild-signals` | 待办 |
| 1.12 | 测试：删 11 个实验测试，新增端到端契约测试、跨周期加仓测试 | 待办 |
| 1.13 | 回归：同口径重跑，确认与 0.3 的参照数字一致 | 待办 |
| 1.14 | 调整 `.gitignore`，`src/backtest/`、`tests/` 入库；提交 | 待办 |

删除的测试文件：`test_ablation_report`、`test_high_vol_frequency_control`、`test_high_vol_mixed_strategy`、`test_high_vol_quality_capital_attribution`、`test_high_vol_quality_control`、`test_high_vol_quality_tier_robustness`、`test_portfolio_risk_control`、`test_relative_strength`、`test_volatility_focus_anchor`、`test_volatility_profile_strategy`、`test_volatility_strategy`。

产出：一次“瘦身 + 口径修正”提交，验收标准 1、2、3、6 达成。

### 5.2 阶段二：链路自愈（12/03 – 12/09）

| # | 任务 | 状态 |
|---|---|---|
| 2.1 | `run_daily` 改为区间补算：从最后一个完整派生日补到今天，逐日计算 indicators、regime、signals、advice，advice 用当日真实风控信号 | 待办 |
| 2.2 | `check-data` 增加硬校验：缺失交易日、指数停更、指标/信号断档；失败返回非零退出码 | 待办 |
| 2.3 | 调度：启动即补跑、misfire 处理、失败告警 | 待办 |
| 2.4 | HZ5017 增加 AKShare 兜底 | 待办 |
| 2.5 | 补回 2026-09-15 起的空洞 | 待办 |

产出：停跑数周后一条命令恢复。验收标准 5 达成。

### 5.3 阶段三：基线重跑（12/10 – 12/16）

| # | 任务 | 状态 |
|---|---|---|
| 3.1 | 重跑 `v2.5 limited`：2016-2026、2024-2026，另加“池内可交易 ETF ≥ 20 只”的有效样本区间 | 待办 |
| 3.2 | 重跑门控归因、误判分析、止损归因、ETF 分层四份报告 | 待办 |
| 3.3 | 数字写回 `README.md` 和 `EXPERIMENT.md`，旧数字标注为“瘦身前参照” | 待办 |

说明：原计划的 NAV 回填已取消，NAV 相关能力整体移除。

### 5.4 阶段四：可执行与封版（12/17 – 12/31）

| # | 任务 | 状态 |
|---|---|---|
| 4.1 | 建议输出目标金额、参考股数、占账户比例（写入 `advice_meta`）；文案读取实际预算乘数 | 待办 |
| 4.2 | Dashboard 收敛为 4 页，数据健康并入总览 | 待办 |
| 4.3 | 从零复现演练：全新目录 clone → `init` → `run` → `backtest-portfolio` | 待办 |
| 4.4 | 文档封版：去掉“进行中”标记，`RELEASE_NOTES.md` 填入最终数字 | 待办 |
| 4.5 | 提交并打 tag `v2026-final` | 待办 |

产出：验收标准 4 达成，全部 6 条标准关闭。

## 6. 明确不做（2027 年再议）

- 任何新因子、参数网格、walk-forward
- 动态组合风控、A/B/C 资金配置、横截面资金分配
- 分钟级、自动下单、LLM 生成信号
- 主题热度、行业资金流、基本面估值
- NAV、溢价率、长期赔率

## 7. 已确认的决定（2026-11-26）

| # | 事项 | 决定 |
|---|---|---|
| 1 | 生产基线 | `v2.5 limited` |
| 2 | 调度位置 | 保持本机；阶段二只做启动补跑和失败告警 |
| 3 | `MarketState` 三态命名 | `RISK_OFF / NORMAL / UNKNOWN` |
| 4 | 瘦身后 `src/backtest/`、`tests/` | 入库，`.gitignore` 同步调整 |

## 8. 文档维护约定

- `README.md`：对外入口，写运行方式和当前基线。
- `Archi.md`：架构事实，只写已落地的内容。
- `PLAN.md`：本文件，只写收尾期任务和状态。
- `EXPERIMENT.md`：只记结论和对应配置键，不记过程。
- `Agent.md`：协作者和智能体的工作约定。
- `docs/`：只放问题证据和归档。历史文档统一在 `docs/history/pre-slim-docs-2026-11-26.zip`，不散落。

## 9. 2027 待办（冻结，不在本期）

按优先级：

1. 长周期分类资金配置：A 类满权重、优先执行，B 类按质量缩放，C 类低权重。
2. 同日多个 BUY 的排序与现金分配规则。
3. 止损机会成本归因：止损退出、延迟退出、快速再入场对照。
4. B/C 类主题拆分归因。
5. 动态组合风控。
6. 参数网格与 walk-forward。
7. 组合风险 Dashboard、拦截机会成本统计。
