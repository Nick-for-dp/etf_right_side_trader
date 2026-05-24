# ETF 右侧交易助手 — 近期规划

> v2.0 已完成（2026-05-14）。当前最急迫目标：先落地“长期赔率因子”，用 ETF 自身历史价格/NAV 构建开仓赔率门控，避免项目被 PE/PB 数据源卡住。PE/PB 分位保留为 v3.0 的优化方向。

---

## 项目现状

系统已经形成稳定的日线工作流：

```
fetcher -> quote/nav -> indicators -> strategy -> risk -> advisor -> dashboard
```

当前生产策略为 v2.0 多指标综合评分：

```
趋势 / MACD / RSI / 布林带 -> -100~+100 技术评分 -> BUY / SELL / HOLD
```

关键设计保持不变：

- `quote` 存储 ETF 日线、NAV、溢价率。
- `indicators.data` 使用 JSONB，新增指标无需改表。
- `signals` 只存策略输出和决策依据，下游 advisor 策略无关。
- 风控信号优先级高于策略信号。

---

## 已完成内容（缩写）

| 版本 | 内容 | 状态 |
|------|------|------|
| v1.0 | 基础数据链路、数据库、CLI、Dashboard MVP | ✅ |
| v1.1 | MACD 辅助确认、单只 ETF 增量初始化 | ✅ |
| v1.2 | 8% 止损、回撤止盈、虚拟交易盈亏分析 | ✅ |
| v2.0 | 趋势/MACD/RSI/布林带多指标综合评分、策略对比回测 | ✅ |
| v2.1-prep | Tushare 历史行情回填（`backfill-tushare`） + 前复权处理 + 515050 拆分验证 | ✅ 2026-05-23 |

v2.0 当前规则：

```
score = 0.35*S_trend + 0.25*S_macd + 0.15*S_rsi + 0.25*S_bb
BUY  = score >= +50 且至少 2 个子信号为正
SELL = score <= -50 且至少 2 个子信号为负
Volume 仅作为置信度衰减，不放大信号
```

---

## 数据源现状（2026-05-23 更新）

v2.1A 长期赔率因子需要 3 年以上历史日线。原有 BaoStock 仅覆盖 ~6 个月，AKShare 东方财富反爬严格、拉取不稳定。为此新增 Tushare 作为历史行情补充源：

```
Tushare fund_daily + fund_adj（全量历史 OHLCV，手动前复权）
       +
BaoStock（日常增量 OHLCV，自动前复权）
       +
AKShare/EastMoney（NAV + 溢价率）
```

关键设计：

- `HistoryFetcher` — 调 Tushare API，取不复权日线 + 复权因子，手动计算前复权。Tushare `fund_daily` 不提供 NAV，写入 DB 时 nav=None，后续从东方财富补。
- `DataManager.backfill_tushare()` — 临时方法，全量或单只 ETF 一键回填，`ON CONFLICT DO NOTHING` 自动跳过已有日期，不覆盖已存在的 NAV 数据。
- CLI 命令：`python main.py backfill-tushare [--symbol 588000] [--start 20180101] [--end YYYYMMDD]`
- 前复权公式：`前复权价格 = 原始价格 × 当日复权因子 / 最新复权因子`
- 515050（通信ETF华夏）2026-05-13 发生 3:1 拆分，`fund_adj` 的 `adj_factor` 从 1.0 → 3.0，全量验证（2019 年上市 ~ 今）diff=0.0000，价格序列连续无断崖。

当前 26 只 ETF 均可通过该链路获取上市以来全量历史前复权 OHLCV，满足 v2.1A 长期赔率因子的数据窗口要求。

---

## 当前最急迫任务：v2.1A 长期赔率因子

### 目标

不要先追求 PE/PB。先构建一个可回测、可每日更新、无额外数据依赖的“长期赔率因子”，回答：

```
当前这只 ETF 的长期入场赔率：便宜 / 中性 / 偏贵？
```

它不直接产生 BUY/SELL，只作为技术买入信号的门控或阈值调节器：

| 赔率状态 | 交易作用 |
|----------|----------|
| `CHEAP` | 允许 BUY/加仓，可将技术阈值从 50 降到 45 |
| `FAIR` | 正常执行技术策略 |
| `EXPENSIVE` | 禁止新开仓/加仓，只允许持有或卖出 |

### 数据需求

第一版只使用现有 `quote` 表：

| 字段 | 用途 |
|------|------|
| `date` | 计算滚动窗口 |
| `nav` | 长期赔率的首选价格基准 |
| `close` | NAV 缺失时回退 |
| `premium_rate` | 高溢价硬过滤 |
| `volume` | 后续可用于流动性过滤 |

价格基准：

```
P_t = nav if nav exists else close
```

窗口要求：

```
最少：3 年，约 756 个交易日
理想：5 年，约 1260 个交易日
```

**短历史 ETF 处理**（上市不足 3 年）：

| ETF | 上市日 | 约交易日 | 处理方式 |
|-----|--------|----------|----------|
| 561360 石油ETF国泰 | 2023-10-09 | ~654 | L 缩至 ~400，出赔率但精度打折 |
| 159227 航空航天ETF华夏 | 2024-01-08 | ~592 | L 缩至 ~340，出赔率但精度打折 |
| 159278 机器人ETF鹏华 | 2024-07-18 | ~459 | L < 252，直接标记 INSUFFICIENT |
| 159326 电网设备ETF华夏 | 2024-09-02 | ~427 | L < 252，直接标记 INSUFFICIENT |

动态窗口规则（在 `LongTermOdds.calculate()` 中实现）：

```
available = len(df)                                    # DataFrame 中实际交易日数
L_nominal = 756                                        # 理想窗口
H         = 252                                        # 持有期窗口
if available < H + 252:                                # 不足 2 年数据
    odds_state = "INSUFFICIENT", 全列 NaN
else:
    L_actual = min(L_nominal, available - H)           # 动态缩放
```

`INSUFFICIENT` 状态的 ETF 不参与门控（既不拦截也不放行，回退到 v2.0 技术策略逻辑）。

### 原子指标

| 指标 | 含义 | 方向 |
|------|------|------|
| `price_percentile` | 当前价格在过去 3 年的历史分位 | 越低越便宜 |
| `drawdown_score` | 当前相对 3 年高点的回撤 | 适度回撤提高赔率 |
| `zscore_score` | 当前价格相对长期均值的偏离 | 低于中枢更便宜 |
| `holding_score` | 历史任意时点买入并持有 1 年的胜率和平均收益 | 越高越好 |
| `risk_penalty` | 年化波动和最大回撤惩罚 | 风险越高扣分 |
| `premium_filter` | 场内溢价硬过滤 | 高溢价禁止开仓 |

### 计算公式

设：

```
L = 756 个交易日
H = 252 个交易日
P_t = 当日 nav，缺失则 close
```

历史价格分位：

```
price_pct = rank(P_t in P[t-L+1:t]) / L
S_price = clamp((0.5 - price_pct) * 2, -1, 1)
```

回撤赔率：

```
high = max(P[t-L+1:t])
drawdown = P_t / high - 1
dd_abs = abs(drawdown)
S_drawdown = clamp(dd_abs / 0.30, 0, 1)
```

长期均值偏离：

```
ma_long = mean(P[t-L+1:t])
std_long = std(P[t-L+1:t])
z = (P_t - ma_long) / std_long
S_z = clamp(-z / 2, -1, 1)
```

历史持有胜率：

```
returns_i = P[i+H] / P[i] - 1
i in [t-L+1, t-H]

winrate = count(returns_i > 0) / count(returns_i)
avg_return = mean(returns_i)

S_winrate = clamp((winrate - 0.5) * 4, -1, 1)
S_avg_return = clamp(avg_return / 0.20, -1, 1)
S_hold = 0.6*S_winrate + 0.4*S_avg_return
```

风险惩罚：

```
r = P_t / P_{t-1} - 1
vol_ann = std(r) * sqrt(252)
max_dd = max_drawdown(P[t-L+1:t])

P_risk =
  0.5 * clamp((vol_ann - 0.20) / 0.20, 0, 1)
+ 0.5 * clamp((abs(max_dd) - 0.30) / 0.30, 0, 1)

S_risk = -P_risk
```

长期赔率总分：

```
odds_score =
  0.30*S_price
+ 0.20*S_drawdown
+ 0.20*S_z
+ 0.20*S_hold
+ 0.10*S_risk

odds_score_final = odds_score * 100
```

状态映射：

```
CHEAP     : odds_score_final >= +30
FAIR      : -30 < odds_score_final < +30
EXPENSIVE : odds_score_final <= -30
```

高溢价硬过滤：

```
premium_rate >= 1.5% -> 禁止新开仓/加仓
```

### 更新频率

每日收盘后更新一次，放入现有日线流程：

```
STEP 1: 拉取 quote / nav
STEP 2: 计算技术指标
STEP 3: 计算 long_term_odds
STEP 4: 生成技术信号
STEP 5: advisor 根据 odds_state 做开仓门控
```

长期赔率是慢变量，但每日更新成本低，且能与当前 quote/indicator 流程自然对齐。

### 计划落地字段

写入 `indicators.data`：

```json
{
  "odds_score": 42.5,
  "odds_state": "CHEAP",
  "odds_price_pct": 0.22,
  "odds_drawdown": -0.18,
  "odds_zscore": -0.9,
  "odds_hold_winrate_1y": 0.64,
  "odds_hold_avg_return_1y": 0.12,
  "odds_risk_penalty": -0.2,
  "odds_premium_blocked": false
}
```

### v2.1A 任务拆分

| 步骤 | 任务 | 产出 | 状态 |
|------|------|------|------|
| S1 | 新增 `indicators/long_term_odds.py` | 计算 odds 原子指标、总分、状态 | ✅ 2026-05-23 |
| S2 | 在 `IndicatorService` 注册长期赔率指标 | 每日自动计算并写入 JSONB | ✅ 2026-05-23 |
| S3 | 历史数据回填 | Tushare 全量回填 26 只 ETF OHLCV | ✅ 2026-05-23 |
| S4 | advisor 开仓门控 | `EXPENSIVE` 或高溢价时阻止新开仓/加仓 | ✅ 2026-05-23 |
| S5 | Dashboard 展示 | ETF 详情页展示 odds_score、状态、分解项 | ✅ 2026-05-23 |
| S6 | 回测验证 | 对比 v2.0 与 v2.1A，观察追高交易和回撤变化 | ✅ 2026-05-24 |

验收标准：

- 不新增外部数据依赖。
- 可对历史数据回测，不能使用未来函数。
- 技术面 SELL 不被长期赔率阻止。
- 长期赔率只影响新开仓/加仓，不强制清仓。
- Dashboard 能解释”为什么技术 BUY 被拦截”。

---

#### S1：新增 `indicators/long_term_odds.py`

**新建文件**：`src/indicators/long_term_odds.py`

实现 `BaseIndicator`，`calculate(df) -> DataFrame`。

输入 DataFrame 须包含列：`date`, `close`, `nav`, `premium_rate`。计算窗口 L=756 个交易日（约 3 年），持有期 H=252 个交易日（约 1 年）。

输出 DataFrame 列：

| 列名 | 含义 | 取值范围 |
|------|------|----------|
| `odds_score` | 长期赔率总分 | `[-100, 100]` |
| `odds_state` | 赔率状态标签 | `”CHEAP”` / `”FAIR”` / `”EXPENSIVE”` |
| `odds_price_pct` | 当前价格在 L 窗口内的历史分位 | `[0, 1]` |
| `odds_drawdown` | 当前价格相对 L 窗口高点的回撤幅度 | 负数 |
| `odds_zscore` | 当前价格相对 L 窗口均值的 Z-score | 无界 |
| `odds_hold_winrate_1y` | L 窗口内任意时点买入持有 1 年的胜率 | `[0, 1]` |
| `odds_hold_avg_return_1y` | L 窗口内任意时点买入持有 1 年的平均收益 | 无界 |
| `odds_risk_penalty` | 年化波动 + 最大回撤惩罚 | `[-1, 0]` |
| `odds_premium_blocked` | 当日溢价 ≥ 1.5% 硬过滤标记 | `true` / `false` |

**关键实现约束**：

- 价格基准：`P_t = nav if nav not null else close`
- 无未来函数：`price_pct` 使用 `rank()/L`（不是窗口结束后的秩），`holding_score` 的 returns_i 使用 `P[i+H]` 仅在 `i+H <= t` 时计算
- 前 L+H-1 行（约 1008 个交易日）全列 NaN——数据不足时不出赔率

**不修改 `BaseIndicator` 接口**。新指标通过构造函数或内部逻辑适配自身特殊需求。

---

#### S2：IndicatorService 适配 + 注册

**修改文件**：`src/service/indicator_service.py`

1. `_LOOKBACK_PADDING`：120 → 1500 日历天（约 4 年，覆盖 odds 需要的 3 年交易数据 + 1 年 H 窗口）

2. `price_df` 构建新增 `nav` 列：

```python
price_df = pd.DataFrame([{
    “date”: str(q.date),
    “open”: q.open, “high”: q.high, “low”: q.low,
    “close”: q.close, “volume”: q.volume,
    “nav”: q.nav,                # 新增
    “premium_rate”: q.premium_rate,  # 新增
} for q in quotes])
```

**修改文件**：`src/indicators/__init__.py`

新增导出：`from .long_term_odds import LongTermOdds`

**修改文件**：`src/runner/daily_runner.py`（STEP 2，`_step2_calc_indicators`）

注册新指标：

```python
service.register(LongTermOdds())
```

**修改文件**：`init_db.py`（回填流程，`init_system`）

同上，注册 `LongTermOdds()`。

---

#### S3：历史数据回填 ✅ 2026-05-23

**实现方式**：通过 Tushare `fund_daily` + `fund_adj` 拉取上市以来全量前复权 OHLCV，`DataManager.backfill_tushare()` 方法实现。

**修改文件**：`settings.yaml` — `data.lookback_days` 已在 v2.0 阶段改为 1500。

**操作步骤**：

1. 执行 `python main.py backfill-tushare` 拉取全部 26 只 ETF 历史日线
2. 数据库中已有日期的数据通过 `ON CONFLICT DO NOTHING` 自动保留（含 NAV）
3. NAV 缺失的日期后续通过东方财富 `fund_etf_fund_info_em` 补全

**验证**：515050（通信ETF华夏）2026-05-13 发生 3:1 拆分，`adj_factor` 1.0→3.0，全量 5 年数据交叉验证 diff=0.0000，价格序列连续。

---

#### S4：advisor 开仓门控

**修改文件**：`src/advisor/operation_advisor.py`

函数签名扩展：

```python
def generate_advice(positions: list[dict],
                    signals: pd.DataFrame,
                    current_prices: dict[str, float],
                    risk_signals: dict[str, dict] | None = None,
                    odds_map: dict[str, dict] | None = None) -> list[dict]
```

`odds_map` 结构：`{code: {“odds_state”: “FAIR”, “odds_score”: 15.2, “premium_blocked”: False}}`

**门控逻辑**（在 `_ADVICE_MAP` 查表后、风险检查后）：

```
if advice in (“建仓”, “加仓”):
    if odds_state == “EXPENSIVE” or premium_blocked:
        if advice == “建仓” → override 为 “观望”
        if advice == “加仓” → override 为 “继续持有”
```

技术面 SELL 不受此门控影响（风控最高优，SELL 次之，赔率只抑制买入）。

**数据链路**（STEP 5 改动，`_step5_generate_advice`）：

从 `indicators` 表读取 `t_minus_1` 的 `data` JSONB，提取 `odds_state` / `odds_score` / `odds_premium_blocked`，组装 `odds_map` 传入 `generate_advice()`。

`indicators_repo` 已有 `find_by_code_between()`，可复用查询最近 N 天的指标数据。

| 持仓 | 信号 | 赔率状态 | 建议 |
|------|------|----------|------|
| 空仓 | BUY | CHEAP/FAIR | 建仓 |
| 空仓 | BUY | EXPENSIVE | 观望 |
| 空仓 | HOLD | 任意 | 观望 |
| 持仓 | BUY | CHEAP/FAIR | 加仓 |
| 持仓 | BUY | EXPENSIVE | 继续持有 |
| 持仓 | HOLD | 任意 | 继续持有 |
| 持仓 | SELL | 任意 | 清仓 |
| 任意 | 止损/止盈触发 | 任意 | 强制清仓 |

---

#### S5：Dashboard 展示

**修改文件**：`src/dashboard/detail.py`

底部 8 列指标卡片新增 2-3 列：

| 新增列 | 数据来源 | 展示格式 |
|--------|----------|----------|
| 赔率评分 | `indicators.data.odds_score` | `+42.5` |
| 赔率状态 | `indicators.data.odds_state` | 标签：绿色 CHEAP / 灰色 FAIR / 红色 EXPENSIVE |
| 溢价过滤 | `indicators.data.odds_premium_blocked` | 如为 true，显示”⚠ 高溢价拦截” |

可选：在 K 线图下方新增一个小型副图，展示 `odds_score` 历史曲线 + `CHEAP/FAIR/EXPENSIVE` 三色背景带。

---

#### S6：回测验证

复用 `src/service/profit_analysis_service.py` 的虚拟交易重建逻辑。

对比指标：

- v2.0（无赔率门控）vs v2.1A（有赔率门控）的同期交易记录
- 观察：追高建仓次数、总盈亏、最大回撤、胜率
- 验收：赔率门控减少追高交易，回撤改善，不显著减少盈利交易

**注意事项**：

- 对比时统一使用 `operation_advice` 中的历史建议（v2.0 和 v2.1A 各自生成一套 advice）
- 可先对单只 ETF（如 588000）跑试算，确认效果后再全量对比

---

## v2.1B：轻量基本面/持有体验辅助（后行）

在 v2.1A 稳定后，可评估接入 `fund_individual_profit_probability_xq`。

定位：

```
ETF 长期持有体验校验，不替代 PE/PB，不作为估值。
```

使用限制：

- 可用于实盘辅助。
- 不可直接用于历史回测，否则会产生未来函数。
- 更适合作为 `PASS / NEUTRAL / BLOCK` 门控，而非评分输入。

---

## v3.0：PE/PB 与回测框架优化

PE/PB 分位不再作为 v2.1 的阻塞项，调整到 v3.0 优化实现。

### PE/PB 数据链路

目标：

```
ETF -> 跟踪指数 -> 指数 PE/PB 历史 -> 估值分位 -> S_valuation
```

优先级：

1. 直接获取指数 PE/PB 历史数据。
2. 使用指数成分股和权重自算 PE/PB。
3. 对 PE 失真的行业或主题 ETF，引入 PB、股息率、ROE 等替代口径。

自算整体法：

```
PE_TTM = sum(成分股市值) / sum(成分股 TTM 净利润)
PB     = sum(成分股市值) / sum(成分股净资产)
```

近似权重法：

```
PE_index ≈ 1 / sum(weight_i / pe_ttm_i)
PB_index ≈ 1 / sum(weight_i / pb_i)
```

需要优化的问题：

- ETF 到跟踪指数的映射维护。
- 指数成分和权重的历史版本。
- 个股财务数据更新滞后。
- 亏损股、负净资产、极端 PE 的处理规则。
- 不同指数公司估值口径差异。

### 回测框架升级

v3.0 同时推进：

- 参数网格搜索。
- 分 ETF / 分市场环境回测。
- odds 门控阈值优化。
- 技术评分权重优化。
- 风险指标：最大回撤、年化收益、夏普、胜率、盈亏比。

---

## 操作建议映射

| 持仓 | 信号 | 赔率状态 | 建议 |
|------|------|----------|------|
| 空仓 | BUY | CHEAP/FAIR | 建仓 |
| 空仓 | BUY | EXPENSIVE | 观望 |
| 空仓 | HOLD | 任意 | 观望 |
| 持仓 | BUY | CHEAP/FAIR | 加仓 |
| 持仓 | BUY | EXPENSIVE | 继续持有 |
| 持仓 | HOLD | 任意 | 继续持有 |
| 持仓 | SELL | 任意 | 清仓 |
| 任意 | 止损/止盈触发 | 任意 | 强制清仓 |

---

## 数据库现状

| 表 | 职责 | 关键设计 |
|----|------|----------|
| `quote` | OHLCV + NAV + 溢价率 | (code, date) 联合主键 |
| `indicators` | 技术指标和长期赔率快照 | `data` JSONB，新增指标无需 ALTER TABLE |
| `signals` | 策略信号 | `signal_meta` JSONB 记录决策依据 |
| `positions` | 用户持仓 | `code` 唯一 |
| `operation_advice` | 每日操作建议 | 信号 × 持仓 × 赔率门控 |

---

## V2.1A 下一步计划（2026-05-24 更新）

S1-S6 全部完成，v2.1A 全链路已打通。

### 588000 回测验证结果（2026-05-24）

| 指标 | V2.0 (无门控) | V2.1A (有门控) |
|------|-------------|-------------|
| 累计盈亏 | -30.8% | **+2.1%** |
| 胜率 | 0% | 25% |
| 最大回撤 | -30.7% | -23.6% |
| 买入拦截 | — | 117 次 |

赔率门控显著减少追高交易，v2.0 的 -30.8% 累计亏损在 v2.1A 下扭亏为盈。

### 后续方向

| 优先级 | 内容 | 说明 |
|--------|------|------|
| P1 | 全量 26 只 ETF 回测 | 验证赔率门控在全量 ETF 上的普适性 |
| P2 | v2.1B 轻量持有体验 | `fund_individual_profit_probability_xq` 作为辅助门控 |
| P3 | v3.0 PE/PB 估值 + 参数优化 | 指数估值分位 + 网格搜索参数优化 |
