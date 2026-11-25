---
name: 管段站点介绍
description: 管段/站场介绍模板（结构固定、循证）
---

# 管段 / 站点 / 管线介绍

## 做什么

当用户询问**某一管段、站场、管线或工程**的介绍/概况/基本情况时，按固定结构作答，避免每次章节顺序不同；数字与状态只能来自证据包。

## 何时启用

命中任一即可：

- 问句含：介绍、概况、基本情况、是什么、讲讲、说明一下
- 问句含管段名模式：`起始站_终止站`（如 `济南西分输清管站_泰安压气站`）
- 问句含：管段、管线、管道、站场、压气站、分输站、清管站、阀室

## 输出结构（必须按此顺序，缺数据写「证据不足」）

### 1. 标题

用对象正式名称，例如：`济南西分输清管站_泰安压气站` 管段介绍

### 2. 核心结论（1～2 句）

写清：所属管线/工程、起止站（或站场角色）、长度或关键规模、当前建设/使用状态。句末标注证据 ID。

### 3. 基本身份

用条目列出（有则写，无则跳过该行，勿编造）：

- 管段名称 / 站场名称
- 所属管线（pipeline_name）
- 所属工程（engineering_name）
- 起始站 → 终止站（站场介绍则写所属管线与上下游关系，若证据有）
- 功能定位（如主干层、汇集疏散型、资源通道型等，若有）

### 4. 技术参数表（Markdown 表格，优先）

| 参数 | 数值 | 说明 |
|---|---|---|
| 管段长度 | … km | pipe_section_length |
| 管径 | … mm | pipe_diameter |
| 设计压力 | … MPa | design_pressure |
| 设计输量 | … | design_trans_flow_rate |
| 壁厚 | … mm | wall_thickness |
| 管材 | … | pipeline_material |
| 输送介质 | … | medium_tran |
| 里程范围 | 起–止 | start_meilage / end_meilage |

站场介绍时，把表头改为与站场相关的字段（若证据只有管段表，则说明「当前证据以管段台账为主」）。

### 5. 建设与运行

- 建设状态（build_status）
- 使用/投产状态（use_status）
- 投产或启用时间（use_time）
- 项目来源 / 所属项目库（若有）

### 6. 管理与区域归属

- 主体 / 业主单位（main_body、owner_company）
- 行政区划（administrative_division_name）
- 运价区 / 计价方式（transportation_price_area、pricing_method）
- 是否国家管网资产（若有）

### 7. 待补充

证据包没有、但对介绍有用的项，用列表标出（例如：实际日输量、近年事故/检修、站内设备清单）。禁止用推测填具体数字。

## 写作硬约束

1. **禁止编造**：证据没有的数字、状态、单位一律不写，或写入「待补充」。
2. **引用**：每个关键事实句末标注证据 ID（`kb:…` / `data:…`）；同一证据可重复引用。
3. **表格优先**：参数类信息优先用 Markdown 表格，便于前端渲染。
4. **结构稳定**：两次回答同一对象时，章节标题与顺序应一致；仅因证据增减导致某节变短或标「待补充」。
5. **语言**：白话、短句；面向非专业读者也能读懂。

## 字段对照（问数 CSV 常见列）

优先从 `data:` 证据抽取：`pipe_section_name`、`pipeline_name`、`engineering_name`、`start_station_name`、`end_station_name`、`pipe_section_length`、`pipe_diameter`、`design_pressure`、`design_trans_flow_rate`、`medium_tran`、`build_status`、`use_status`、`use_time`、`owner_company`、`administrative_division_name`、`transportation_price_area`。
