"use client";

import { Loader2, RefreshCw, Save } from "lucide-react";
import { useEffect, useState, useTransition } from "react";

import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";
import { useProjectStore } from "@/stores/project";

export function ConfigEditor({ project }: { project: string }) {
  const { t } = useI18n();
  const configContent = useProjectStore((state) => state.byProject[project]?.configContent || "");
  const setConfigContent = useProjectStore((state) => state.setConfigContent);
  const [status, setStatus] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    startTransition(async () => {
      try {
        const payload = await api.getConfig(project);
        setConfigContent(project, payload.content);
      } catch (error) {
        setStatus(error instanceof Error ? error.message : t("configLoadFailed"));
      }
    });
  }, [project, setConfigContent, t]);

  function reload() {
    startTransition(async () => {
      try {
        const payload = await api.getConfig(project);
        setConfigContent(project, payload.content);
        setStatus(t("configReloaded"));
      } catch (error) {
        setStatus(error instanceof Error ? error.message : t("configReloadFailed"));
      }
    });
  }

  function save() {
    startTransition(async () => {
      try {
        await api.saveConfig(project, configContent);
        setStatus(t("configSaved"));
      } catch (error) {
        setStatus(error instanceof Error ? error.message : t("configSaveFailed"));
      }
    });
  }

  return (
    <div className="panel-surface rounded-[28px] p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="eyebrow">config.yaml</div>
          <p className="mt-2 text-sm text-stone-600">
            {t("configDescription")}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={reload}
            className="status-chip flex items-center gap-2 rounded-full px-4 py-2 text-sm text-stone-700"
          >
            <RefreshCw className="h-4 w-4" />
            {t("reload")}
          </button>
          <button
            type="button"
            onClick={save}
            className="flex items-center gap-2 rounded-full bg-[linear-gradient(180deg,#cf6634,#a94821)] px-4 py-2 text-sm text-white"
          >
            {isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            {t("save")}
          </button>
        </div>
      </div>

      <textarea
        value={configContent}
        onChange={(event) => setConfigContent(project, event.target.value)}
        className="min-h-[420px] w-full rounded-[24px] border border-stone-200 bg-[#17120e] px-4 py-4 font-mono text-sm text-stone-100 outline-none transition focus:border-orange-300"
      />
      {status ? <div className="mt-3 text-sm text-stone-600">{status}</div> : null}
    </div>
  );
}
