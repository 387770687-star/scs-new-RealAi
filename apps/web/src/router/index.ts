import { createRouter, createWebHashHistory } from "vue-router";
import MainLayout from "@/layouts/MainLayout.vue";

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: "/",
      component: MainLayout,
      children: [
        { path: "", redirect: "/workbench" },
        {
          path: "workbench",
          name: "workbench",
          component: () => import("@/views/workbench/WorkbenchView.vue"),
          meta: { title: "工作台" },
        },
        {
          path: "knowledge",
          name: "knowledge",
          component: () => import("@/views/knowledge/KnowledgeView.vue"),
          meta: { title: "知识库" },
        },
        {
          path: "knowledge/graph",
          name: "knowledge-graph",
          component: () => import("@/views/knowledge/GraphView.vue"),
          meta: { title: "知识图谱" },
        },
        {
          path: "writing",
          name: "writing",
          component: () => import("@/views/writing/WritingView.vue"),
          meta: { title: "写作任务" },
        },
        {
          path: "skills",
          name: "skills",
          component: () => import("@/views/skills/SkillsView.vue"),
          meta: { title: "Skill 工坊" },
        },
        {
          path: "models",
          name: "models",
          component: () => import("@/views/models/ModelsView.vue"),
          meta: { title: "模型中心" },
        },
        {
          path: "evaluation",
          name: "evaluation",
          component: () => import("@/views/evaluation/EvaluationView.vue"),
          meta: { title: "评测中心" },
        },
        {
          path: "system",
          name: "system",
          component: () => import("@/views/system/SystemView.vue"),
          meta: { title: "系统管理" },
        },
      ],
    },
  ],
});

router.afterEach((to) => {
  const productName = "战略规划域多源多模态知识大脑";
  const title = (to.meta.title as string) || productName;
  document.title = title === productName ? productName : `${title} · ${productName}`;
});
