"use client";

import { BookOpenCheckIcon, FileTextIcon, GlobeIcon, Loader2Icon } from "lucide-react";
import { useCallback, useState } from "react";
import { toast } from "sonner";

import { ReportProgressDialog } from "@/components/realai/report-progress-dialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  fetchRealAiConfig,
  lightAsk,
  runReportStream,
} from "@/core/realai/api";
import type { AgentProgressStep } from "@/core/realai/types";
import { useRealAi } from "@/core/realai/store";

const INITIAL_STEPS: AgentProgressStep[] = [
  { id: "lead", label: "战略主 Agent", status: "pending" },
  { id: "arch", label: "大纲架构", status: "pending" },
  { id: "retrieve", label: "知识检索", status: "pending" },
  { id: "data", label: "问数分析", status: "pending" },
  { id: "vision", label: "视觉分析", status: "pending" },
  { id: "writer", label: "正文写作", status: "pending" },
  { id: "evidence_audit", label: "证据审核", status: "pending" },
  { id: "review", label: "管网评审", status: "pending" },
];

export function RealAiToolbar() {
  const {
    webSearchEnabled,
    setWebSearchEnabled,
    openEvidence,
    vaultBanner,
    setVaultBanner,
  } = useRealAi();
  const [busy, setBusy] = useState<"light" | "report" | null>(null);
  const [lightAnswer, setLightAnswer] = useState<string | null>(null);
  const [reportPreview, setReportPreview] = useState<string | null>(null);
  const [outlinePreview, setOutlinePreview] = useState<string | null>(null);
  const [pendingGoal, setPendingGoal] = useState<string | null>(null);
  const [reportGoalOpen, setReportGoalOpen] = useState(false);
  const [reportGoal, setReportGoal] = useState("");
  const [progressOpen, setProgressOpen] = useState(false);
  const [progressGoal, setProgressGoal] = useState("");
  const [progressSteps, setProgressSteps] = useState<AgentProgressStep[]>(INITIAL_STEPS);
  const [progressPhase, setProgressPhase] = useState<string | undefined>();
  const [lightQueryOpen, setLightQueryOpen] = useState(false);
  const [lightQuery, setLightQuery] = useState("");

  const submitLightAsk = useCallback(async () => {
    const query = lightQuery.trim();
    if (!query) return;
    setLightQueryOpen(false);
    setBusy("light");
    try {
      const res = await lightAsk(query, webSearchEnabled);
      openEvidence(res.evidence);
      setLightAnswer(res.answer);
      toast.success("轻量问答完成");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "轻量问答失败");
    } finally {
      setBusy(null);
    }
  }, [lightQuery, openEvidence, webSearchEnabled]);

  const runReportFlow = useCallback(
    async (goal: string, stepConfirm: boolean, confirmed: boolean) => {
      setProgressGoal(goal);
      setProgressSteps(INITIAL_STEPS);
      setProgressPhase(undefined);
      setProgressOpen(true);

      const res = await runReportStream(goal, stepConfirm, confirmed, (steps) => {
        setProgressSteps(steps);
      });

      setProgressPhase(res.phase);
      if (res.agent_progress?.length) {
        setProgressSteps(res.agent_progress);
      }

      if (res.phase === "await_outline_confirm") {
        setPendingGoal(goal);
        setOutlinePreview(JSON.stringify(res.outline, null, 2));
        openEvidence(res.evidence);
        return;
      }

      openEvidence(res.evidence);
      setReportPreview(res.preview_markdown ?? "");
      toast.success(
        `报告已写入 ${res.vault_path}${res.vault_path_docx ? ` 与 ${res.vault_path_docx}` : ""}`,
      );
    },
    [openEvidence],
  );

  const startReport = useCallback(async () => {
    const goal = reportGoal.trim();
    if (!goal) return;
    setReportGoalOpen(false);
    setBusy("report");
    try {
      const cfg = await fetchRealAiConfig();
      const stepConfirm = Boolean(
        (cfg.settings?.report as { stepConfirm?: boolean } | undefined)?.stepConfirm,
      );
      await runReportFlow(goal, stepConfirm, false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "报告生成失败");
    } finally {
      setBusy(null);
    }
  }, [reportGoal, runReportFlow]);

  const confirmOutline = useCallback(async () => {
    if (!pendingGoal) return;
    setBusy("report");
    try {
      const cfg = await fetchRealAiConfig();
      const stepConfirm = Boolean(
        (cfg.settings?.report as { stepConfirm?: boolean } | undefined)?.stepConfirm,
      );
      await runReportFlow(pendingGoal, stepConfirm, true);
      setOutlinePreview(null);
      setPendingGoal(null);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "报告生成失败");
    } finally {
      setBusy(null);
    }
  }, [pendingGoal, runReportFlow]);

  return (
    <>
      <div className="bg-muted/40 flex flex-wrap items-center gap-3 border-b px-3 py-2 text-sm">
        {vaultBanner && (
          <button
            type="button"
            className="text-primary text-xs underline"
            onClick={() => setVaultBanner(null)}
          >
            {vaultBanner}（点击关闭）
          </button>
        )}
        <div className="flex items-center gap-2">
          <Checkbox
            id="realai-web"
            checked={webSearchEnabled}
            onCheckedChange={(v) => setWebSearchEnabled(v === true)}
          />
          <Label htmlFor="realai-web" className="flex items-center gap-1 text-xs">
            <GlobeIcon className="size-3.5" /> 同时搜联网
          </Label>
        </div>
        <Button
          size="sm"
          variant="secondary"
          disabled={!!busy}
          onClick={() => {
            setLightQuery("");
            setLightQueryOpen(true);
          }}
        >
          {busy === "light" ? (
            <Loader2Icon className="size-4 animate-spin" />
          ) : (
            <BookOpenCheckIcon className="size-4" />
          )}
          轻量循证
        </Button>
        <Button
          size="sm"
          variant="default"
          disabled={!!busy}
          onClick={() => {
            setReportGoal("");
            setReportGoalOpen(true);
          }}
        >
          {busy === "report" ? (
            <Loader2Icon className="size-4 animate-spin" />
          ) : (
            <FileTextIcon className="size-4" />
          )}
          生成报告
        </Button>
      </div>

      <Dialog open={lightQueryOpen} onOpenChange={setLightQueryOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>轻量循证问答</DialogTitle>
            <DialogDescription>
              基于知识库检索与问数；{webSearchEnabled ? "已开启联网补充" : "未勾选联网"}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="light-query">你的问题</Label>
            <Textarea
              id="light-query"
              rows={4}
              placeholder="例如：去年采用了哪些降本策略？综合运营成本降低了多少？"
              value={lightQuery}
              onChange={(e) => setLightQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                  e.preventDefault();
                  void submitLightAsk();
                }
              }}
            />
            <p className="text-muted-foreground text-xs">Ctrl+Enter 提交</p>
          </div>
          <Button disabled={!lightQuery.trim() || !!busy} onClick={() => void submitLightAsk()}>
            {busy === "light" ? <Loader2Icon className="size-4 animate-spin" /> : "开始问答"}
          </Button>
        </DialogContent>
      </Dialog>

      <Dialog open={reportGoalOpen} onOpenChange={setReportGoalOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>生成报告</DialogTitle>
            <DialogDescription>将依次运行 8 个子 Agent，可在进度面板查看状态</DialogDescription>
          </DialogHeader>
          <Input
            placeholder="例如：油气管道工程建设进展周报"
            value={reportGoal}
            onChange={(e) => setReportGoal(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void startReport()}
          />
          <Button disabled={!reportGoal.trim() || !!busy} onClick={() => void startReport()}>
            开始生成
          </Button>
        </DialogContent>
      </Dialog>

      <ReportProgressDialog
        open={progressOpen}
        goal={progressGoal}
        steps={progressSteps}
        phase={progressPhase}
        onOpenChange={setProgressOpen}
      />

      <Dialog open={!!lightAnswer} onOpenChange={(open) => !open && setLightAnswer(null)}>
        <DialogContent className="max-h-[80vh] max-w-lg overflow-y-auto">
          <DialogHeader>
            <DialogTitle>轻量循证回答</DialogTitle>
            <DialogDescription>可打开循证抽屉查看 kb / data / web 分区依据</DialogDescription>
          </DialogHeader>
          <div className="text-sm whitespace-pre-wrap">{lightAnswer}</div>
        </DialogContent>
      </Dialog>

      <Dialog
        open={!!outlinePreview}
        onOpenChange={(open) => {
          if (!open) {
            setOutlinePreview(null);
            setPendingGoal(null);
          }
        }}
      >
        <DialogContent className="max-h-[80vh] max-w-lg overflow-y-auto">
          <DialogHeader>
            <DialogTitle>确认报告大纲（逐步确认）</DialogTitle>
            <DialogDescription>确认后将生成正文并导出 MD / Word</DialogDescription>
          </DialogHeader>
          <pre className="text-xs whitespace-pre-wrap">{outlinePreview}</pre>
          <Button onClick={() => void confirmOutline()} disabled={!!busy}>
            确认并生成报告
          </Button>
        </DialogContent>
      </Dialog>

      <Dialog open={!!reportPreview} onOpenChange={(open) => !open && setReportPreview(null)}>
        <DialogContent className="max-h-[80vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>报告预览</DialogTitle>
            <DialogDescription>Markdown 与 Word 已写入 Vault reports 目录</DialogDescription>
          </DialogHeader>
          <pre className="text-xs whitespace-pre-wrap">{reportPreview}</pre>
        </DialogContent>
      </Dialog>
    </>
  );
}
