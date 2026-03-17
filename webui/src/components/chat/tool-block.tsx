"use client";

import { FileText, Search, Terminal, Wrench } from "lucide-react";

import { useI18n } from "@/i18n/provider";
import type { ContentBlock } from "@/lib/types";

const iconByToolName: Record<string, typeof Terminal> = {
  bash: Terminal,
  read: FileText,
  grep: Search,
  glob: Search,
};

export function ToolBlock({ block }: { block: Extract<ContentBlock, { type: "tool_use" | "tool_result" | "json" }> }) {
  const { t } = useI18n();

  if (block.type === "tool_result") {
    return (
      <div className="rounded-2xl border border-stone-200 bg-stone-950 px-4 py-3 text-sm text-stone-100">
        <div className="mb-2 text-xs uppercase tracking-[0.24em] text-stone-400">{t("toolResult")}</div>
        <pre className="overflow-x-auto whitespace-pre-wrap break-words">{block.content}</pre>
      </div>
    );
  }

  const Icon =
    block.type === "tool_use"
      ? iconByToolName[block.name.toLowerCase()] || Wrench
      : Wrench;
  const label = block.type === "tool_use" ? block.name : block.label;
  const value = block.type === "tool_use" ? block.input : block.value;

  return (
    <div className="rounded-2xl border border-stone-200 bg-stone-100/80 px-4 py-3 text-sm text-stone-800">
      <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-[0.24em] text-stone-500">
        <Icon className="h-4 w-4" />
        <span>{label}</span>
      </div>
      <pre className="overflow-x-auto whitespace-pre-wrap break-words">{JSON.stringify(value, null, 2)}</pre>
    </div>
  );
}
