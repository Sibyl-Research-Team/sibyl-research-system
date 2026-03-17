"use client";

import { useI18n } from "@/i18n/provider";

export function PipelineProgress({
  stages,
  currentStage,
}: {
  stages: string[];
  currentStage: string;
}) {
  const { t, stageLabel } = useI18n();
  const currentIndex = stages.indexOf(currentStage);

  return (
    <div className="panel-surface rounded-[28px] p-5">
      <div className="mb-4">
        <div className="eyebrow">{t("pipeline")}</div>
      </div>
      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
        {stages.map((stage, index) => {
          const state =
            index < currentIndex ? "done" : index === currentIndex ? "current" : "future";
          return (
            <div
              key={stage}
              className={`rounded-2xl border px-4 py-3 text-sm ${
                state === "done"
                  ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                  : state === "current"
                    ? "border-orange-300 bg-orange-50 text-orange-900"
                    : "border-stone-200 bg-stone-50 text-stone-500"
              }`}
            >
              {stageLabel(stage)}
            </div>
          );
        })}
      </div>
    </div>
  );
}
