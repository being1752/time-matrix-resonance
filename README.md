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
    ├── output.py               # CSV 输出
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
signals.csv     # 开平仓信号
intervals.csv   # 共振区间变化
summary.csv     # 回测总结
backtest.log    # 中文运行日志
```

这些输出文件已被 `.gitignore` 忽略。

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

颜色仅用于触发开平仓事件，内部使用枚举，日志和 CSV 中输出为文本：

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
*.log
*.xls
*.docx
__pycache__/
```

