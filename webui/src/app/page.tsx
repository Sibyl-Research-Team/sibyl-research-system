"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AgentActivity } from "@/components/monitor/agent-activity";
import { CostChart } from "@/components/monitor/cost-chart";
import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";
import type { ActiveAgent, CostPayload } from "@/lib/types";
import { useSystemStore } from "@/stores/system";

export default function HomePage() {
  const { projects, systemStatus, loadOverview, loading, error } = useSystemStore();
  const { t, stageLabel } = useI18n();
  const [agents, setAgents] = useState<ActiveAgent[]>([]);
  const [cost, setCost] = useState<CostPayload | null>(null);
  const [gpuLeases, setGpuLeases] = useState<Record<string, { project_name?: string; task_ids?: string[] }>>({});

  useEffect(() => {
    void loadOverview();
    void api.getActiveAgents().then((payload) => setAgents(payload.agents)).catch(() => undefined);
    void api.getCost().then(setCost).catch(() => undefined);
    void api.getGpuOverview().then((payload) => setGpuLeases(payload.leases)).catch(() => undefined);
  }, [loadOverview]);

  return (
    <div className="space-y-6">
      <section className="panel-surface overflow-hidden rounded-[34px] px-6 py-7 md:px-8 md:py-8">
        <div className="grid gap-8 xl:grid-cols-[1.15fr_0.85fr] xl:items-end">
          <div className="relative">
            <div className="eyebrow">{t("systemOverview")}</div>
            <h1 className="mt-4 max-w-3xl font-display text-5xl leading-[0.9] text-stone-950 md:text-7xl">
              {t("heroTitle")}
            </h1>
            <p className="mt-5 max-w-2xl text-sm leading-8 text-stone-600 md:text-[0.96rem]">
              {t("heroDescription")}
            </p>
            <div className="mt-6 flex flex-wrap gap-2">
              <div className="status-chip rounded-full px-3 py-2 text-xs tracking-[0.18em] text-stone-600">
                {t("trackedWorkspaces", { count: projects.length })}
              </div>
              <div className="status-chip rounded-full px-3 py-2 text-xs tracking-[0.18em] text-stone-600">
                {t("gpuLanes", { count: Object.keys(gpuLeases).length })}
              </div>
              <div className="status-chip rounded-full px-3 py-2 text-xs tracking-[0.18em] text-stone-600">
                {t("usageSamples", { count: cost?.timeline.length ?? 0 })}
              </div>
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="panel-soft rounded-[24px] px-4 py-4">
              <div className="text-[0.68rem] uppercase tracking-[0.28em] text-stone-500">{t("projects")}</div>
              <div className="mt-3 text-4xl font-semibold leading-none text-stone-950">
                {systemStatus?.project_count ?? projects.length}
              </div>
            </div>
            <div className="panel-soft rounded-[24px] px-4 py-4">
              <div className="text-[0.68rem] uppercase tracking-[0.28em] text-stone-500">{t("activeAgents")}</div>
              <div className="mt-3 text-4xl font-semibold leading-none text-stone-950">{agents.length}</div>
            </div>
            <div className="panel-soft rounded-[24px] px-4 py-4">
              <div className="text-[0.68rem] uppercase tracking-[0.28em] text-stone-500">{t("runtimeReady")}</div>
              <div className="mt-3 text-4xl font-semibold leading-none text-stone-950">
                {systemStatus?.runtime_ready_count ?? 0}
              </div>
            </div>
            <div className="panel-soft rounded-[24px] px-4 py-4">
              <div className="text-[0.68rem] uppercase tracking-[0.28em] text-stone-500">{t("totalTokens")}</div>
              <div className="mt-3 text-4xl font-semibold leading-none text-stone-950">
                {(cost?.totals.input_tokens ?? 0) + (cost?.totals.output_tokens ?? 0)}
              </div>
            </div>
          </div>
        </div>
        {error ? <div className="mt-4 text-sm text-red-600">{error}</div> : null}
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.08fr_0.92fr]">
        <div className="panel-surface rounded-[30px] p-5 md:p-6">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <div className="eyebrow">{t("projects")}</div>
              <div className="mt-2 text-xl font-medium text-stone-950">{t("openWorkspace")}</div>
            </div>
            {loading ? <div className="text-sm text-stone-500">{t("refreshing")}</div> : null}
          </div>
          <div className="mb-4 rounded-[24px] border border-stone-200/80 bg-white/65 px-4 py-4 text-sm text-stone-600">
            {systemStatus?.workspaces_dir ? (
              <div>{t("workspaceSource", { path: systemStatus.workspaces_dir })}</div>
            ) : null}
            <div className={systemStatus?.workspaces_dir ? "mt-2" : undefined}>{t("workspaceRecognitionHint")}</div>
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            {projects.map((project) => (
              <Link
                key={project.name}
                href={`/projects/${project.name}`}
                className="group rounded-[26px] border border-stone-200/85 bg-[linear-gradient(145deg,rgba(255,255,255,0.78),rgba(250,240,228,0.86))] px-5 py-5 transition hover:-translate-y-0.5 hover:border-orange-300 hover:shadow-[0_18px_34px_rgba(186,101,52,0.14)]"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="font-display text-[2rem] leading-none text-stone-950">{project.name}</div>
                    <div className="mt-3 text-sm leading-7 text-stone-600">{project.topic || t("noTopicRecorded")}</div>
                  </div>
                  <div className="status-chip rounded-full px-3 py-1 text-xs uppercase tracking-[0.18em] text-stone-500">
                    {stageLabel(project.stage)}
                  </div>
                </div>
                <div className="mt-5 flex flex-wrap items-center gap-2 text-xs uppercase tracking-[0.18em] text-stone-500">
                  <span className="rounded-full bg-white/75 px-3 py-1">{t("iterationLabel", { count: project.iteration })}</span>
                  <span className="rounded-full bg-white/75 px-3 py-1">
                    {project.runtime_ready ? t("runtimeReadyChip") : t("setupNeeded")}
                  </span>
                </div>
              </Link>
            ))}
            {!loading && projects.length === 0 ? (
              <div className="rounded-[26px] border border-dashed border-stone-300 px-5 py-8 text-sm leading-7 text-stone-500 lg:col-span-2">
                <div>{t("noProjectsDiscovered")}</div>
                {systemStatus?.workspaces_dir ? (
                  <div className="mt-3">{t("workspaceSource", { path: systemStatus.workspaces_dir })}</div>
                ) : null}
                <div className="mt-2">{t("workspaceRecognitionHint")}</div>
              </div>
            ) : null}
          </div>
        </div>

        <div className="space-y-4">
          <div className="panel-surface rounded-[30px] p-5 md:p-6">
            <div className="mb-4">
              <div className="eyebrow">{t("gpuLeases")}</div>
              <div className="mt-2 text-xl font-medium text-stone-950">{t("currentAcceleratorOccupancy")}</div>
            </div>
            <div className="space-y-3">
              {Object.entries(gpuLeases).map(([gpu, lease]) => (
                <div key={gpu} className="panel-soft rounded-[24px] px-4 py-4 text-sm text-stone-700">
                  <div className="font-medium text-stone-900">GPU {gpu}</div>
                  <div className="mt-1">{lease.project_name || t("idle")}</div>
                  <div className="mt-1 text-stone-500">{(lease.task_ids || []).join(", ") || t("noTaskIds")}</div>
                </div>
              ))}
              {Object.keys(gpuLeases).length === 0 ? (
                <div className="rounded-[24px] border border-dashed border-stone-300 px-4 py-8 text-sm text-stone-500">
                  {t("noActiveGpuLeases")}
                </div>
              ) : null}
            </div>
          </div>
          <AgentActivity agents={agents} />
        </div>
      </section>

      <CostChart cost={cost} />
    </div>
  );
}
