"use client";

import {
  AlertCircleIcon,
  ExternalLinkIcon,
  FileUpIcon,
  Loader2Icon,
  PencilIcon,
  PlayIcon,
  SparklesIcon,
  Trash2Icon,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  deleteSkill,
  executeSkill,
  fetchSkill,
  fetchSkillHistory,
  fetchSkillsWorkshop,
  importSkillZip,
  saveSkill,
  setSkillEnabled,
} from "@/core/realai/api";
import {
  canDeleteSkill,
  canEditSkill,
  isDeerflowBuiltinSkill,
  isRealAiProjectSkill,
  REALAI_PROJECT_SKILL_IDS,
} from "@/core/realai/skill-origin";
import type { SkillSummary } from "@/core/realai/types";
import { cn } from "@/lib/utils";
import { useQuery, useQueryClient } from "@tanstack/react-query";

export function SkillWorkshopPage() {
  const inputRef = useRef<HTMLInputElement>(null);
  const qc = useQueryClient();
  const [filter, setFilter] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [viewOpen, setViewOpen] = useState(false);
  const [viewBody, setViewBody] = useState("");
  const [viewReadOnly, setViewReadOnly] = useState(true);
  const [executeOpen, setExecuteOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyItems, setHistoryItems] = useState<Record<string, unknown>[]>([]);
  const [executeInput, setExecuteInput] = useState("");
  const [executeOutput, setExecuteOutput] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [deleteTargetId, setDeleteTargetId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"realai" | "deerflow">("realai");
  const [form, setForm] = useState({ id: "", name: "", description: "", body: "" });

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["realai", "skills", "workshop"],
    queryFn: fetchSkillsWorkshop,
  });

  const skills = (data?.skills ?? []).filter((s) => {
    const q = filter.trim().toLowerCase();
    if (!q) return true;
    return (
      s.id.toLowerCase().includes(q) ||
      s.name.toLowerCase().includes(q) ||
      (s.description ?? "").toLowerCase().includes(q)
    );
  });

  const realaiSkills = skills.filter((s) => isRealAiProjectSkill(s));
  const deerflowSkills = skills.filter((s) => isDeerflowBuiltinSkill(s));

  const tabSkills = activeTab === "realai" ? realaiSkills : deerflowSkills;
  const selected = tabSkills.find((s) => s.id === selectedId) ?? null;

  const onTabChange = (value: string) => {
    const tab = value as "realai" | "deerflow";
    setActiveTab(tab);
    const nextList = tab === "realai" ? realaiSkills : deerflowSkills;
    if (selectedId && !nextList.some((s) => s.id === selectedId)) {
      setSelectedId(null);
    }
  };

  const openCreate = () => {
    setEditingId(null);
    setForm({ id: "", name: "", description: "", body: "" });
    setEditorOpen(true);
  };

  const openView = useCallback(async (id: string) => {
    setBusy(`load-${id}`);
    try {
      const skill = await fetchSkill(id);
      setForm({
        id: skill.id,
        name: skill.name,
        description: skill.description,
        body: skill.body,
      });
      setSelectedId(skill.id);
      setViewBody(skill.body || skill.raw || "（无正文）");
      setViewReadOnly(!canEditSkill(skill));
      setViewOpen(true);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "加载失败");
    } finally {
      setBusy(null);
    }
  }, []);

  const openEdit = useCallback(async (id: string) => {
    setBusy(`load-${id}`);
    try {
      const skill = await fetchSkill(id);
      if (!canEditSkill(skill)) {
        toast.error("该 Skill 只读，不可编辑");
        return;
      }
      setForm({
        id: skill.id,
        name: skill.name,
        description: skill.description,
        body: skill.body,
      });
      setEditingId(skill.id);
      setEditorOpen(true);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "加载失败");
    } finally {
      setBusy(null);
    }
  }, []);

  const onSave = useCallback(async () => {
    const id = (editingId || form.id).trim();
    if (!id) {
      toast.error("请填写 skill-id");
      return;
    }
    setBusy("save");
    try {
      await saveSkill(
        id,
        { name: form.name, description: form.description, body: form.body },
        !!editingId,
      );
      toast.success("Skill 已保存并同步到 DeerFlow public/custom");
      setEditorOpen(false);
      await refetch();
      void qc.invalidateQueries({ queryKey: ["realai", "skills"] });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存失败");
    } finally {
      setBusy(null);
    }
  }, [editingId, form, qc, refetch]);

  const onToggleEnabled = useCallback(
    async (skill: SkillSummary, enabled: boolean) => {
      setBusy(`en-${skill.id}`);
      try {
        await setSkillEnabled(skill.id, enabled);
        toast.success(enabled ? "已启用" : "已停用");
        await refetch();
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "启停失败");
      } finally {
        setBusy(null);
      }
    },
    [refetch],
  );

  const onDelete = useCallback(
    async (id: string) => {
      setBusy(`del-${id}`);
      try {
        await deleteSkill(id);
        toast.success("已删除");
        if (selectedId === id) setSelectedId(null);
        await refetch();
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "删除失败");
      } finally {
        setBusy(null);
        setDeleteTargetId(null);
      }
    },
    [refetch, selectedId],
  );

  const onImport = useCallback(
    async (files: FileList | null) => {
      const file = files?.[0];
      if (!file) return;
      setBusy("import");
      try {
        const res = await importSkillZip(file);
        toast.success(`已导入：${res.imported.join(", ")}`);
        await refetch();
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "导入失败");
      } finally {
        setBusy(null);
        if (inputRef.current) inputRef.current.value = "";
      }
    },
    [refetch],
  );

  const onExecute = useCallback(async () => {
    if (!selectedId || !executeInput.trim()) return;
    const skill = skills.find((s) => s.id === selectedId);
    if (skill && !skill.valid) {
      toast.error(`Skill 无效：${skill.errors.join("；")}`);
      return;
    }
    if (skill && !canEditSkill(skill)) {
      toast.error("系统内置 Skill 请在与 Agent 对话中使用 /" + selectedId);
      return;
    }
    setBusy("execute");
    try {
      const res = await executeSkill(selectedId, executeInput.trim());
      setExecuteOutput(res.output);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "执行失败");
    } finally {
      setBusy(null);
    }
  }, [executeInput, selectedId, skills]);

  const openHistory = useCallback(async (id: string) => {
    setBusy(`hist-${id}`);
    try {
      const res = await fetchSkillHistory(id);
      setHistoryItems(res.history);
      setSelectedId(id);
      setHistoryOpen(true);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "无版本历史");
    } finally {
      setBusy(null);
    }
  }, []);

  return (
    <div className="mx-auto flex h-full max-w-5xl flex-col gap-4 p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold">
            <SparklesIcon className="size-6" /> Skill 工坊
          </h1>
          <p className="text-muted-foreground mt-1 text-sm">
            管理 RealAi Skill（维护/试跑/导入）并浏览系统内置 Skill。Agent 对话内用{" "}
            <code className="text-xs">/skill-name</code> 激活；试跑走 RealAi execute。
          </p>
          {data && (
            <p className="text-muted-foreground mt-1 text-xs">
              共 {data.count} 个（RealAi {data.realai_count} · DeerFlow {data.deerflow_count}）
            </p>
          )}
        </div>
        <div className="flex gap-2">
          <Button variant="outline" asChild>
            <Link href="/workspace/chats">返回对话</Link>
          </Button>
        </div>
      </div>

      <Tabs value={activeTab} onValueChange={onTabChange} className="flex min-h-0 flex-1 flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <TabsList>
            <TabsTrigger value="realai">
              RealAi 项目
              {data ? ` (${realaiSkills.length})` : ""}
            </TabsTrigger>
            <TabsTrigger value="deerflow">
              系统内置
              {data ? ` (${deerflowSkills.length})` : ""}
            </TabsTrigger>
          </TabsList>
          {activeTab === "realai" && (
            <div className="flex gap-2">
              <Button variant="outline" onClick={openCreate}>
                新建
              </Button>
              <Button variant="outline" disabled={busy === "import"} onClick={() => inputRef.current?.click()}>
                {busy === "import" ? <Loader2Icon className="size-4 animate-spin" /> : <FileUpIcon className="size-4" />}
                导入 zip
              </Button>
              <input ref={inputRef} type="file" accept=".zip" className="hidden" onChange={(e) => void onImport(e.target.files)} />
            </div>
          )}
        </div>

        <Input placeholder="搜索名称或描述…" value={filter} onChange={(e) => setFilter(e.target.value)} />

        {isLoading ? (
          <p className="text-muted-foreground text-sm">加载中…</p>
        ) : (
          <>
            <TabsContent value="realai" className="mt-0 space-y-4">
              <p className="text-muted-foreground text-xs">
                可编辑、试跑、导入；报告写作/评审等 RealAi 预设也在此页。
              </p>
              <SkillGrid
                skills={realaiSkills}
                selectedId={selectedId}
                busy={busy}
                emptyText="暂无 RealAi Skill，可新建或导入 zip"
                onSelect={setSelectedId}
                onEdit={(id) => void openEdit(id)}
                onView={(id) => void openView(id)}
                onDelete={setDeleteTargetId}
                onExecute={(skill) => {
                  if (!skill.valid) {
                    toast.error(skill.errors.join("；"));
                    return;
                  }
                  setSelectedId(skill.id);
                  setExecuteInput("");
                  setExecuteOutput(null);
                  setExecuteOpen(true);
                }}
                onToggle={(skill, enabled) => void onToggleEnabled(skill, enabled)}
                onHistory={(id) => void openHistory(id)}
              />
            </TabsContent>

            <TabsContent value="deerflow" className="mt-0 space-y-4">
              <p className="text-muted-foreground text-xs">
                英文原版 · 只读 · 在 Agent 对话中用 <code className="text-[10px]">/skill-name</code> 激活。
              </p>
              <SkillGrid
                skills={deerflowSkills}
                selectedId={selectedId}
                busy={busy}
                emptyText="暂无系统内置 Skill"
                onSelect={setSelectedId}
                onEdit={(id) => void openEdit(id)}
                onView={(id) => void openView(id)}
                onDelete={setDeleteTargetId}
                onExecute={(skill) => {
                  toast.info(`请在 Agent 对话输入 /${skill.id} 使用该 Skill`);
                }}
                onToggle={(skill, enabled) => void onToggleEnabled(skill, enabled)}
                onHistory={(id) => void openHistory(id)}
              />
            </TabsContent>
          </>
        )}
      </Tabs>

      {selected && (
        <div className="bg-muted/30 rounded-lg border p-4 text-sm">
          <div className="font-medium">{selected.name}</div>
          <div className="text-muted-foreground mt-1">{selected.description}</div>
          <div className="text-muted-foreground mt-2 flex flex-wrap gap-3 text-xs">
            <span>来源：{isDeerflowBuiltinSkill(selected) ? "系统内置（只读）" : "RealAi 项目"}</span>
            <span>分类：{selected.category ?? "—"}</span>
            <span>版本：{selected.version ? new Date(selected.version).toLocaleString() : "—"}</span>
            <span>{selected.enabled ? "已启用" : "已停用"}</span>
          </div>
        </div>
      )}

      {/* dialogs — same as panel */}
      <Dialog open={viewOpen} onOpenChange={setViewOpen}>
        <DialogContent className="max-h-[85vh] max-w-lg overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{form.name || form.id}</DialogTitle>
            <DialogDescription>
              {viewReadOnly ? "系统内置 Skill · 只读查看" : "RealAi 项目 Skill · 查看"}
            </DialogDescription>
          </DialogHeader>
          <p className="text-muted-foreground text-sm">{form.description}</p>
          <pre className="bg-muted max-h-[50vh] overflow-y-auto rounded p-3 text-xs whitespace-pre-wrap">{viewBody}</pre>
        </DialogContent>
      </Dialog>

      <Dialog open={editorOpen} onOpenChange={setEditorOpen}>
        <DialogContent className="max-h-[85vh] max-w-lg overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editingId ? "编辑 Skill" : "新建 Skill"}</DialogTitle>
            <DialogDescription>保存后自动写入 skills/public 或 custom，并供 DeerFlow Agent 加载</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label htmlFor="ws-skill-id">skill-id</Label>
              <Input id="ws-skill-id" disabled={!!editingId} value={form.id} onChange={(e) => setForm((f) => ({ ...f, id: e.target.value }))} />
            </div>
            <div>
              <Label htmlFor="ws-skill-name">name</Label>
              <Input id="ws-skill-name" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
            </div>
            <div>
              <Label htmlFor="ws-skill-desc">description</Label>
              <Input id="ws-skill-desc" value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
            </div>
            <div>
              <Label htmlFor="ws-skill-body">正文</Label>
              <Textarea id="ws-skill-body" rows={10} value={form.body} onChange={(e) => setForm((f) => ({ ...f, body: e.target.value }))} />
            </div>
            <Button disabled={busy === "save"} onClick={() => void onSave()}>
              {busy === "save" ? <Loader2Icon className="size-4 animate-spin" /> : "保存"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={executeOpen} onOpenChange={setExecuteOpen}>
        <DialogContent className="max-h-[85vh] max-w-lg overflow-y-auto">
          <DialogHeader>
            <DialogTitle>试跑 Skill：{selectedId}</DialogTitle>
            <DialogDescription>指令模式执行（非 Agent 沙箱）</DialogDescription>
          </DialogHeader>
          <Textarea rows={4} value={executeInput} onChange={(e) => setExecuteInput(e.target.value)} />
          <Button disabled={busy === "execute"} onClick={() => void onExecute()}>
            {busy === "execute" ? <Loader2Icon className="size-4 animate-spin" /> : <PlayIcon className="size-4" />}
            执行
          </Button>
          {executeOutput && (
            <pre className="bg-muted mt-2 max-h-48 overflow-y-auto rounded p-2 text-xs whitespace-pre-wrap">{executeOutput}</pre>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={historyOpen} onOpenChange={setHistoryOpen}>
        <DialogContent className="max-h-[85vh] max-w-lg overflow-y-auto">
          <DialogHeader>
            <DialogTitle>版本历史：{selectedId}</DialogTitle>
            <DialogDescription>custom Skill 保存时追加记录</DialogDescription>
          </DialogHeader>
          <ul className="space-y-2 text-xs">
            {historyItems.map((h, i) => (
              <li key={i} className="bg-muted rounded p-2">
                <div>{String(h.ts ?? "")}</div>
                <div className="text-muted-foreground">{String(h.action ?? "")}</div>
              </li>
            ))}
            {historyItems.length === 0 && <li className="text-muted-foreground">暂无历史</li>}
          </ul>
        </DialogContent>
      </Dialog>

      <Dialog open={!!deleteTargetId} onOpenChange={(open) => !open && setDeleteTargetId(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>删除 Skill</DialogTitle>
            <DialogDescription>
              确定删除「{deleteTargetId}」？此操作不可撤销。
              {deleteTargetId && REALAI_PROJECT_SKILL_IDS.has(deleteTargetId)
                ? " 预置 Skill 删除后不会在重启时自动恢复。"
                : ""}
            </DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setDeleteTargetId(null)}>
              取消
            </Button>
            <Button
              variant="destructive"
              disabled={!!deleteTargetId && busy === `del-${deleteTargetId}`}
              onClick={() => deleteTargetId && void onDelete(deleteTargetId)}
            >
              {deleteTargetId && busy === `del-${deleteTargetId}` ? (
                <Loader2Icon className="size-4 animate-spin" />
              ) : (
                "删除"
              )}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function SkillGrid({
  skills,
  selectedId,
  busy,
  emptyText,
  onSelect,
  onEdit,
  onView,
  onDelete,
  onExecute,
  onToggle,
  onHistory,
}: {
  skills: SkillSummary[];
  selectedId: string | null;
  busy: string | null;
  emptyText: string;
  onSelect: (id: string) => void;
  onEdit: (id: string) => void;
  onView: (id: string) => void;
  onDelete: (id: string) => void;
  onExecute: (skill: SkillSummary) => void;
  onToggle: (skill: SkillSummary, enabled: boolean) => void;
  onHistory: (id: string) => void;
}) {
  if (skills.length === 0) {
    return <p className="text-muted-foreground text-sm">{emptyText}</p>;
  }
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {skills.map((skill) => (
        <SkillCard
          key={skill.id}
          skill={skill}
          selected={selectedId === skill.id}
          busy={busy}
          onSelect={() => onSelect(skill.id)}
          onEdit={() => onEdit(skill.id)}
          onView={() => onView(skill.id)}
          onDelete={() => onDelete(skill.id)}
          onExecute={() => onExecute(skill)}
          onToggle={(enabled) => onToggle(skill, enabled)}
          onHistory={() => onHistory(skill.id)}
        />
      ))}
    </div>
  );
}

function SkillCard({
  skill,
  selected,
  busy,
  onSelect,
  onEdit,
  onView,
  onDelete,
  onExecute,
  onToggle,
  onHistory,
}: {
  skill: SkillSummary;
  selected: boolean;
  busy: string | null;
  onSelect: () => void;
  onEdit: () => void;
  onView: () => void;
  onDelete: () => void;
  onExecute: () => void;
  onToggle: (enabled: boolean) => void;
  onHistory: () => void;
}) {
  const readOnly = !canEditSkill(skill);
  const deletable = canDeleteSkill(skill);
  const deerflow = isDeerflowBuiltinSkill(skill);
  return (
    <div
      className={cn(
        "rounded-lg border p-3 transition-colors",
        selected && "border-primary/50 bg-primary/5",
        !skill.valid && "border-destructive/30",
      )}
    >
      <button type="button" className="w-full text-left" onClick={onSelect}>
        <div className="flex items-center gap-2">
          {!skill.valid && <AlertCircleIcon className="text-destructive size-4" />}
          <span className="font-medium">{skill.name || skill.id}</span>
          <span className="text-muted-foreground ml-auto text-[10px] uppercase">
            {deerflow ? "DeerFlow · 只读" : "RealAi"}
          </span>
        </div>
        <p className="text-muted-foreground mt-1 line-clamp-2 text-xs">{skill.description}</p>
      </button>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
        <div className="flex items-center gap-1">
          <Switch
            checked={skill.enabled !== false}
            disabled={busy === `en-${skill.id}`}
            onCheckedChange={onToggle}
          />
          <span>{skill.enabled !== false ? "启用" : "停用"}</span>
        </div>
        {skill.version && (
          <span className="text-muted-foreground">{new Date(skill.version).toLocaleDateString()}</span>
        )}
        <div className="ml-auto flex gap-1">
          {readOnly ? (
            <Button size="icon" variant="ghost" className="size-7" onClick={onView} title="查看">
              <ExternalLinkIcon className="size-3.5" />
            </Button>
          ) : (
            <>
              <Button size="icon" variant="ghost" className="size-7" onClick={onExecute} title="试跑">
                <PlayIcon className="size-3.5" />
              </Button>
              <Button size="icon" variant="ghost" className="size-7" onClick={onHistory} title="版本">
                <ExternalLinkIcon className="size-3.5" />
              </Button>
              <Button size="icon" variant="ghost" className="size-7" onClick={onEdit} title="编辑">
                <PencilIcon className="size-3.5" />
              </Button>
              {deletable && (
                <Button
                  size="icon"
                  variant="ghost"
                  className="size-7"
                  disabled={busy === `del-${skill.id}`}
                  onClick={onDelete}
                  title="删除"
                >
                  <Trash2Icon className="size-3.5" />
                </Button>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
