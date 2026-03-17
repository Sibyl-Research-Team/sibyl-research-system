export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export interface ProjectSummary {
  name: string;
  stage: string;
  iteration: number;
  paused: boolean;
  stop_requested: boolean;
  errors: number;
  topic?: string;
  runtime_ready?: boolean;
  migration_needed?: boolean;
}

export interface SystemStatus {
  system_root?: string;
  workspaces_dir?: string;
  project_count: number;
  runtime_ready_count: number;
  tool_count?: number;
  agent_count?: number;
  evolution_outcome_count?: number;
  ts?: number;
}

export interface DashboardData {
  status: {
    name: string;
    stage: string;
    iteration: number;
    paused: boolean;
    stop_requested: boolean;
    topic?: string;
    runtime?: {
      runtime_ready?: boolean;
    };
  };
  stages: string[];
  stage_durations: Array<{
    stage: string;
    iteration: number;
    duration_sec: number | null;
  }>;
  agent_summary: Array<{
    agent: string;
    stage: string;
    iteration: number;
    status: string;
    duration_sec: number | null;
    model_tier?: string;
  }>;
  recent_events: Array<Record<string, JsonValue>>;
  experiment_progress?: {
    gpu_progress?: {
      completed?: string[];
      running?: string[];
      running_map?: Record<string, { gpu_ids?: number[]; started_at?: string }>;
    };
    experiment_state?: {
      tasks?: Record<string, { status?: string; gpu_ids?: number[] }>;
    };
  };
  quality_trend: Array<{ iteration: number; score: number; timestamp: number }>;
  errors: Array<Record<string, JsonValue>>;
}

export type ContentBlock =
  | { type: "text"; text: string }
  | { type: "tool_use"; id: string; name: string; input: Record<string, JsonValue> }
  | { type: "tool_result"; tool_use_id: string; content: string; is_error?: boolean }
  | { type: "thinking"; text: string }
  | { type: "json"; label: string; value: JsonValue };

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  blocks: ContentBlock[];
  model?: string;
  usage?: { input_tokens: number; output_tokens: number };
  timestamp?: string;
}

export interface FileEntry {
  name: string;
  path: string;
  type: "dir" | "file";
  size?: number;
  ext?: string;
}

export interface FileListing {
  dirs: FileEntry[];
  files: FileEntry[];
}

export interface TerminalInfo {
  project: string;
  running: boolean;
  port?: number | null;
  pid?: number | null;
  url?: string | null;
  tmux_target?: string;
  started_at?: number | null;
}

export interface ActiveAgent {
  project: string;
  agent: string;
  stage: string;
  iteration: number;
  model_tier?: string;
  started_at?: number;
  duration_sec?: number;
}

export interface CostPoint {
  project: string;
  session_id: string;
  timestamp?: string;
  model?: string;
  input_tokens: number;
  output_tokens: number;
  cost_estimate_usd: number;
}

export interface CostPayload {
  totals: {
    input_tokens: number;
    output_tokens: number;
    cost_estimate_usd: number;
  };
  timeline: CostPoint[];
}
