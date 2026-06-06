# R335: v91#1 gateway_status退化修复

## 诊断过程

**现象**: `hermes gateway status` 从基线 ~1.7s → 3-13s (退化最高8x)

**根因定位**:
1. 用内部 stamp 埋点定位到 `find_alias_for_profile()` 函数耗时 0.47s/次，4 profiles 合计 ~1.9s
2. 该函数遍历 `~/.local/bin/` 下所有文件并逐个 `read_text()` 全文搜索 `hermes -p <profile>` 字符串
3. wrapper 目录中混入大二进制文件: `uv` (60MB), `xurl` (13MB), `uvx` (354KB) 等
4. 冷 cache 时每次读取 60MB+, 4 profiles × 107 文件 = 灾难级 I/O
5. OS 文件 cache 状态导致波动: 冷 13s → 热 3s

## 修复方案

在 `hermes_cli/profiles.py::find_alias_for_profile()` 中:
1. **跳过 >4KB 文件** — Hermes wrapper 仅 36-40B，大文件不可能是 wrapper
2. **只读前 200B** — wrapper 脚本仅 2 行(#!/bin/sh + exec hermes...)，无需读全文

## Benchmark 验证 (n=10)

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| Min | 1.7s (基线) / 3.0s (实测) | **1.123s** |
| Max | 13.4s | **1.177s** |
| Avg | 4.76s | **1.145s** |
| P50 | 3.1s | **1.142s** |
| 方差 | 10.5s 波动 | **0.055s 稳定** |

## 验收结论 ✅

- 根因: ✅ `find_alias_for_profile()` 读大二进制文件(uv 60MB)
- 修复: ✅ 跳过>4KB + 仅读前200B
- benchmark <3s: ✅ 实际 ~1.15s 稳定
- 目标: 🔴 3-13s → 🟢 ~1.15s (恢复并超越基线)
