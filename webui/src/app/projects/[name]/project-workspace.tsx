"use client";

import * as Tabs from "@radix-ui/react-tabs";
import { useCallback, useEffect, useState } from "react";

import { MessageInput } from "@/components/chat/message-input";
import { MessageList } from "@/components/chat/message-list";
import { AgentActivity } from "@/components/monitor/agent-activity";
import { CostChart } from "@/components/monitor/cost-chart";
import { ExperimentGrid } from "@/components/monitor/experiment-grid";
import { PipelineProgress } from "@/components/monitor/pipeline-progress";
import { ConfigEditor } from "@/components/project/config-editor";
import { FileBrowser } from "@/components/project/file-browser";
import { TerminalPanel } from "@/components/project/terminal-panel";
import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";
import type { ActiveAgent, CostPayload } from "@/lib/types";
import { useConversationStream } from "@/hooks/use-conversation-stream";
import { useProjectState } from "@/hooks/use-project-state";
import { useProjectStore } from "@/stores/project";

const tabClass =
  "rounded-full px-3.5 py-2 text-[0.95rem] font-medium text-stone-600 transition data-[state=active]:bg-[linear-gradient(145deg,rgba(255,236,224,0.95),rgba(255,247,240,0.98))] data-[state=active]:text-orange-900 data-[state=active]:shadow-[0_10px_24px_rgba(186,101,52,0.16)]";

export function ProjectWorkspace({ project }: { project: string }) {
  const { t, stageLabel } = useI18n();
  const setDashboard = useProjectStore((state) => state.setDashboard);
  const setFiles = useProjectStore((state) => state.setFiles);
  const setConfigContent = useProjectStore((state) => state.setConfigContent);
  const setTerminalInfo = useProjectStore((state) => state.setTerminalInfo);
  const slice = useProjectStore((state) => state.byProject[project]);
  const { connected } = useConversationStream(project);
  const [agents, setAgents] = useState<ActiveAgent[]>([]);
  const [cost, setCost] = useState<CostPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [dashboard, rootFiles, config, terminalInfo, activeAgents, costPayload] = await Promise.all([
        api.getDashboard(project),
        api.getFiles(project),
        api.getConfig(project),
        api.getTerminalInfo(project),
        api.getActiveAgents(project),
        api.getCost(project),
      ]);
      setDashboard(project, dashboard);
      setFiles(project, rootFiles);
      setConfigContent(project, config.content);
      setTerminalInfo(project, terminalInfo);
      setAgents(activeAgents.agents.filter((agent) => agent.project === project));
      setCost(costPayload);
      setError(null);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to load project state");
    }
  }, [project, setConfigContent, setDashboard, setFiles, setTerminalInfo]);

  useEffect(() => {
    const refreshTimer = window.setTimeout(() => {
      void refresh();
    }, 0);
    return () => {
      window.clearTimeout(refreshTimer);
    };
  }, [refresh]);

  useProjectState(project, refresh);

  return (
    <div className="space-y-5">
      <section className="panel-surface overflow-hidden rounded-[30px] px-5 py-6 md:px-7 md:py-7">
        <div className="flex flex-wrap items-start justify-between gap-3.5">
          <div>
            <div className="eyebrow">{t("project")}</div>
            <h1 className="mt-3 font-display text-4xl leading-none text-stone-950 md:text-5xl">{project}</h1>
            <p className="mt-3 max-w-3xl text-[0.95rem] leading-7 text-stone-600">
              {slice?.dashboard?.status?.topic || t("dashboardMetadataPlaceholder")}
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <div className="status-chip rounded-full px-3 py-1.5 text-[0.7rem] uppercase tracking-[0.18em] text-stone-600">
                {connected ? t("conversationLive") : t("conversationRetrying")}
              </div>
              <div className="status-chip rounded-full px-3 py-1.5 text-[0.7rem] uppercase tracking-[0.18em] text-stone-600">
                {slice?.files ? t("indexedEntries", { count: slice.files.dirs.length + slice.files.files.length }) : t("indexPending")}
              </div>
            </div>
          </div>
          <div className="status-chip rounded-full px-3.5 py-1.5 text-xs text-stone-700">
            {stageLabel(slice?.dashboard?.status?.stage || t("loadingStage"))} · {t("iterationLabel", { count: slice?.dashboard?.status?.iteration ?? 0 })}
          </div>
        </div>
        {error ? <div className="mt-4 text-sm text-red-600">{error}</div> : null}
      </section>

      <Tabs.Root defaultValue="chat" className="space-y-3">
        <Tabs.List className="panel-surface inline-flex rounded-full p-[3px]">
          <Tabs.Trigger value="chat" className={tabClass}>{t("chat")}</Tabs.Trigger>
          <Tabs.Trigger value="monitor" className={tabClass}>{t("monitor")}</Tabs.Trigger>
          <Tabs.Trigger value="files" className={tabClass}>{t("files")}</Tabs.Trigger>
          <Tabs.Trigger value="config" className={tabClass}>{t("config")}</Tabs.Trigger>
          <Tabs.Trigger value="terminal" className={tabClass}>{t("terminal")}</Tabs.Trigger>
        </Tabs.List>

        <Tabs.Content value="chat" className="space-y-4">
          <MessageList messages={slice?.messages || []} connected={connected} />
          <MessageInput project={project} />
        </Tabs.Content>

        <Tabs.Content value="monitor" className="space-y-4">
          <PipelineProgress
            stages={slice?.dashboard?.stages || []}
            currentStage={slice?.dashboard?.status?.stage || ""}
          />
          <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
            <ExperimentGrid dashboard={slice?.dashboard || null} />
            <AgentActivity agents={agents} />
          </div>
          <CostChart cost={cost} />
        </Tabs.Content>

        <Tabs.Content value="files">
          <FileBrowser project={project} />
        </Tabs.Content>

        <Tabs.Content value="config">
          <ConfigEditor project={project} />
        </Tabs.Content>

        <Tabs.Content value="terminal">
          <TerminalPanel project={project} />
        </Tabs.Content>
      </Tabs.Root>
    </div>
  );
}
