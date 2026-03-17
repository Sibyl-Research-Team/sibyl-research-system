"use client";

import { useEffect } from "react";

const WS_URL =
  process.env.NEXT_PUBLIC_WS_URL ||
  (typeof window !== "undefined"
    ? `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`
    : "");

export function useProjectState(project: string, onInvalidate: () => void) {
  useEffect(() => {
    if (!WS_URL) return;
    let isActive = true;
    let retryDelay = 500;
    let retryTimer: number | null = null;
    let socket: WebSocket | null = null;

    function connect() {
      if (!isActive) return;
      socket = new WebSocket(`${WS_URL}/ws/state/${encodeURIComponent(project)}`);
      socket.onmessage = () => {
        onInvalidate();
      };
      socket.onclose = () => {
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

    connect();

    return () => {
      isActive = false;
      if (retryTimer !== null) {
        window.clearTimeout(retryTimer);
      }
      socket?.close();
    };
  }, [onInvalidate, project]);
}
