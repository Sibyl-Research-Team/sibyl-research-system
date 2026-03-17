export type Locale = "en" | "zh";

type MessageKey =
  | "brand"
  | "console"
  | "brandDescription"
  | "projects"
  | "status"
  | "overview"
  | "syncing"
  | "ready"
  | "noProjectsDiscovered"
  | "language"
  | "systemOverview"
  | "heroTitle"
  | "heroDescription"
  | "trackedWorkspaces"
  | "gpuLanes"
  | "usageSamples"
  | "activeAgents"
  | "runtimeReady"
  | "totalTokens"
  | "openWorkspace"
  | "refreshing"
  | "gpuLeases"
  | "currentAcceleratorOccupancy"
  | "noActiveGpuLeases"
  | "workspaceSource"
  | "workspaceRecognitionHint"
  | "iterationLabel"
  | "runtimeReadyChip"
  | "setupNeeded"
  | "noTopicRecorded"
  | "idle"
  | "noTaskIds"
  | "dashboardMetadataPlaceholder"
  | "loadingStage"
  | "project"
  | "conversationLive"
  | "conversationRetrying"
  | "indexedEntries"
  | "indexPending"
  | "chat"
  | "monitor"
  | "files"
  | "config"
  | "terminal"
  | "conversation"
  | "live"
  | "reconnecting"
  | "waitingConversation"
  | "talkToRunningSession"
  | "send"
  | "stop"
  | "resume"
  | "messagePlaceholder"
  | "messageSent"
  | "stopRequested"
  | "resumeRequested"
  | "sendFailed"
  | "stopFailed"
  | "resumeFailed"
  | "user"
  | "assistant"
  | "system"
  | "toolResult"
  | "inputTokens"
  | "outputTokens"
  | "pipeline"
  | "gpuWorkload"
  | "noRunningGpuTasks"
  | "gpusLabel"
  | "unknown"
  | "running"
  | "workspace"
  | "root"
  | "currentDirectory"
  | "upLevel"
  | "folderSummary"
  | "emptyDirectory"
  | "preview"
  | "previewUnavailable"
  | "loadingPreview"
  | "selectFilePreview"
  | "loadFilesFailed"
  | "loadFileFailed"
  | "configDescription"
  | "reload"
  | "save"
  | "configReloaded"
  | "configSaved"
  | "configLoadFailed"
  | "configReloadFailed"
  | "configSaveFailed"
  | "liveTerminal"
  | "open"
  | "terminalHelp"
  | "loadingTerminalStatus"
  | "terminalLoadFailed"
  | "activeAgentsTitle"
  | "noActiveAgents"
  | "tokenCostTrend"
  | "noUsageData"
  | "preparingWorkspace"
  | "authChecking"
  | "authTitle"
  | "authSubtitle"
  | "authPlaceholder"
  | "authSubmit"
  | "authInvalid"
  | "authNetworkError"
  | "retry";

export const messages: Record<Locale, Record<MessageKey, string>> = {
  en: {
    brand: "Sibyl",
    console: "Research Console",
    brandDescription: "Chat, monitoring, files, and terminal access for a single running research system.",
    projects: "Projects",
    status: "Status",
    overview: "Overview",
    syncing: "syncing",
    ready: "ready",
    noProjectsDiscovered: "No projects discovered yet.",
    language: "Language",
    systemOverview: "System Overview",
    heroTitle: "Sibyl WebUI",
    heroDescription: "Monitor active projects, watch Claude conversations stream in real time, inspect files, edit config, and jump straight into the live terminal.",
    trackedWorkspaces: "{count} tracked workspaces",
    gpuLanes: "{count} gpu lanes",
    usageSamples: "{count} usage samples",
    activeAgents: "Active Agents",
    runtimeReady: "Runtime Ready",
    totalTokens: "Total Tokens",
    openWorkspace: "Open a running workspace",
    refreshing: "Refreshing…",
    gpuLeases: "GPU Leases",
    currentAcceleratorOccupancy: "Current accelerator occupancy",
    noActiveGpuLeases: "No active GPU leases reported.",
    workspaceSource: "Scanning workspaces from: {path}",
    workspaceRecognitionHint: "Only directories containing status.json are recognized as projects.",
    iterationLabel: "Iteration {count}",
    runtimeReadyChip: "runtime ready",
    setupNeeded: "setup needed",
    noTopicRecorded: "No topic recorded",
    idle: "idle",
    noTaskIds: "No task ids",
    dashboardMetadataPlaceholder: "Dashboard metadata will appear here after the first refresh.",
    loadingStage: "loading stage",
    project: "Project",
    conversationLive: "conversation live",
    conversationRetrying: "conversation retrying",
    indexedEntries: "{count} indexed entries",
    indexPending: "index pending",
    chat: "Chat",
    monitor: "Monitor",
    files: "Files",
    config: "Config",
    terminal: "Terminal",
    conversation: "Conversation",
    live: "live",
    reconnecting: "reconnecting",
    waitingConversation: "Waiting for conversation history or the next streamed Claude turn.",
    talkToRunningSession: "Talk to the running Claude session",
    send: "Send",
    stop: "Stop",
    resume: "Resume",
    messagePlaceholder: "Send a prompt or command to the active Sibyl session...",
    messageSent: "Message sent",
    stopRequested: "Stop requested",
    resumeRequested: "Resume requested",
    sendFailed: "Failed to send message",
    stopFailed: "Failed to stop project",
    resumeFailed: "Failed to resume project",
    user: "user",
    assistant: "assistant",
    system: "system",
    toolResult: "Tool Result",
    inputTokens: "in",
    outputTokens: "out",
    pipeline: "Pipeline",
    gpuWorkload: "GPU Workload",
    noRunningGpuTasks: "No running GPU tasks reported.",
    gpusLabel: "GPUs",
    unknown: "unknown",
    running: "running",
    workspace: "Workspace",
    root: "Root",
    currentDirectory: "Current directory",
    upLevel: "Up one level",
    folderSummary: "{dirs} folders · {files} files",
    emptyDirectory: "This folder is empty.",
    preview: "Preview",
    previewUnavailable: "This file type is not currently previewable in the browser.",
    loadingPreview: "Loading preview...",
    selectFilePreview: "Select a file to preview its contents.",
    loadFilesFailed: "Failed to load files",
    loadFileFailed: "Failed to load file",
    configDescription: "Edit the project override file. Saving keeps your raw YAML text intact and validates it on the server.",
    reload: "Reload",
    save: "Save",
    configReloaded: "Config reloaded",
    configSaved: "Config saved",
    configLoadFailed: "Failed to load config",
    configReloadFailed: "Failed to reload config",
    configSaveFailed: "Failed to save config",
    liveTerminal: "Live Terminal",
    open: "Open",
    terminalHelp: "Start ttyd for this project to enable browser terminal access.",
    loadingTerminalStatus: "Loading terminal status...",
    terminalLoadFailed: "Failed to load terminal metadata",
    activeAgentsTitle: "Active Agents",
    noActiveAgents: "No active agents right now.",
    tokenCostTrend: "Token Cost Trend",
    noUsageData: "No usage data available yet.",
    preparingWorkspace: "Preparing workspace interface...",
    authChecking: "Checking dashboard access…",
    authTitle: "Dashboard access required",
    authSubtitle: "This WebUI is protected by SIBYL_DASHBOARD_KEY. Sign in once and the project list will load normally.",
    authPlaceholder: "Enter dashboard key",
    authSubmit: "Unlock WebUI",
    authInvalid: "Invalid key",
    authNetworkError: "Cannot reach the backend auth endpoint.",
    retry: "Retry",
  },
  zh: {
    brand: "Sibyl",
    console: "研究控制台",
    brandDescription: "在一个界面里查看聊天、监控、文件和终端，面向正在运行的研究项目。",
    projects: "项目",
    status: "状态",
    overview: "总览",
    syncing: "同步中",
    ready: "就绪",
    noProjectsDiscovered: "当前没有发现可识别的项目。",
    language: "语言",
    systemOverview: "系统概览",
    heroTitle: "Sibyl WebUI",
    heroDescription: "实时监控活跃项目，查看 Claude 对话流，浏览文件、编辑配置，并直接进入在线终端。",
    trackedWorkspaces: "已跟踪 {count} 个 workspace",
    gpuLanes: "{count} 条 GPU 通道",
    usageSamples: "{count} 条用量样本",
    activeAgents: "活跃 Agent",
    runtimeReady: "运行环境就绪",
    totalTokens: "总 Token",
    openWorkspace: "打开一个正在运行的项目",
    refreshing: "刷新中…",
    gpuLeases: "GPU 占用",
    currentAcceleratorOccupancy: "当前加速器占用情况",
    noActiveGpuLeases: "当前没有上报中的 GPU 占用。",
    workspaceSource: "当前扫描目录：{path}",
    workspaceRecognitionHint: "只有包含 status.json 的目录才会被识别为项目。",
    iterationLabel: "迭代 {count}",
    runtimeReadyChip: "运行环境就绪",
    setupNeeded: "需要初始化",
    noTopicRecorded: "暂无主题说明",
    idle: "空闲",
    noTaskIds: "没有任务 ID",
    dashboardMetadataPlaceholder: "首次刷新后，这里会显示项目的 dashboard 元数据。",
    loadingStage: "正在加载阶段",
    project: "项目",
    conversationLive: "会话实时连接",
    conversationRetrying: "会话重连中",
    indexedEntries: "已索引 {count} 个条目",
    indexPending: "索引中",
    chat: "聊天",
    monitor: "监控",
    files: "文件",
    config: "配置",
    terminal: "终端",
    conversation: "对话",
    live: "实时",
    reconnecting: "重连中",
    waitingConversation: "正在等待历史对话或下一条 Claude 流式消息。",
    talkToRunningSession: "向当前运行中的 Claude 会话发送消息",
    send: "发送",
    stop: "停止",
    resume: "恢复",
    messagePlaceholder: "向当前 Sibyl 会话发送提示词或命令…",
    messageSent: "消息已发送",
    stopRequested: "已请求停止",
    resumeRequested: "已请求恢复",
    sendFailed: "发送消息失败",
    stopFailed: "停止项目失败",
    resumeFailed: "恢复项目失败",
    user: "用户",
    assistant: "助手",
    system: "系统",
    toolResult: "工具结果",
    inputTokens: "输入",
    outputTokens: "输出",
    pipeline: "流水线",
    gpuWorkload: "GPU 负载",
    noRunningGpuTasks: "当前没有运行中的 GPU 任务。",
    gpusLabel: "GPU",
    unknown: "未知",
    running: "运行中",
    workspace: "工作区",
    root: "根目录",
    currentDirectory: "当前目录",
    upLevel: "返回上一级",
    folderSummary: "{dirs} 个文件夹 · {files} 个文件",
    emptyDirectory: "这个目录目前是空的。",
    preview: "预览",
    previewUnavailable: "这种文件类型暂时还不能在浏览器里直接预览。",
    loadingPreview: "正在加载预览…",
    selectFilePreview: "选择一个文件以查看内容。",
    loadFilesFailed: "加载文件失败",
    loadFileFailed: "加载文件失败",
    configDescription: "编辑项目级 config.yaml。保存时会保留你的原始 YAML 文本，并在服务端做校验。",
    reload: "重新加载",
    save: "保存",
    configReloaded: "配置已重新加载",
    configSaved: "配置已保存",
    configLoadFailed: "加载配置失败",
    configReloadFailed: "重新加载配置失败",
    configSaveFailed: "保存配置失败",
    liveTerminal: "在线终端",
    open: "打开",
    terminalHelp: "为该项目启动 ttyd 后，即可在浏览器中使用终端。",
    loadingTerminalStatus: "正在加载终端状态…",
    terminalLoadFailed: "加载终端元数据失败",
    activeAgentsTitle: "活跃 Agent",
    noActiveAgents: "当前没有活跃中的 Agent。",
    tokenCostTrend: "Token 用量趋势",
    noUsageData: "当前还没有可用的用量数据。",
    preparingWorkspace: "正在准备项目界面…",
    authChecking: "正在检查仪表盘访问权限…",
    authTitle: "需要仪表盘访问密钥",
    authSubtitle: "当前 WebUI 启用了 SIBYL_DASHBOARD_KEY 鉴权。登录一次后，项目列表就会正常显示。",
    authPlaceholder: "输入 dashboard key",
    authSubmit: "解锁 WebUI",
    authInvalid: "密钥无效",
    authNetworkError: "无法连接到后端鉴权接口。",
    retry: "重试",
  },
};

const stageMessages: Record<Locale, Record<string, string>> = {
  en: {
    init: "init",
    planning: "planning",
    literature_search: "literature search",
    writing_sections: "writing sections",
    pilot_experiments: "pilot experiments",
    experiment_cycle: "experiment cycle",
    done: "done",
  },
  zh: {
    init: "初始化",
    planning: "规划中",
    literature_search: "文献检索",
    writing_sections: "撰写章节",
    pilot_experiments: "试点实验",
    experiment_cycle: "实验循环",
    done: "已完成",
  },
};

export function resolveStageLabel(stage: string, locale: Locale): string {
  const trimmed = stage.trim();
  if (!trimmed) return trimmed;
  const mapped = stageMessages[locale][trimmed];
  if (mapped) return mapped;
  if (locale === "en") {
    return trimmed.replaceAll("_", " ");
  }
  return trimmed;
}
