import type {
  SessionMeta, SessionDetail, SkillMeta, SkillDetail, UsageSnapshot, Machines,
} from "./types";

export async function fetchMachines(): Promise<Machines> {
  const r = await fetch("/api/machines");
  if (!r.ok) throw new Error(`machines ${r.status}`);
  return r.json();
}

export async function fetchSessions(): Promise<SessionMeta[]> {
  const r = await fetch("/api/sessions");
  if (!r.ok) throw new Error(`sessions ${r.status}`);
  return r.json();
}

export async function fetchSession(id: string, signal?: AbortSignal): Promise<SessionDetail> {
  const r = await fetch(`/api/sessions/${encodeURIComponent(id)}`, { signal });
  if (!r.ok) throw new Error(`session ${r.status}`);
  return r.json();
}

export async function fetchSkills(): Promise<SkillMeta[]> {
  const r = await fetch("/api/skills");
  if (!r.ok) throw new Error(`skills ${r.status}`);
  return r.json();
}

export async function fetchSkill(id: string, signal?: AbortSignal): Promise<SkillDetail> {
  const r = await fetch(`/api/skills/${encodeURIComponent(id)}`, { signal });
  if (!r.ok) throw new Error(`skill ${r.status}`);
  return r.json();
}

export async function fetchUsage(): Promise<UsageSnapshot> {
  const r = await fetch("/api/usage");
  if (!r.ok) throw new Error(`usage ${r.status}`);
  return r.json();
}
