"use client";

import { create } from "zustand";

import type { ChatMessage, DashboardData, FileListing, TerminalInfo } from "@/lib/types";

interface ProjectSlice {
  dashboard: DashboardData | null;
  messages: ChatMessage[];
  files: FileListing | null;
  configContent: string;
  terminalInfo: TerminalInfo | null;
}

interface ProjectStore {
  byProject: Record<string, ProjectSlice>;
  ensureProject: (project: string) => void;
  setDashboard: (project: string, dashboard: DashboardData) => void;
  setMessages: (project: string, messages: ChatMessage[]) => void;
  appendMessages: (project: string, messages: ChatMessage[]) => void;
  setFiles: (project: string, files: FileListing) => void;
  setConfigContent: (project: string, content: string) => void;
  setTerminalInfo: (project: string, terminalInfo: TerminalInfo) => void;
}

const emptySlice = (): ProjectSlice => ({
  dashboard: null,
  messages: [],
  files: null,
  configContent: "",
  terminalInfo: null,
});

export const useProjectStore = create<ProjectStore>((set, get) => ({
  byProject: {},
  ensureProject: (project) => {
    if (get().byProject[project]) return;
    set((state) => ({ byProject: { ...state.byProject, [project]: emptySlice() } }));
  },
  setDashboard: (project, dashboard) =>
    set((state) => ({
      byProject: {
        ...state.byProject,
        [project]: { ...(state.byProject[project] || emptySlice()), dashboard },
      },
    })),
  setMessages: (project, messages) =>
    set((state) => ({
      byProject: {
        ...state.byProject,
        [project]: { ...(state.byProject[project] || emptySlice()), messages },
      },
    })),
  appendMessages: (project, messages) =>
    set((state) => {
      const current = state.byProject[project] || emptySlice();
      const merged = [...current.messages];
      for (const message of messages) {
        if (!merged.some((existing) => existing.id === message.id)) {
          merged.push(message);
        }
      }
      return {
        byProject: {
          ...state.byProject,
          [project]: { ...current, messages: merged },
        },
      };
    }),
  setFiles: (project, files) =>
    set((state) => ({
      byProject: {
        ...state.byProject,
        [project]: { ...(state.byProject[project] || emptySlice()), files },
      },
    })),
  setConfigContent: (project, configContent) =>
    set((state) => ({
      byProject: {
        ...state.byProject,
        [project]: { ...(state.byProject[project] || emptySlice()), configContent },
      },
    })),
  setTerminalInfo: (project, terminalInfo) =>
    set((state) => ({
      byProject: {
        ...state.byProject,
        [project]: { ...(state.byProject[project] || emptySlice()), terminalInfo },
      },
    })),
}));
