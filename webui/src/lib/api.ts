import type {
  CostPayload,
  DashboardData,
  FileListing,
  ProjectSummary,
  SystemStatus,
  TerminalInfo,
} from "./types";

async function parseError(response: Response) {
  try {
    const payload = (await response.json()) as { error?: string };
    return payload.error || `${response.status} ${response.statusText}`;
  } catch {
    return `${response.status} ${response.statusText}`;
  }
}

async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    ...init,
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return (await response.json()) as T;
}

async function apiText(path: string): Promise<string> {
  const response = await fetch(path, { credentials: "include" });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.text();
}

export const api = {
  getFileUrl: (project: string, path: string) =>
    `/api/projects/${encodeURIComponent(project)}/file?path=${encodeURIComponent(path)}`,
  authCheck: () => apiJson<{ ok: boolean; auth_required: boolean }>("/api/auth/check"),
  authLogin: (key: string) =>
    apiJson<{ ok: boolean }>("/api/auth", {
      method: "POST",
      body: JSON.stringify({ key }),
    }),
  getProjects: () => apiJson<ProjectSummary[]>("/api/projects"),
  getSystemStatus: () => apiJson<SystemStatus>("/api/system/status"),
  getDashboard: (project: string) =>
    apiJson<DashboardData>(`/api/projects/${encodeURIComponent(project)}/dashboard?events_tail=100`),
  getConversation: (project: string, limit = 120) =>
    apiJson<{ project: string; session: { session_id?: string } | null; entries: unknown[] }>(
      `/api/projects/${encodeURIComponent(project)}/conversation?limit=${limit}`,
    ),
  sendMessage: (project: string, text: string) =>
    apiJson<{ ok: boolean; error?: string }>(`/api/projects/${encodeURIComponent(project)}/send-message`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  stopProject: (project: string) =>
    apiJson<{ ok: boolean; mode?: string }>(`/api/projects/${encodeURIComponent(project)}/stop`, {
      method: "POST",
    }),
  resumeProject: (project: string) =>
    apiJson<{ ok: boolean; mode?: string }>(`/api/projects/${encodeURIComponent(project)}/resume`, {
      method: "POST",
    }),
  getFiles: (project: string, dir = "") =>
    apiJson<FileListing>(
      `/api/projects/${encodeURIComponent(project)}/files${dir ? `?dir=${encodeURIComponent(dir)}` : ""}`,
    ),
  getFile: (project: string, path: string) =>
    apiText(`/api/projects/${encodeURIComponent(project)}/file?path=${encodeURIComponent(path)}`),
  getConfig: (project: string) =>
    apiJson<{ content: string; path: string }>(`/api/projects/${encodeURIComponent(project)}/config`),
  saveConfig: (project: string, content: string) =>
    apiJson<{ ok: boolean }>(`/api/projects/${encodeURIComponent(project)}/config`, {
      method: "PUT",
      body: JSON.stringify({ content }),
    }),
  getTerminalInfo: (project: string) =>
    apiJson<TerminalInfo>(`/api/projects/${encodeURIComponent(project)}/terminal-info`),
  getGpuOverview: () =>
    apiJson<{ leases: Record<string, { project_name?: string; task_ids?: string[] }>; updated_at?: number }>(
      "/api/monitor/gpu",
    ),
  getActiveAgents: (project?: string) =>
    apiJson<{ agents: import("./types").ActiveAgent[] }>(
      `/api/monitor/agents${project ? `?project=${encodeURIComponent(project)}` : ""}`,
    ),
  getCost: (project?: string) =>
    apiJson<CostPayload>(`/api/monitor/cost${project ? `?project=${encodeURIComponent(project)}` : ""}`),
};
