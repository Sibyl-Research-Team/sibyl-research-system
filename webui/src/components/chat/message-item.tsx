"use client";

import ReactMarkdown from "react-markdown";

import { useI18n } from "@/i18n/provider";
import type { ChatMessage, ContentBlock } from "@/lib/types";

import { ToolBlock } from "./tool-block";

function isStructuredBlock(
  block: ContentBlock,
): block is Extract<ContentBlock, { type: "tool_use" | "tool_result" | "json" }> {
  return block.type === "tool_use" || block.type === "tool_result" || block.type === "json";
}

export function MessageItem({ message }: { message: ChatMessage }) {
  const { t } = useI18n();
  const isAssistant = message.role === "assistant";
  const roleLabel =
    message.role === "assistant"
      ? t("assistant")
      : message.role === "system"
        ? t("system")
        : t("user");

  return (
    <article
      className={`rounded-[24px] border px-5 py-4 shadow-sm ${
        isAssistant
          ? "border-stone-200/80 bg-[linear-gradient(180deg,rgba(255,255,255,0.9),rgba(251,246,238,0.92))]"
          : "border-orange-200 bg-[linear-gradient(180deg,rgba(255,239,229,0.96),rgba(255,247,241,0.98))]"
      }`}
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-xs uppercase tracking-[0.22em] text-stone-500">
        <span className={`rounded-full px-2.5 py-1 ${isAssistant ? "bg-white/75" : "bg-orange-100/90 text-orange-900"}`}>
          {roleLabel}
        </span>
        <span>{message.model || message.timestamp || message.id.slice(0, 8)}</span>
      </div>

      <div className="space-y-3">
        {message.blocks.map((block, index) => {
          if (block.type === "text" || block.type === "thinking") {
            return (
              <div
                key={`${message.id}-${index}`}
                className={block.type === "thinking" ? "rounded-2xl border border-dashed border-stone-300 bg-stone-50 px-4 py-3 text-sm text-stone-600" : ""}
              >
                <ReactMarkdown>{block.text}</ReactMarkdown>
              </div>
            );
          }
          if (isStructuredBlock(block)) {
            return <ToolBlock key={`${message.id}-${index}`} block={block} />;
          }
          return null;
        })}
      </div>

      {message.usage ? (
        <div className="mt-4 text-xs text-stone-500">
          {message.usage.input_tokens} {t("inputTokens")} / {message.usage.output_tokens} {t("outputTokens")}
        </div>
      ) : null}
    </article>
  );
}
