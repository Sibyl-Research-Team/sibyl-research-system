"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { parseConversationEntry } from "@/lib/parse-message";
import { useProjectStore } from "@/stores/project";

const WS_URL =
  process.env.NEXT_PUBLIC_WS_URL ||
  (typeof window !== "undefined"
    ? `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`
    : "");

export function useConversationStream(project: string) {
  const [connected, setConnected] = useState(false);
  const setMessages = useProjectStore((state) => state.setMessages);
  const appendMessages = useProjectStore((state) => state.appendMessages);
  const ensureProject = useProjectStore((state) => state.ensureProject);

  useEffect(() => {
    ensureProject(project);
    let isActive = true;
    let socket: WebSocket | null = null;
    let retryDelay = 500;
    let retryTimer: number | null = null;

    async function loadHistory() {
      try {
        const payload = await api.getConversation(project, 120);
        if (!isActive) return;
        const messages = payload.entries
          .map(parseConversationEntry)
          .filter((message): message is NonNullable<typeof message> => Boolean(message));
        setMessages(project, messages);
      } catch {
        if (!isActive) return;
      }
    }

    function connect() {
      if (!isActive || !WS_URL) return;
      socket = new WebSocket(`${WS_URL}/ws/conversation/${encodeURIComponent(project)}`);
      socket.onopen = () => {
        retryDelay = 500;
        setConnected(true);
      };
      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as { entries?: unknown[] };
          const messages = (payload.entries || [])
            .map(parseConversationEntry)
            .filter((message): message is NonNullable<typeof message> => Boolean(message));
          appendMessages(project, messages);
        } catch {
          // Ignore malformed pushes and rely on the next refresh.
        }
      };
      socket.onclose = () => {
        setConnected(false);
        if (!isActive) return;
        retryTimer = window.setTimeout(() => {
          retryDelay = Math.min(retryDelay * 2, 30_000);
          connect();
        }, retryDelay);
      };
      socket.onerror = () => {
        socket?.close();
      };
    }

    loadHistory();
    connect();

    return () => {
      isActive = false;
      setConnected(false);
      if (retryTimer !== null) {
        window.clearTimeout(retryTimer);
      }
      socket?.close();
    };
  }, [appendMessages, ensureProject, project, setMessages]);

  return { connected };
}
