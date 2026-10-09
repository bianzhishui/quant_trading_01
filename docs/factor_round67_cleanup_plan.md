# Round 67 遗留项清理：`keep="first"` 显式化 + 删除替换语义死代码 · 预注册

> 状态：**已预注册 2026-10-09 / 实施中**
> 来源：R66 §0.3 的两个遗留项（由 0.009% 残差调查引出）。
> 代码：`src/quant_trading_01/data_io.py`

---

## 1. 两项遗留

### ① `keep="first"` 是隐式语义

```python
merged = merged.drop_duplicates(subset=["date", "code"])   # 默认 keep="first" —— 隐式
```

语义正确（历史优先、新数据不覆盖已有行），但**代码里没写出来**。
R66 用测试把它固定住了，然而下一个改这行的人未必会去读测试：

- 改成 `keep="last"` → **静默开始用新数据覆盖历史**；
- 调换 `concat` 顺序 → 同样后果。

### ② 替换语义死代码

```python
def write_full_daily_replace(df):      # "df 即各年份的最终内容, 不与既有合并"
```

- **全仓零调用**（含 `archive/`，R67 已复验，仅定义处 1 处命中）；
- 它是**唯一**会"替换式覆盖历史"的写入函数——留着就是一个随时会被误用的陷阱。

---

## 2. 规则（定死）

**行为零改动**，只做两件事：

1. `write_full_daily` 的 `drop_duplicates` 写全参数并加注释：

```python
merged = merged.drop_duplicates(
    subset=["date", "code"], keep="first"
)  # 显式 keep="first": 历史优先, 新抓数据不得覆盖已存在的行(R66 护栏)
```

2. **删除** `write_full_daily_replace`（确认零调用后）。

---

## 3. 预注册判定标准

| 判据 | 标准 | 含义 |
|---|---|---|
| **M1 行为零改动** | R66 的五条护栏（L1/L2/L3 + slow L4）**全部仍通过**；`write_full_daily` 对同输入产出逐位不变 | 纯可读性 + 死代码清理 |
| **M2 显式化落地** | 源码中 `drop_duplicates` 显式带 `keep="first"`（结构断言） | 防后人改成 last |
| **M3 陷阱消除** | `data_io` **不再存在** `write_full_daily_replace`（断言）；且全仓无引用 | 替换语义写入不可再被误用 |
| **M4 质量门** | `ruff check .` 0 错误 + `pytest` 全过（默认 + `-m slow`） | 仓库硬性要求 |

---

## 4. 诚实风险

1. **删除会破坏任何未入库的外部调用**：本轮已复验全仓（含 `archive/`）零调用；
   若存在仓库外的本地脚本引用该函数，会 `AttributeError`——如实记录该可能性（极低）。
2. **M1 的"逐位不变"不另做前后快照比对**：由 R66 的 L1/L2/L4 护栏承担
   （它们断言的是"追加后的内容"），语义等价性由此间接保证。

---

## 5. 非目标

- 建仓行遗留快照（`monthly_funds` 首行，R66/验证脚本查出的 66.68~180.72 元不一致）
  → **另开一轮**（涉及重写入库产物，需单独预注册）。

---

## 6. 实施

`src/quant_trading_01/data_io.py` → `tests/test_full_daily_append_invariant.py` 增两条断言
→ ruff + pytest（默认 + `-m slow`）→ 提交。

---

## §0 实施结果归档

> 实施 2026-10-09 ｜ `src/quant_trading_01/data_io.py` + `tests/test_full_daily_append_invariant.py`

### 0.0 总判定：**✅ 通过（M1-M4 全过）**

| 判据 | 结果 |
|---|---|
| **M1 行为零改动** | ✅ R66 五条护栏全部仍通过（L1/L2/L3 + **slow L4 真实分区门**：579,943 行重新追加 10-08 后 576,761 行逐位不变） |
| **M2 显式化落地** | ✅ 源码显式带 `keep="first"` + 注释："历史优先, 新抓数据不得覆盖已存在的行"；新增结构断言 `test_m2` |
| **M3 陷阱消除** | ✅ `write_full_daily_replace` **已删除**（780 字符）；新增断言 `test_m3`（`not hasattr` + 源码不含该名） |
| **M4 质量门** | ✅ `ruff check .` 0 错误；`pytest` **67 passed**（默认）+ **5 passed**（`-m slow`） |

### 0.1 改动（2 处，均不改变行为）

1. `write_full_daily`：`drop_duplicates(subset=["date","code"])` → 显式 `keep="first"` + 两行注释；
2. 删除替换语义死代码 `write_full_daily_replace`（全仓含 `archive/` 复验零调用）。

### 0.2 诚实边界

1. **若仓库外存在本地脚本引用被删函数**，会 `AttributeError`——已复验全仓（含 `archive/`）
   仅定义处 1 处命中，风险极低，如实记录；
2. **M1 的"逐位不变"未另做前后快照比对**，由 R66 的 L1/L2/L4 护栏间接保证（它们断言追加后的内容）。

### 0.3 复现

```bash
uv run pytest tests/test_full_daily_append_invariant.py -v        # 5 passed
uv run pytest tests/test_full_daily_append_invariant.py -m slow   # 1 passed
uv run ruff check .
```

