"use client";

import { Loader2, Play, RotateCcw, Square } from "lucide-react";
import { useState, useTransition } from "react";

import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";

export function MessageInput({ project }: { project: string }) {
  const { t } = useI18n();
  const [text, setText] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  function send() {
    if (!text.trim()) return;
    startTransition(async () => {
      try {
        await api.sendMessage(project, text);
        setStatus(t("messageSent"));
        setText("");
      } catch (error) {
        setStatus(error instanceof Error ? error.message : t("sendFailed"));
      }
    });
  }

  function stop() {
    startTransition(async () => {
      try {
        await api.stopProject(project);
        setStatus(t("stopRequested"));
      } catch (error) {
        setStatus(error instanceof Error ? error.message : t("stopFailed"));
      }
    });
  }

  function resume() {
    startTransition(async () => {
      try {
        await api.resumeProject(project);
        setStatus(t("resumeRequested"));
      } catch (error) {
        setStatus(error instanceof Error ? error.message : t("resumeFailed"));
      }
    });
  }

  return (
    <div className="panel-surface rounded-[30px] p-5">
      <label className="eyebrow mb-2 block">
        {t("talkToRunningSession")}
      </label>
      <div className="flex flex-col gap-3 md:flex-row">
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder={t("messagePlaceholder")}
          className="min-h-28 flex-1 rounded-[24px] border border-stone-200 bg-[linear-gradient(180deg,rgba(255,255,255,0.7),rgba(246,236,224,0.62))] px-4 py-3 text-sm text-stone-900 outline-none transition focus:border-orange-300"
        />
        <div className="flex w-full gap-3 md:w-56 md:flex-col">
          <button
            type="button"
            onClick={send}
            disabled={isPending || !text.trim()}
            className="flex flex-1 items-center justify-center gap-2 rounded-[22px] bg-[linear-gradient(180deg,#cf6634,#a94821)] px-4 py-3 text-sm font-medium text-white transition hover:brightness-105 disabled:cursor-not-allowed disabled:bg-orange-300"
          >
            {isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {t("send")}
          </button>
          <button
            type="button"
            onClick={stop}
            disabled={isPending}
            className="flex flex-1 items-center justify-center gap-2 rounded-[22px] border border-stone-300 bg-white/75 px-4 py-3 text-sm font-medium text-stone-800 transition hover:bg-white disabled:cursor-not-allowed"
          >
            <Square className="h-4 w-4" />
            {t("stop")}
          </button>
          <button
            type="button"
            onClick={resume}
            disabled={isPending}
            className="flex flex-1 items-center justify-center gap-2 rounded-[22px] border border-stone-300 bg-white/75 px-4 py-3 text-sm font-medium text-stone-800 transition hover:bg-white disabled:cursor-not-allowed"
          >
            <RotateCcw className="h-4 w-4" />
            {t("resume")}
          </button>
        </div>
      </div>
      {status ? <div className="mt-3 text-sm text-stone-600">{status}</div> : null}
    </div>
  );
}
