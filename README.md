# Time Matrix Resonance

一个基于 1 分钟 K 线的多周期 MACD 共振回测引擎。

程序从 MySQL 逐根读取 1 分钟行情，按有效交易分钟更新 `1 ~ 当日最大周期` 的多周期状态，计算各周期 MACD、颜色、趋势，再扫描满足条件的共振区间并生成开平仓信号。

## 当前状态

- 数据源：MySQL
- 行情粒度：1 分钟 K 线
- 最大周期：从历史数据中单日最大有效分钟数自动推断
- MACD：每个周期独立计算，不使用数据库中已有 MACD 字段
- 回测方式：逐根 1 分钟线推进，模拟实时处理
- 交易方向：当前只实现做多信号

## 目录结构

```text
.
├── main.py                    # 程序入口
├── config.example.toml         # 配置模板，可复制为 config.toml
├── import_data_to_mysql.py     # 原始数据导入 MySQL 脚本
└── time_matrix/
    ├── cli.py                  # 配置读取、日志初始化、回测入口
    ├── config.py               # TOML 配置读取
    ├── data_loader.py          # MySQL 分钟线读取
    ├── indicators.py           # MACD、颜色、趋势状态
    ├── resonance.py            # 共振区间扫描与校验
    ├── backtester.py           # 逐分钟回测主流程
    ├── output.py               # XLSX 输出
    └── models.py               # 数据结构与枚举
```

## 环境要求

- Python 3.12+
- MySQL
- Python 依赖：

```powershell
pip install pymysql
```

## 配置

复制配置模板：

```powershell
Copy-Item .\config.example.toml .\config.toml
```

修改 `config.toml` 中的 MySQL 信息：

```toml
[data.mysql]
host = "localhost"
user = "root"
password = "CHANGE_ME"
database = "stock_data"
table = "stock_minute_quotes"
stock_code = "001330"
```

`config.toml` 包含本地密码，已被 `.gitignore` 忽略，不应提交到 GitHub。

## MySQL 表字段

回测读取以下字段：

```sql
trade_time
open_price
high_price
low_price
close_price
volume
stock_code
```

程序不会读取数据库里的 MACD 字段。所有周期的 MACD 都会根据该周期自己的收盘价序列重新计算。

## 运行

```powershell
python .\main.py
```

如需指定其他配置文件：

```powershell
python .\main.py --config .\config.example.toml
```

## 输出

默认输出目录由配置决定：

```toml
[output]
dir = "backtest_output_mysql"
```

生成文件：

```text
signals.xlsx     # 开平仓信号
intervals.xlsx   # 共振区间变化
signal_validation.xlsx # 算法信号后验验证
event_snapshots.xlsx # 开平仓与区间变化事件快照
summary.xlsx     # 回测总结
chart_data.json  # 前端K线复盘数据
backtest.log    # 中文运行日志
```

这些输出文件已被 `.gitignore` 忽略。

### 报告怎么用

回测完成后，建议按这个顺序看报告：

```text
summary.xlsx            先看整体结果是否有交易、胜率和盈亏是否正常
signals.xlsx            再看每一笔真实开平仓发生在什么时间、什么价格、什么原因
event_snapshots.xlsx    复盘开仓后每根1分钟线和关键周期状态如何变化
intervals.xlsx          检查共振区间是怎么出现、扩大、收缩或消失的
signal_validation.xlsx  验证算法信号后价格是否按预期上涨
chart_data.json         给前端K线复盘页面使用
backtest.log            排查运行过程、配置、进度、开平仓和异常
```

`summary.xlsx` 是总览表，用来回答“这次回测整体有没有效果”。主要字段含义：

```text
分钟线数量              本次实际参与回测的1分钟K线数量
信号数量                开仓和平仓信号总数
区间变化数量            最优共振区间发生变化的次数
事件快照数量            event_snapshots.xlsx 中记录的快照行数
算法验证数量            创建了多少次后验验证任务
算法验证成功数量        验证窗口结束时价格符合预期方向的次数
算法验证成功率百分比    算法信号本身的方向验证成功率
完整交易笔数            有开仓也有平仓的完整交易数量
盈利笔数                完整交易里平仓价高于开仓价的笔数
亏损笔数                完整交易里平仓价低于开仓价的笔数
胜率百分比              盈利笔数 / 完整交易笔数
总盈亏                  所有完整交易的价差盈亏合计，未计算手续费滑点
平均每笔盈亏            总盈亏 / 完整交易笔数
是否有未平仓            回测结束时是否还有持仓没平
预热结束时间            预热期结束、正式开始判断区间和交易的时间
```

`signals.xlsx` 是真实交易信号表，用来回答“策略实际在哪里开仓、在哪里平仓”。主要字段含义：

```text
时间                    信号发生的1分钟K线时间
动作                    open_long 表示开多，close_long 表示平多
价格                    该信号使用的成交参考价，当前为当根1分钟线收盘价
原因                    触发原因，例如 trigger_blue_to_green、trigger_color_reversal
区间最小周期            开仓或平仓时锁定区间的 P_min
区间最大周期            开仓或平仓时锁定区间的 P_max
触发周期                P_trigger，负责触发开平仓的小周期
触发前颜色              触发周期上一状态颜色
触发后颜色              触发周期当前状态颜色
```

`signals.xlsx` 重点看信号是否成对出现。如果只有开仓没有平仓，`summary.xlsx` 的完整交易笔数不会包含这笔；如果没有任何信号，优先检查 `intervals.xlsx` 是否出现满足条件的区间，再检查触发周期是否发生 `blue -> green`。

`intervals.xlsx` 是共振区间变化表，用来回答“算法什么时候认为多周期进入共振”。主要字段含义：

```text
时间                    最优共振区间发生变化的时间
方向                    当前方向，目前主要是 long
区间最小周期            本次最优区间的 P_min
区间最大周期            本次最优区间的 P_max
区间长度                P_max - P_min + 1
趋势周期数              区间内趋势为上涨的周期数量
最大连续趋势数          区间内连续上涨周期的最大长度
趋势占比                趋势周期数 / 区间总周期数，分母包含 up/down/non
触发周期                根据 P_min 和 divisor 算出的 P_trigger
```

`intervals.xlsx` 适合检查你的区间规则是否太宽或太窄。如果区间很多但 `signals.xlsx` 很少，说明大周期共振出现了，但触发周期没有给到开仓颜色转换；如果区间很少，优先调整入场区间阈值。

### 事件快照

`event_snapshots.xlsx` 用来复盘关键变化点，当前会记录三类事件：

```text
interval_change # 满足区间创建、变化或消失
open_long       # 开多
position_tick   # 持仓期间每根1分钟线的状态快照
close_long      # 平多
```

每条快照包含事件时间、1 分钟 K 线 OHLCV、交易日、当日有效分钟序号、事件价格、持仓状态、持仓浮盈亏、持仓期间最高/最低价、旧区间、新区间、触发周期、触发周期 MACD、颜色和趋势，以及 P_min / P_max 两个主要计算周期的 MACD、颜色和趋势。
它适合用来回答“这根 1 分钟线进来后，算法状态为什么变了、是否因此开平仓”。

### 各报告字段说明

`event_snapshots.xlsx` 的核心字段用法：

```text
事件时间                  当前快照对应的1分钟K线时间
事件类型                  interval_change / open_long / position_tick / close_long
原因                      本行快照产生的原因
价格                      当前事件价格，通常等于当根1分钟收盘价
1分钟开盘价/最高价/最低价/收盘价/成交量
                          用来复盘持仓期间真实价格怎么走
交易日                    当前K线所属交易日
当日有效分钟序号          只按真实存在的交易分钟累计，午休会直接跨过去
持仓状态                  flat 表示空仓，long 表示持有多单
持仓开仓时间              当前持仓从哪根1分钟K线开始
持仓开仓价                当前持仓的开仓价
持仓浮盈亏                当前价格 - 开仓价，未计算手续费滑点
持仓最高价                开仓后到当前快照为止出现过的最高价
持仓最低价                开仓后到当前快照为止出现过的最低价
旧区间最小/最大周期       区间变化前的 P_min / P_max
新区间最小/最大周期       区间变化后或当前持仓锁定的 P_min / P_max
新趋势周期数              当前区间内趋势为 up 的周期数量
新最大连续趋势数          当前区间内连续 up 周期的最大长度
新趋势占比                当前区间 up 周期数 / 区间总周期数
触发周期                  用来开平仓的小周期 P_trigger
触发周期MACD              P_trigger 当前最新 MACD 柱值
触发前颜色/触发后颜色     判断开仓 blue -> green、平仓 red -> yellow 或 green -> blue
触发周期趋势              P_trigger 当前趋势状态
最小周期MACD/颜色/趋势    P_min 当前最新状态
最大周期MACD/颜色/趋势    P_max 当前最新状态
区间变化类型              created / removed / range_changed / metrics_changed / none
```

看 `event_snapshots.xlsx` 时，最常用的方式是按一笔交易筛选：先找到 `open_long`，再往下看连续的 `position_tick`，最后看到 `close_long`。这样可以确认开仓后价格有没有按预期走、P_min/P_max 的 MACD 和趋势有没有同步变弱、平仓到底是触发周期颜色反转还是区间被破坏。

`signal_validation.xlsx` 是算法有效性验证表，用来回答“出现共振区间后，价格在预期窗口内最终是否上涨”。它不等同于真实交易收益，而是先验证算法信号本身有没有方向性。主要字段含义：

```text
验证编号                  每条验证任务的唯一编号
信号时间                  共振区间出现并创建验证任务的时间
方向                      当前验证方向，目前主要是 long
区间最小/最大周期         本次验证锁定的 P_min / P_max
区间长度                  验证起点的区间长度
触发周期                  本次区间对应的 P_trigger
最小周期已运行分钟        当前 P_min 周期已经运行了多少有效分钟
预期观察分钟              预计还能观察多少有效分钟
实际观察分钟              实际完成观察的有效分钟数
起始价格                  验证起点价格
结束时间                  验证窗口结束时间
结束价格                  验证窗口结束价格
结束涨跌幅百分比          从起始价格到结束价格的涨跌幅
窗口最高价                观察窗口内最高价
最大浮盈百分比            窗口最高价相对起始价格的最大浮盈
窗口最低价                观察窗口内最低价
最大回撤百分比            窗口最低价相对起始价格的最大回撤
是否符合预期方向          long 方向下，结束价格是否高于起始价格
起始/结束趋势周期数       观察窗口开始和结束时区间内 up 周期数量
趋势周期数变化            结束趋势周期数 - 起始趋势周期数
趋势强弱变化              stronger / weaker / unchanged
结束时区间是否有效        观察结束时原区间是否仍满足离场条件
是否完整观察              是否走满预期观察窗口
完成原因                  completed_window 或 end_of_data
```

如果 `signal_validation.xlsx` 表现好，但 `signals.xlsx` 和 `summary.xlsx` 表现差，说明算法方向可能有效，问题更可能在开仓触发、平仓条件、持仓规则或去重规则。如果验证本身就弱，优先回头看共振区间定义、趋势定义和阈值配置。

`chart_data.json` 是给前端 K 线复盘页面用的数据文件，不建议手工分析。它包含 1 分钟 K 线、1 分钟 MACD、开平仓信号、验证结果、区间变化和事件快照。前端页面用它把开仓、平仓、验证窗口和 MACD 副图画在同一张图上。

`backtest.log` 是中文运行日志，用来排查“为什么没有信号”或“为什么某一刻平仓”。重点搜索：

```text
回测开始                  查看配置是否按预期生效
回放进度                  查看是否正常推进、是否被 max_bars 截断
共振区间变化              查看区间是否被扫描出来
共振区间消失              查看原区间什么时候不满足条件
开多信号                  查看开仓时间、价格、原因、触发周期颜色
平多信号                  查看平仓时间、价格、原因、触发周期颜色
事件快照                  查看关键事件和持仓逐分钟快照是否写入
回测结束                  查看最终信号数、交易数、胜率和盈亏
```

## 核心规则

### 1. 周期更新

每次只读取 1 根 1 分钟线。

对于周期 `1 ~ max_period`，如果：

```text
day_index % period == 0
```

说明该周期 K 线完成，才更新该周期的 MACD、颜色、趋势。

未完成周期不参与共振扫描。

### 2. MACD

每个周期独立维护自己的 MACD 状态。

当前柱体口径：

```text
MACD = 2 * (DIF - DEA)
```

### 3. 颜色状态

颜色仅用于触发开平仓事件，内部使用枚举，日志和 XLSX 中输出为文本：

```text
red
yellow
blue
green
non
```

规则：

```text
red    = MACD > 0 且 delta > 0
yellow = MACD > 0 且 delta < 0
blue   = MACD < 0 且 delta < 0
green  = MACD < 0 且 delta > 0
non    = MACD = 0 或无法判断
```

`delta = 0` 时沿用上一颜色。

### 4. 趋势状态

趋势内部使用枚举：

```text
up
down
non
```

规则：

```text
最后一次 MACD 过零点之后：
如果柱体严格一根比一根大，趋势为 up
如果柱体严格一根比一根小，趋势为 down
其他波浪式变化为 non
```

### 5. 共振区间

配置：

```toml
[resonance.entry]
min_length = 10
min_ratio = 0.8
min_consecutive_trend = 8
```

入场区间必须同时满足：

```text
区间长度 >= min_length
上涨周期数 / 区间总周期数 >= min_ratio
区间内至少存在连续 min_consecutive_trend 个上涨周期
```

区间总周期数包含：

```text
up + down + non
```

如果多个区间满足条件：

```text
先取长度最大
长度相同取上涨占比最高
占比相同取 P_min 更小
```

### 6. 触发周期

配置：

```toml
[resonance.trigger]
divisor = 10
```

计算：

```text
P_trigger = max(1, P_min // divisor)
```

### 7. 开仓

大级别共振区间成立后，触发周期出现：

```text
blue -> green
```

生成开多信号。

### 8. 平仓

满足以下任一条件则平多：

```text
red -> yellow
green -> blue
```

或开仓时锁定的原始区间不再满足离场配置：

```toml
[resonance.exit]
min_ratio = 0.8
min_trend_count = 0
min_consecutive_trend = 8
```

其中 `min_trend_count = 0` 表示不启用绝对数量下限。

## 预热期

配置：

```toml
[backtest]
warmup_months = 1
```

预热期内只更新各周期的 MACD、颜色、趋势，不扫描区间、不产生交易信号。

## 算法有效性验证

配置：
```toml
[validation]
enabled = true
min_expected_minutes = 1
```

验证模块不以真实开平仓为中心，而是以“共振区间出现”为中心。  
每次正式回测阶段出现新的最优上涨共振区间时，程序会创建一条算法验证任务：

```text
expected_minutes = P_max - P_min - 当前 P_min 周期已运行有效分钟数
```

如果 `expected_minutes < min_expected_minutes`，该次验证会被跳过。

验证任务从共振出现当根 1 分钟 K 线的收盘价开始，向后推进 `expected_minutes` 根有效 1 分钟 K 线。  
这里的推进只按数据库里真实存在的 1 分钟 K 线累计，午休、停盘、隔夜不会被当成有效分钟。

生成文件：
```text
signal_validation.xlsx
```

核心字段：
```text
signal_time              共振信号出现时间
p_min / p_max             本次验证锁定的共振区间
elapsed_in_min_period     当前 P_min 周期已经运行的有效分钟数
expected_minutes          预期观察窗口
observed_minutes          实际观察到的有效分钟数
start_price               验证起点价格
end_price                 验证终点价格
return_pct                起点到终点涨跌幅
max_gain_pct              观察窗口内最大浮盈
max_drawdown_pct          观察窗口内最大回撤
is_expected_direction     做多方向下，终点价格是否高于起点价格
start_trend_count         起点区间内上涨趋势周期数
end_trend_count           终点区间内上涨趋势周期数
trend_strength_change     stronger / weaker / unchanged
interval_valid_at_end     终点时原始区间是否仍满足离场配置要求
completion_reason         completed_window 或 end_of_data
```

`signals.xlsx` 用来分析真实交易规则；`signal_validation.xlsx` 用来先判断算法信号本身是否有效。  
如果验证结果显示算法信号后价格经常上涨，但真实交易表现不好，问题优先看开仓、平仓、去重和持仓规则；如果验证结果本身就弱，问题优先看共振区间定义和趋势状态定义。

## 提交说明

建议提交：

```text
time_matrix/
main.py
import_data_to_mysql.py
config.example.toml
README.md
.gitignore
```

不要提交：

```text
config.toml
backtest_output*/
*.csv
*.xlsx
*.log
*.xls
*.docx
__pycache__/
```
