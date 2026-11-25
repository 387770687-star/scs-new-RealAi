"use client";

import { Loader2Icon, Settings2Icon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { fetchRealAiConfig, saveRealAiConfig, syncRealAiConfig } from "@/core/realai/api";
import type { RealAiSettings } from "@/core/realai/types";
import { useI18n } from "@/core/i18n/hooks";

import { SettingsSection } from "./settings-section";

const EMPTY: RealAiSettings = {
  obsidianVaultPath: "./vault",
  llm: {
    provider: "minimax",
    modelId: "minimax-m3",
    model: "MiniMax M3",
    baseUrl: "https://api.minimaxi.com/v1",
    hasApiKey: false,
    apiKeyPreview: "",
  },
  report: {
    outputDir: "./vault/reports",
    stepConfirm: false,
    researcherSkillId: "strategic-planning-researcher",
    architectSkillId: "strategic-planning-architect",
    writerSkillId: "strategic-planning-writer",
    citerSkillId: "strategic-planning-citer",
    reviewSkillId: "strategic-planning-reviewer",
    optimizerSkillId: "strategic-planning-optimizer",
  },
  search: { webSearchEnabled: false },
  data: { excelRoots: ["./vault"], databases: [] },
};

export function RealAiSettingsPage() {
  const { t } = useI18n();
  const tr = t.settings.realai;
  const [form, setForm] = useState<RealAiSettings>(EMPTY);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [dbJson, setDbJson] = useState("[]");
  const [excelRoots, setExcelRoots] = useState("./vault");
  const [vaultResolved, setVaultResolved] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const res = await fetchRealAiConfig();
      setVaultResolved(res.vault_path);
      const s = { ...EMPTY, ...res.settings };
      setForm(s);
      setExcelRoots((s.data?.excelRoots ?? ["./vault"]).join("\n"));
      setDbJson(JSON.stringify(s.data?.databases ?? [], null, 2));
      setApiKeyInput("");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : tr.loadFailed);
    } finally {
      setBusy(false);
    }
  }, [tr.loadFailed]);

  useEffect(() => {
    void load();
  }, [load]);

  const onSave = useCallback(async () => {
    type DbRow = { name: string; url: string; enabled?: boolean };
    let databases: DbRow[] = [];
    try {
      databases = JSON.parse(dbJson) as DbRow[];
      if (!Array.isArray(databases)) throw new Error("not array");
    } catch {
      toast.error(tr.invalidDbJson);
      return;
    }

    setBusy(true);
    try {
      const res = await saveRealAiConfig({
        obsidianVaultPath: form.obsidianVaultPath,
        llm: {
          provider: "minimax",
          modelId: form.llm?.modelId || "minimax-m3",
          model: form.llm?.model || "MiniMax M3",
          baseUrl: form.llm?.baseUrl || EMPTY.llm!.baseUrl,
          ...(apiKeyInput.trim() ? { apiKey: apiKeyInput.trim() } : {}),
        },
        report: form.report,
        search: form.search,
        data: {
          excelRoots: excelRoots
            .split(/\r?\n/)
            .map((l) => l.trim())
            .filter(Boolean),
          databases,
        },
      });
      toast.success(res.message || tr.saveSuccess);
      setVaultResolved(res.vault_path);
      setForm({ ...EMPTY, ...res.settings });
      setApiKeyInput("");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : tr.saveFailed);
    } finally {
      setBusy(false);
    }
  }, [apiKeyInput, dbJson, excelRoots, form, tr]);

  const onSync = useCallback(async () => {
    setBusy(true);
    try {
      await syncRealAiConfig();
      toast.success(tr.syncSuccess);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : tr.syncFailed);
    } finally {
      setBusy(false);
    }
  }, [tr]);

  return (
    <div className="space-y-8">
      <SettingsSection title={tr.title} description={tr.description}>
        <p className="text-muted-foreground text-xs">
          {tr.deerflowHint} {vaultResolved && <>· Vault: {vaultResolved}</>}
        </p>
      </SettingsSection>

      <SettingsSection title={tr.llmTitle} description={tr.llmDescription}>
        <div className="grid max-w-xl gap-4">
          <div>
            <Label htmlFor="ra-key">{tr.apiKey}</Label>
            <Input
              id="ra-key"
              type="password"
              placeholder={
                form.llm?.hasApiKey
                  ? `${tr.apiKeyKeepPrefix} (${form.llm.apiKeyPreview || "****"})`
                  : tr.apiKeyPlaceholder
              }
              value={apiKeyInput}
              onChange={(e) => setApiKeyInput(e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="ra-base">{tr.baseUrl}</Label>
            <Input
              id="ra-base"
              value={form.llm?.baseUrl || ""}
              onChange={(e) => setForm((f) => ({ ...f, llm: { ...f.llm!, baseUrl: e.target.value } }))}
            />
          </div>
          <div>
            <Label htmlFor="ra-model">{tr.modelId}</Label>
            <Input
              id="ra-model"
              value={form.llm?.modelId || "minimax-m3"}
              onChange={(e) => setForm((f) => ({ ...f, llm: { ...f.llm!, modelId: e.target.value } }))}
            />
          </div>
        </div>
      </SettingsSection>

      <SettingsSection title={tr.vaultTitle} description={tr.vaultDescription}>
        <div className="max-w-xl">
          <Label htmlFor="ra-vault">{tr.vaultPath}</Label>
          <Input
            id="ra-vault"
            value={form.obsidianVaultPath || ""}
            onChange={(e) => setForm((f) => ({ ...f, obsidianVaultPath: e.target.value }))}
          />
        </div>
      </SettingsSection>

      <SettingsSection title={tr.reportTitle} description={tr.reportDescription}>
        <div className="grid max-w-xl gap-4">
          <div>
            <Label htmlFor="ra-report-out">{tr.reportOutput}</Label>
            <Input
              id="ra-report-out"
              value={form.report?.outputDir || ""}
              onChange={(e) => setForm((f) => ({ ...f, report: { ...f.report!, outputDir: e.target.value } }))}
            />
          </div>
          <div className="flex items-center gap-2">
            <Checkbox
              id="ra-step"
              checked={!!form.report?.stepConfirm}
              onCheckedChange={(v) =>
                setForm((f) => ({ ...f, report: { ...f.report!, stepConfirm: v === true } }))
              }
            />
            <Label htmlFor="ra-step">{tr.stepConfirm}</Label>
          </div>
          <div>
            <Label htmlFor="ra-wskill">{tr.writerSkill}</Label>
            <Input
              id="ra-wskill"
              value={form.report?.writerSkillId || ""}
              onChange={(e) =>
                setForm((f) => ({ ...f, report: { ...f.report!, writerSkillId: e.target.value } }))
              }
            />
          </div>
          <div>
            <Label htmlFor="ra-rskill">{tr.reviewSkill}</Label>
            <Input
              id="ra-rskill"
              value={form.report?.reviewSkillId || ""}
              onChange={(e) =>
                setForm((f) => ({ ...f, report: { ...f.report!, reviewSkillId: e.target.value } }))
              }
            />
          </div>
        </div>
      </SettingsSection>

      <SettingsSection title={tr.dataTitle} description={tr.dataDescription}>
        <div className="grid max-w-xl gap-4">
          <div>
            <Label htmlFor="ra-excel">{tr.excelRoots}</Label>
            <Textarea
              id="ra-excel"
              rows={3}
              value={excelRoots}
              onChange={(e) => setExcelRoots(e.target.value)}
              placeholder="./vault"
            />
          </div>
          <div>
            <Label htmlFor="ra-db">{tr.databases}</Label>
            <Textarea id="ra-db" rows={6} className="font-mono text-xs" value={dbJson} onChange={(e) => setDbJson(e.target.value)} />
          </div>
        </div>
      </SettingsSection>

      <SettingsSection title={tr.searchTitle} description={tr.searchDescription}>
        <div className="flex items-center gap-2">
          <Checkbox
            id="ra-web"
            checked={!!form.search?.webSearchEnabled}
            onCheckedChange={(v) => setForm((f) => ({ ...f, search: { webSearchEnabled: v === true } }))}
          />
          <Label htmlFor="ra-web">{tr.webDefault}</Label>
        </div>
      </SettingsSection>

      <div className="flex flex-wrap gap-2">
        <Button disabled={busy} onClick={() => void onSave()}>
          {busy ? <Loader2Icon className="size-4 animate-spin" /> : <Settings2Icon className="size-4" />}
          {tr.save}
        </Button>
        <Button variant="outline" disabled={busy} onClick={() => void onSync()}>
          {tr.syncDeerflow}
        </Button>
        <Button variant="ghost" disabled={busy} onClick={() => void load()}>
          {tr.reload}
        </Button>
      </div>
    </div>
  );
}
