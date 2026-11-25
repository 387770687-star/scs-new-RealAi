"use client";

import { CheckCircle2Icon, Loader2Icon, SparklesIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  completeOnboarding,
  fetchOnboardingStatus,
  fetchRealAiHealth,
} from "@/core/realai/api";
import { useQuery, useQueryClient } from "@tanstack/react-query";

export function RealAiOnboardingGate() {
  const router = useRouter();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);
  const [apiKey, setApiKey] = useState("");
  const [webSearch, setWebSearch] = useState(false);
  const [importDemo, setImportDemo] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [healthOk, setHealthOk] = useState<boolean | null>(null);

  const { data: status } = useQuery({
    queryKey: ["realai", "onboarding"],
    queryFn: fetchOnboardingStatus,
    staleTime: 60_000,
  });

  useEffect(() => {
    if (status?.needed) setOpen(true);
  }, [status?.needed]);

  const runHealthCheck = useCallback(async () => {
    setHealthOk(null);
    try {
      const h = await fetchRealAiHealth();
      setHealthOk(Boolean(h.vault_exists !== false));
      toast.success(`健康检查通过 · 知识库 ${h.vault_file_count ?? 0} 个文件`);
    } catch (err) {
      setHealthOk(false);
      toast.error(err instanceof Error ? err.message : "健康检查失败");
    }
  }, []);

  const onComplete = useCallback(async () => {
    if (!apiKey.trim()) {
      toast.error("请填写 MiniMax API Key");
      return;
    }
    setSubmitting(true);
    try {
      await completeOnboarding({
        api_key: apiKey.trim(),
        web_search_enabled: webSearch,
        import_demo: importDemo,
      });
      await qc.invalidateQueries({ queryKey: ["realai"] });
      toast.success("欢迎使用 RealAi！");
      setOpen(false);
      router.refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "向导完成失败");
    } finally {
      setSubmitting(false);
    }
  }, [apiKey, webSearch, importDemo, qc, router]);

  if (!status?.needed) return null;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="sm:max-w-lg" onPointerDownOutside={(e) => e.preventDefault()}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <SparklesIcon className="size-5" /> RealAi 首次设置
          </DialogTitle>
          <DialogDescription>
            只需几步：配置模型 Key、选择是否联网、导入示例资料并完成健康检查。
          </DialogDescription>
        </DialogHeader>

        {step === 0 && (
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label htmlFor="onboard-key">MiniMax API Key</Label>
              <Input
                id="onboard-key"
                type="password"
                placeholder="在 minimaxi.com 获取"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="onboard-web">默认开启联网搜索</Label>
              <Switch id="onboard-web" checked={webSearch} onCheckedChange={setWebSearch} />
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="onboard-demo">导入油气管道示例资料</Label>
              <Switch id="onboard-demo" checked={importDemo} onCheckedChange={setImportDemo} />
            </div>
          </div>
        )}

        {step === 1 && (
          <div className="space-y-3 py-4 text-sm">
            <p className="text-muted-foreground">
              点击「运行健康检查」确认后端与知识库目录可用。通过后点「完成」进入主界面。
            </p>
            {healthOk === true && (
              <p className="flex items-center gap-1 text-green-600">
                <CheckCircle2Icon className="size-4" /> 检查通过
              </p>
            )}
            {healthOk === false && (
              <p className="text-destructive">检查未通过，请确认 RealAi 后端已启动。</p>
            )}
          </div>
        )}

        <DialogFooter className="gap-2 sm:gap-0">
          {step === 0 ? (
            <Button onClick={() => setStep(1)} disabled={!apiKey.trim()}>
              下一步
            </Button>
          ) : (
            <>
              <Button variant="outline" onClick={() => void runHealthCheck()}>
                运行健康检查
              </Button>
              <Button onClick={() => void onComplete()} disabled={submitting || healthOk !== true}>
                {submitting ? <Loader2Icon className="size-4 animate-spin" /> : "完成"}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
