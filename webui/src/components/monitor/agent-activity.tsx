"use client";

import { useI18n } from "@/i18n/provider";
import type { ActiveAgent } from "@/lib/types";

export function AgentActivity({ agents }: { agents: ActiveAgent[] }) {
  const { t, stageLabel } = useI18n();

  return (
    <div className="panel-surface rounded-[28px] p-5">
      <div className="mb-4">
        <div className="eyebrow">{t("activeAgentsTitle")}</div>
      </div>
      <div className="space-y-3">
        {agents.map((agent) => (
          <div key={`${agent.project}-${agent.agent}-${agent.iteration}`} className="panel-soft rounded-[24px] px-4 py-3 text-sm text-stone-700">
            <div className="font-medium text-stone-900">{agent.agent}</div>
            <div className="mt-1">
              {stageLabel(agent.stage)} · {t("iterationLabel", { count: agent.iteration })}
            </div>
          </div>
        ))}
        {agents.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-stone-300 px-4 py-8 text-sm text-stone-500">
            {t("noActiveAgents")}
          </div>
        ) : null}
      </div>
    </div>
  );
}
