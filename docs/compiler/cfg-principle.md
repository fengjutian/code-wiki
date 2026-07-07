# CFG（控制流图）的原理

**CFG (Control Flow Graph)** 是编译器中间表示（IR）和程序分析中的核心数据结构，用于表示程序所有可能的执行路径。

---

## 1. 基本定义

CFG 是一个**有向图** `G = (V, E)`，其中：

| 元素 | 含义 |
|------|------|
| **节点 (Basic Block)** | 一段**连续执行**的指令序列，只有一个入口和一个出口——即一旦进入，必定顺序执行完所有指令 |
| **边 (Edge)** | 表示 basic block 之间的**控制转移**（跳转、分支、返回等） |
| **Entry** | 唯一的入口节点（函数起始） |
| **Exit** | 唯一的出口节点（函数返回） |

---

## 2. 核心构建规则

### Basic Block 划分原则

一个 basic block 的**第一条指令**必须是以下之一：
- 函数的入口
- 跳转指令的目标（label）

一个 basic block 的**最后一条指令**必须是以下之一：
- 跳转指令（`jmp`, `br`, `goto`）
- 返回指令（`ret`）
- 条件分支之后的 fall-through 分界

```
原始指令序列          →    划分出的 Basic Blocks

  x = 1                    ┌─ B0: x = 1
  y = 2                    │       y = 2
  if x > 0 goto L1         │       if x > 0 goto L1 ──┐
  z = 3                    └────────────────────────── │
  goto L2                ┌─ B1: z = 3                  │
L1:                       │       goto L2 ─────┐       │
  z = 4                  └────────────────────  │       │
  ret z               ┌─ B2 (来自B0): z = 4    │       │
L2:                    │       ret z           │       │
  ret z               └────────────────────    │       │
                      ┌─ B3 (来自B1): ret z    │       │
                      └────────────────────    │       │
                                                 
边: B0→B2 (条件成立), B0→B1 (条件不成立), B1→B3, B2→Exit
```

---

## 3. 三大经典分析

LLVM 和 GCC 都基于 CFG 做这三类核心分析：

### 3.1 支配关系 (Dominance)

- **A dominates B**：从 Entry 到 B 的**所有路径**都必须经过 A
- **Immediate Dominator**：最接近 B 的 dominator

**用途**：识别循环（自然循环 = 回边 + 支配关系）、SSA 构造

```
        Entry
         │
         B0          ← B0 dominates 所有节点
        /  \
       B1  B2        ← B1 不 dominate B3（有路径 B0→B2→B3 绕过 B1）
        \  /
         B3
```

### 3.2 数据流分析 (Data-flow Analysis)

迭代求解以下方程到不动点：

| 分析 | 方向 | 交汇运算 | 用途 |
|------|------|----------|------|
| **Reaching Definitions** | 前向 | ∪ | 优化、死代码消除 |
| **Liveness Analysis** | 后向 | ∪ | 寄存器分配 |
| **Available Expressions** | 前向 | ∩ | 公共子表达式消除 |
| **Constant Propagation** | 前向 | ∩ | 常量折叠 |

```
通用迭代框架（前向）：

for each block B:
    IN[B] = ∅
do {
    changed = false
    for each block B:
        IN[B] = ∪(OUT[P] for each predecessor P)
        old_OUT = OUT[B]
        OUT[B] = transfer(IN[B], B)
        if OUT[B] ≠ old_OUT: changed = true
} while (changed)
```

### 3.3 循环检测

利用 CFG 中的**回边 (back edge)**：`B → H` 是一条回边 iff `H` **dominates** `B`。

---

## 4. SSA (Static Single Assignment)

现代编译器（LLVM、v8 JIT、GraalVM）在 CFG 基础上的关键扩展：

```
原始:                      SSA 形式:
  x = 1              →      x₁ = 1
  x = x + 1          →      x₂ = x₁ + 1
  if (...)            →      if (...) goto B1 else B2
  x = 3              →  B1: x₃ = 3
  y = x + 1          →  B2: x₄ = φ(x₂, x₃)   ← φ 节点在支配边界
                           y₁ = x₄ + 1
```

**φ (phi) 函数** 插入在**支配边界 (dominance frontier)** 上，合并来自不同前驱的值。

---

## 5. 典型应用全景

```
源代码 (C/Go/Rust/...)
  │
  ▼
AST ───► CFG 构造（basic block 划分 + 边）
              │
              ├──► 支配树 ──► SSA 构造 ──► 优化 Pipeline
              │
              ├──► 数据流分析 ──► 死代码消除 / 常量传播
              │
              ├──► 循环分析 ──► 向量化 / 展开
              │
              └──► 控制依赖图 ──► 并行化 / 安全分析
```

---

## 6. 一句话总结

> **CFG 将程序从"线性指令序列"提升为"有向图"，使得编译器可以系统性地回答"这个值从哪里来""这个定义会被用到吗""哪些代码永远执行不到"等问题——所有现代编译器优化都建立在 CFG 之上。**
