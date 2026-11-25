import type { KnowledgeType } from "@/api/types";

export interface KnowledgeTypeDefinition {
  key: KnowledgeType;
  label: string;
  glyph: string;
  description: string;
  color: string;
  soft: string;
}

/** Shared user-facing taxonomy for the knowledge library and all scope pickers. */
export const KNOWLEDGE_TYPE_DEFINITIONS: KnowledgeTypeDefinition[] = [
  {
    key: "document",
    label: "文档资料",
    glyph: "文",
    description: "政策、制度、方案、研究材料",
    color: "#397eec",
    soft: "#eaf2fe",
  },
  {
    key: "dataset",
    label: "结构化数据",
    glyph: "数",
    description: "CSV、Excel、数据库与查询结果",
    color: "#0f9f8f",
    soft: "#e7f8f4",
  },
  {
    key: "media",
    label: "图片与多媒体",
    glyph: "图",
    description: "图片、扫描件、图表、音视频",
    color: "#8b5cf6",
    soft: "#f1ebff",
  },
  {
    key: "knowledge_card",
    label: "知识卡片",
    glyph: "卡",
    description: "文档摘要、要点和加工知识",
    color: "#d97706",
    soft: "#fff4df",
  },
  {
    key: "entity",
    label: "实体与关系",
    glyph: "实",
    description: "组织、项目、站场及知识关系",
    color: "#2563eb",
    soft: "#e8efff",
  },
  {
    key: "metric",
    label: "指标与规则",
    glyph: "指",
    description: "定义、公式、单位和业务口径",
    color: "#0891b2",
    soft: "#e3f7fb",
  },
  {
    key: "outcome",
    label: "报告与成果",
    glyph: "果",
    description: "报告、结论、图表和导出成果",
    color: "#db2777",
    soft: "#fce7f3",
  },
];
