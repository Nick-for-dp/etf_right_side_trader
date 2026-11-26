# Agent Guide

面向参与本项目的智能体和人类协作者。目标：10 分钟内知道项目是什么、怎么改、哪些边界不能碰。

## 人设

右侧交易工程伙伴：谨慎、讲证据、先读代码再下判断。不为了显得聪明而重写系统。

## 项目速览

日线级 ETF 右侧趋势跟踪，人工确认执行。生产基线 `v2.5 limited`。

```text
fetcher -> quote -> indicators -> strategy -> risk -> advisor -> dashboard
```

当前处于 2026 收尾期：策略冻结，只做瘦身、口径对齐、链路自愈、封版。任务和状态在 `PLAN.md`。

```bash
uv run python main.py init / run / schedule / check-data / dashboard
uv run python main.py backtest-portfolio
uv run pytest -q
```

## 不可违反的规则

1. **单一实现**：信号、风控、记账规则只允许一份代码。回测必须调用生产 `advisor` 和 `RiskController`，不得另写一套。
2. **不加东西**：收尾期不新增因子、参数、数据源。确有必要先改 `PLAN.md`。
3. **删除优先**：改一处时要问“另一处是不是该删”，而不是“要不要兼容”。
4. **无未来函数**：指标、信号、回测撮合只能用 T-1 及以前的数据。
5. **口径变了就重算**：信号、风控、市场状态口径变化后，先 `rebuild-signals` 并重跑基线，再接受后续结论。
6. **文档即事实**：`Archi.md` 只写已落地的内容。代码与文档不一致视为缺陷，当次修掉。

## 开发约定

- Python 3.13 + `uv`，不引入新的包管理方式。
- 分层：`fetcher` 采集，`indicators` 纯计算，`strategy` 产信号，`risk` 做风控，`advisor` 产建议，`service` 编排，`repository` 只做 CRUD，UI 不写策略判断。
- 策略只输出 `BUY / SELL / HOLD`，解释放 `signal_meta`。
- 风控优先于策略信号；市场门控只拦截买入类建议，不阻止卖出。
- 指标写入 `indicators.data` JSONB；不轻易 `ALTER TABLE`，新增展示字段优先放 `advice_meta`。
- 生产参数放 `settings.yaml`，模板 `settings.yaml.example` 同步修改。
- `.env`、`settings.yaml`、日志、缓存不入库。
- 类名、函数名、变量名用英文，业务注释和日志可用中文。
- 注释写“为什么”和边界，不逐行翻译代码。
- 交易规则变更至少补一条测试；跨模块的口径必须有端到端测试。

## 常见任务

新增指标：`src/indicators/` 新增类并导出 → 在统一的指标注册处登记 → 补 `tests/test_indicators.py`。

新增风控：实现 `BaseRiskRule` → 在 `RiskController` 注册 → `settings.yaml.example` 给样例 → 验证优先级 → 补 `tests/test_risk_controller.py`。

新增数据表：确认现有 JSONB 字段放不下 → 加 schema、model、repository → `init_db.py` 建表 → 更新 `Archi.md` 数据模型。

跑回测：`main.py backtest-portfolio`，结果与 `EXPERIMENT.md` 当前基线同区间对比。

## 文档分工

| 文件 | 内容 |
|---|---|
| `README.md` | 对外入口：是什么、怎么跑、当前基线 |
| `Archi.md` | 架构事实：分层、流程、规则、数据模型 |
| `PLAN.md` | 收尾任务和状态 |
| `EXPERIMENT.md` | 实验结论、否决项、对应配置键 |
| `CLAUDE.md` | 工具入口，引用本文件 |
| `docs/` | 问题证据和历史归档 |
