# ETF 右侧交易助手 — 设计文档

> v1.0 MVP 已完成（2026-04-29），v1.1 已完成（2026-05-06），v1.2 已完成（2026-05-08），本文档聚焦架构设计 + 后续规划。

---

## 架构概要

```
dashboard/（Streamlit 3 页）
runner/（STEP 1-5 编排）
fetcher/ | indicators/ | strategy/ | risk/ | advisor/
service/（TradingCalendar | IndicatorService | PositionService | QuoteService）
database/（ORM schema ←→ pydantic models ←→ repository）
config/（YAML + .env）
```

三层扩展点（不动已有代码）：

| 扩展点 | 方式 | 示例 |
|--------|------|------|
| 新增指标 | 实现 `BaseIndicator.calculate(df) -> dict` | `macd.py` |
| 替换策略 | 实现 `BaseStrategy.generate(df) -> DataFrame`，yaml 改一行 | `ma_macd.py` |
| 新增风控 | 实现 `BaseRiskRule.check(pos, price) -> RiskResult`，yaml 加一项 | `take_profit.py` |

指标与信号分表（`indicators.data` JSONB + `signals`）：策略升级时指标无需重算，只重新生成信号。

---

## 版本演进

### v1.1 — MACD 辅助确认 + 工程改进 ✅（2026-05-06 完成）

**MACD 策略**（主线）：

```
金叉（MA20 > MA60）且 DIF > 0 → BUY（原逻辑加入 MACD 确认，过滤假突破）
死叉（MA20 < MA60）→ SELL（卖出不依赖 MACD，跟随趋势反转）
```

- 新增 `indicators/macd.py`：计算 DIF / DEA / MACD 柱
- 新增 `strategy/ma_cross_macd.py`：继承金叉/死叉逻辑，BUY 侧增加 `DIF > 0` 条件
- yaml 改一行 `type: "ma_cross_macd"`
- 历史 MACD 指标通过 `IndicatorService` 增量回填

实际实现：
- `indicators/macd.py` — MACD 三线（DIF / DEA / MACD 柱），Wilder 平滑
- `strategy/ma_cross_macd.py` — 独立策略类，BUY = 金叉 + DIF > 0，SELL = 死叉
- `strategy/factory.py` + `settings_reader.py` — 新增 `"ma_cross_macd"` 策略类型
- 所有模块注册 MACD 计算器（`daily_runner.py` / `init_db.py`）

**ETF 增量初始化**（工程改进）✅：

- `python main.py init --symbol 588000 --start 2024-01-01` 支持单只 ETF 回填
- 自动检测已有数据，跳过已覆盖的日期范围
- 回填逻辑已迁移到 `DataManager` 中，`init_system` 可直接传参调用

### v1.2 — 回撤止盈 + 盈利分析 ✅（2026-05-08 完成）

**Day 1：回撤止盈 ✅（2026-05-07 完成）**

新增 `risk/trailing_stop.py`：浮盈 10% 激活，从持仓期间最高点回撤 3% 触发 SELL。与止损规则在 `RiskController` 中链式执行，短路返回。新增 `service/quote_service.py`（`QuoteService.find_max_close_between`）+ `PositionService.get_holding_map` 为规则提供峰值数据，不改 `BaseRiskRule` 接口。

**Day 2：虚拟回测盈亏分析 ✅（2026-05-08 完成）**

基于 `operation_advice` 历史重建虚拟交易对，状态机遍历建仓→加仓→卖出周期，以 advice 生成当日收盘价作为虚拟成交价。纯分析层，不新增数据库表。

- `models/virtual_trade.py` — `VirtualTrade` pydantic 模型（exit_date 为空表示未平仓）
- `service/profit_analysis_service.py` — `reconstruct_trades(code, calendar)` 全量历史重建 + `calculate_equity_curve` + `get_summary`
- `dashboard/pnl.py` — 盈亏分析页：汇总指标 + 已平仓明细 + 当前持仓 + 资金曲线，日期过滤在展示层
- `advice_repo.find_by_code` / `quote_repo.find_by_code_in_range` — 按代码查询方法

### v2.0 — 多指标综合评分

**目标**：从单信号判断升级为多维度加权评分，策略输出 -100~+100 综合评分替代 BUY/SELL/HOLD。

**设计原则**：不做"离散状态机先分类再查表"——把连续信息压缩成枚举值再还原是纯信息损失。每个指标通过连续映射函数直接产出 [-1, 1] 子信号，加权求和后 ×100 得到评分。阈值只影响展示标签，不影响决策值。

**依赖关系**：S1-S3 并行 → S4 → S5-S7 并行

#### Phase 1：新增三个指标（S1-S3，可并行）✅ 已完成

| 步骤 | 模块 | 说明 |
|------|------|------|
| **S1** | `indicators/bollinger.py` | 布林带：中轨 MA20、上下轨 ±2σ，输出 `bb_mid/bb_upper/bb_lower/bb_width` |
| **S2** | `indicators/rsi.py` | RSI-14，Wilder 平滑，输出 `rsi` |
| **S3** | `indicators/volume.py` | 成交量 MA（20 日均量）、量比 `vol_ratio` |

三个指标均实现 `BaseIndicator.calculate(df) -> DataFrame`，互不依赖。

#### Phase 2：综合评分策略（S4）

| **S4** | `strategy/multi_indicator_scoring.py` | 依赖 S1-S3 |

策略输出 -100~+100 连续评分。评分公式：

```
score = (w₁·S_trend + w₂·S_macd + w₃·S_rsi + w₄·S_bb) × 100   ∈ [-100, 100]

默认权重：w₁=0.45  w₂=0.30  w₃=0.15  w₄=0.10（sum=1.0，settings.yaml 可配）
```

Volume 不作为独立子信号，而是作为**乘数**作用在整个 score 上：

```
score_final = score × clamp(vol_ratio^0.3, 0.75, 1.25)
```

放量放大分数，缩量压低分数，±25% 封顶。幂次 0.3 抑制极端量比杠杆效应。

##### 子信号设计

**S_trend（0.45）— 趋势方向与强度，系统锚点**

```
S_trend = clamp(spread×25 + position×15, -1, 1)
spread   = (ma20 - ma60) / ma60      # 均线乖离率
position = (close - ma20) / ma20     # 价格距短期均线
```

均线排列决定方向，其他三个指标只做确认和修正。2% 乖离+1.3% 溢价触及 cap，>3% 乖离持续顶 cap——强趋势中系统坚定持有，不因"趋势太强"而退缩。

**S_macd（0.30）— 动能确认**

```
S_macd = clamp(dif_norm×3 + macd_hist_norm×1.5, -1, 1)
dif_norm      = DIF / close
macd_hist_norm = (DIF - DEA) / close
```

连续替代 v1.1 的 `DIF > 0` 硬条件：DIF 为负自然拖累总分，DIF 接近 0 时贡献中性由趋势主导。MACD 柱提供加速度信号——柱线放大推高分，柱线收窄向 0 回归。

**S_rsi（0.15）— 超买超卖修正**

```
S_rsi = clamp((rsi-50)/20, -1, 1) × decay(|rsi-50|, center=20, width=10)
decay(x, c, w) = 1 / (1 + exp((x-c)/w))
```

RSI 45-55 线性映射贡献小，RSI>60 或 <40 区 sigmoid 衰减因子生效——超买超卖区边际贡献递减，避免在极端区域盲目追涨杀跌。R²=80 也只能拉低总分约 13 点，不足以翻转强趋势，但足以在趋势+动能双弱时推到负值触发卖出。

**S_bb（0.10）— 波动率位置**

```
S_bb = clamp((pos_in_band-0.5)×2, -1, 1)
pos_in_band = (close - bb_lower) / (bb_upper - bb_lower)
```

权重最低——布林带位置与趋势方向高度共线，S_trend 已经给了正向分数。主要作用是在震荡市（S_trend≈0）中提供边际信息。

##### 与 advisor 层对接

默认阈值（yaml 可配）：

```
score ≥ +30  → BUY   (建仓/加仓)
score ≤ −30  → SELL  (清仓)
−30 < score < +30 → HOLD (观望/持有)
```

±30 阈值意味着需要至少两个子信号同时指向同一方向才能触发操作。advisor 层从查 `signal` 字段改为读 `score` 数值做阈值映射。

#### Phase 3：集成与验证（S5-S7，可并行）

| **S5** | 指标增量回填 | `IndicatorService` 注册新指标，`init --symbol` 增量回填历史数据 |
| **S6** | Dashboard 更新 | 详情页新增布林带/RSI/成交量副图，信号展示改为评分曲线 |
| **S7** | 回测对比 | 用 `profit_analysis_service` 跑 V1.2 vs V2.0 同期对比，验证升级效果 |

#### 关键设计决策（已定）

1. 不做趋势状态机——连续函数直接算分，不经过离散分类
2. 权重和评分阈值通过 `settings.yaml` 可配置，S4 实施时新增配置项
3. V2.0 策略通过 `strategy.factory` 新增 `"multi_indicator_scoring"` 类型，与 V1.x 共存
4. 信号表 `signal` 字段存储 score 数值，`signal_meta` JSONB 存储四个子信号分解值，便于调试和回测

### v2.1 — 待办

- **LLM 基本面分析**：引入 LLM 对 ETF 基本面（宏观经济、行业政策、资金流向等）进行分析，作为策略信号的辅助确认维度
- **完善操作建议映射**：补充 空仓 + SELL → 持有 映射（卖出信号但无持仓时不操作），确保四个组合全部覆盖

---

## 操作建议映射（策略无关，v1.0-v2.0 不变）

| 持仓 | 信号 | 建议 |
|------|------|------|
| 空仓 | BUY | 建仓 |
| 空仓 | HOLD | 观望 |
| 持仓 | SELL | 清仓 |
| 持仓 | HOLD | 继续持有 |
| 持仓 | BUY | 加仓 |
| 任意 | 止损/止盈触发 | 强制清仓 |

风控信号优先级高于策略信号，短路执行。

---

## 数据库（5 张表）

| 表 | 职责 | 关键设计 |
|----|------|----------|
| `quote` | OHLCV + NAV + 溢价率 | (code, date) 联合主键 |
| `indicators` | 技术指标快照 | `data` JSONB，新增指标无需 ALTER TABLE |
| `signals` | 策略信号 | `signal_meta` JSONB 记录决策依据，`strategy_version` 标记版本 |
| `positions` | 用户持仓 | `id` 自增主键，`code` 唯一 |
| `operation_advice` | 每日操作建议 | 信号 × 持仓查表结果，`signal_source` 标记来源 |
