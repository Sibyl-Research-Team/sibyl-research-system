"use client";

import { useI18n } from "@/i18n/provider";
import type { DashboardData } from "@/lib/types";

export function ExperimentGrid({ dashboard }: { dashboard: DashboardData | null }) {
  const { t } = useI18n();
  const runningMap = dashboard?.experiment_progress?.gpu_progress?.running_map || {};
  const runningEntries = Object.entries(runningMap);

  return (
    <div className="rounded-[28px] border border-white/60 bg-white/85 p-5 shadow-[0_20px_40px_rgba(81,58,32,0.08)]">
      <div className="mb-4 text-xs uppercase tracking-[0.22em] text-stone-500">{t("gpuWorkload")}</div>
      <div className="grid gap-3 lg:grid-cols-2">
        {runningEntries.map(([taskId, info]) => (
          <div key={taskId} className="rounded-2xl border border-stone-200 bg-stone-50 px-4 py-4">
            <div className="font-medium text-stone-900">{taskId}</div>
            <div className="mt-1 text-sm text-stone-600">
              {t("gpusLabel")}: {(info.gpu_ids || []).join(", ") || t("unknown")}
            </div>
            <div className="mt-1 text-sm text-stone-500">{info.started_at || t("running")}</div>
          </div>
        ))}
        {runningEntries.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-stone-300 px-4 py-8 text-sm text-stone-500">
            {t("noRunningGpuTasks")}
          </div>
        ) : null}
      </div>
    </div>
  );
}
