"use client";

import { ExternalLink } from "lucide-react";
import { useEffect, useState, useTransition } from "react";

import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";
import { useProjectStore } from "@/stores/project";

export function TerminalPanel({ project }: { project: string }) {
  const { t } = useI18n();
  const terminalInfo = useProjectStore((state) => state.byProject[project]?.terminalInfo || null);
  const setTerminalInfo = useProjectStore((state) => state.setTerminalInfo);
  const [message, setMessage] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    startTransition(async () => {
      try {
        const info = await api.getTerminalInfo(project);
        setTerminalInfo(project, info);
      } catch (error) {
        setMessage(error instanceof Error ? error.message : t("terminalLoadFailed"));
      }
    });
  }, [project, setTerminalInfo, t]);

  if (!terminalInfo?.running || !terminalInfo.url) {
    return (
      <div className="panel-surface rounded-[28px] p-6">
        <div className="eyebrow">{t("terminal")}</div>
        <div className="mt-4 rounded-[24px] border border-dashed border-stone-300 px-6 py-10 text-sm text-stone-600">
          {t("terminalHelp")}
          <pre className="mt-4 overflow-x-auto rounded-2xl bg-stone-950 px-4 py-4 text-stone-100">
            {`deploy/ttyd-manager.sh start ${project} sibyl`}
          </pre>
          {message ? <div className="mt-4 text-red-600">{message}</div> : null}
          {isPending ? <div className="mt-3 text-stone-500">{t("loadingTerminalStatus")}</div> : null}
        </div>
      </div>
    );
  }

  return (
    <div className="panel-surface rounded-[28px] p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <div className="eyebrow">{t("liveTerminal")}</div>
          <div className="mt-2 text-sm text-stone-600">
            Port {terminalInfo.port} · PID {terminalInfo.pid}
          </div>
        </div>
        <a
          href={terminalInfo.url}
          target="_blank"
          rel="noreferrer"
          className="status-chip flex items-center gap-2 rounded-full px-4 py-2 text-sm text-stone-700"
        >
          <ExternalLink className="h-4 w-4" />
          {t("open")}
        </a>
      </div>
      <iframe
        src={terminalInfo.url}
        title={`${project} ${t("terminal")}`}
        className="h-[66vh] w-full rounded-[24px] border border-stone-200 bg-black"
      />
    </div>
  );
}
