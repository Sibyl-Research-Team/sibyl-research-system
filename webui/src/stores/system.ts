"use client";

import { create } from "zustand";

import { api } from "@/lib/api";
import type { ProjectSummary, SystemStatus } from "@/lib/types";

interface SystemStore {
  projects: ProjectSummary[];
  systemStatus: SystemStatus | null;
  loading: boolean;
  error: string | null;
  loadOverview: () => Promise<void>;
}

export const useSystemStore = create<SystemStore>((set) => ({
  projects: [],
  systemStatus: null,
  loading: false,
  error: null,
  loadOverview: async () => {
    set({ loading: true, error: null });
    try {
      const [projects, systemStatus] = await Promise.all([
        api.getProjects(),
        api.getSystemStatus(),
      ]);
      set({ projects, systemStatus, loading: false });
    } catch (error) {
      set({
        loading: false,
        error: error instanceof Error ? error.message : "Failed to load system overview",
      });
    }
  },
}));
