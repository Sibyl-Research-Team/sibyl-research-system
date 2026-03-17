"use client";

import { useEffect, useRef } from "react";

import { useI18n } from "@/i18n/provider";
import type { ChatMessage } from "@/lib/types";

import { MessageItem } from "./message-item";

export function MessageList({
  messages,
  connected = true,
}: {
  messages: ChatMessage[];
  connected?: boolean;
}) {
  const { t } = useI18n();
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  return (
    <div className="panel-surface overflow-hidden rounded-[30px]">
      <div className="flex items-center justify-between border-b border-stone-200 px-4 py-3 text-xs uppercase tracking-[0.22em] text-stone-500">
        <span>{t("conversation")}</span>
        <span className={connected ? "text-emerald-700" : "text-amber-700"}>
          {connected ? t("live") : t("reconnecting")}
        </span>
      </div>
      <div className="h-[58vh] overflow-y-auto bg-[linear-gradient(180deg,rgba(255,255,255,0.32),rgba(247,239,228,0.44))] p-4">
        <div className="space-y-4">
          {messages.map((message) => (
            <MessageItem key={message.id} message={message} />
          ))}
          {messages.length === 0 ? (
            <div className="rounded-[24px] border border-dashed border-stone-300 px-6 py-10 text-center text-sm text-stone-500">
              {t("waitingConversation")}
            </div>
          ) : null}
          <div ref={bottomRef} />
        </div>
      </div>
    </div>
  );
}
