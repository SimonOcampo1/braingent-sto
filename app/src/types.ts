export type SessionMeta = {
  id: string;
  project: string;
  mtime: number;
  title: string;
  n_prompts: number;
  n_tools: number;
  errors: number;
  machine: string | null; // null = this machine; hostname when synced from another
};

export type TimelineItem =
  | { role: "user"; text: string }
  | { role: "assistant"; text: string }
  | { role: "tool"; tool: string; detail: string; input?: Record<string, string> }
  | { role: "error"; text: string }
  | { role: "image"; media_type: string; data: string };

export type SessionDetail = {
  id: string;
  project: string;
  timeline: TimelineItem[];
};

export type MachineInfo = { type: "laptop" | "desktop" | "unknown"; local: boolean };
export type Machines = Record<string, MachineInfo>;

export type SkillMeta = {
  id: string;
  name: string;
  source: string;
  description: string;
};

export type SkillDetail = SkillMeta & { content: string; body: string; path: string };

export type UsageBlock = {
  isActive: boolean;
  startTime: string;
  endTime: string;
  costUSD: number;
  models: string[];
  tokenCounts: {
    inputTokens: number;
    outputTokens: number;
    cacheCreationInputTokens: number;
    cacheReadInputTokens: number;
  };
  burnRate: { costPerHour: number; tokensPerMinute: number } | null;
  projection: { remainingMinutes: number; totalCost: number; totalTokens: number } | null;
};

export type ModelBreakdown = {
  modelName: string;
  cost: number;
  inputTokens: number;
  outputTokens: number;
  cacheCreationTokens: number;
  cacheReadTokens: number;
};

export type UsageDay = {
  period: string;
  inputTokens: number;
  outputTokens: number;
  cacheCreationTokens: number;
  cacheReadTokens: number;
  totalCost: number;
  modelsUsed: string[];
  modelBreakdowns: ModelBreakdown[];
};

export type UsageLimit = {
  kind: string; // "session" | "weekly_all" | "weekly_scoped"
  label: string | null; // model display name for scoped limits (e.g. "Fable")
  percent: number;
  resetsAt: string;
};

export type UsageSnapshot = {
  block: UsageBlock | null;
  daily: UsageDay[];
  limits: UsageLimit[] | null; // real plan quota; null when offline/no token
  error: string | null;
};
