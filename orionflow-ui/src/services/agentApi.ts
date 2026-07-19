import type { OFLParameter, OFLGeometryStats } from './oflApi';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function authHeaders(): Record<string, string> {
  try {
    const token = JSON.parse(localStorage.getItem('orionflow-auth') || '{}')
      ?.state?.accessToken;
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

export interface SourcedPart {
  part_id: string;
  name: string;
  matched_text: string;
  spec: Record<string, unknown>;
}

export interface PlanFeature {
  name?: string;
  type?: string;
  dims_mm?: Record<string, unknown>;
  justification?: string;
}

export interface DesignPlan {
  part_name?: string;
  material?: string;
  process?: string;
  envelope_mm?: number[] | null;
  features?: PlanFeature[];
  joints?: Record<string, unknown>[];
  risks?: string[];
  knowledge_used?: string[];
  reasoning_mode?: string;
}

export interface AnalysisIssue {
  severity: 'critical' | 'warning' | 'info';
  issue: string;
  fix?: string;
}

export interface AnalysisReport {
  process?: string;
  material?: string;
  properties?: {
    volume_cm3?: number;
    mass_g?: number;
    bbox_mm?: number[];
    watertight?: boolean;
  };
  issues?: AnalysisIssue[];
  manufacturability_score?: number;
}

export interface TraceStep {
  phase: string;
  t_ms: number;
  [key: string]: unknown;
}

export interface AgentDesignResponse {
  success: boolean;
  intent: string;
  reasoning: DesignPlan;
  sourced_parts: SourcedPart[];
  ofl_code: string;
  files: { step?: string | null; stl?: string | null; glb?: string | null; urdf?: string | null; sdf?: string | null };
  parameters: OFLParameter[];
  stats?: OFLGeometryStats | null;
  analysis?: AnalysisReport | null;
  mass_properties?: { mass_kg?: number } | null;
  urdf?: string | null;
  sdf?: string | null;
  repair_attempts: number;
  trace: TraceStep[];
  error?: string | null;
  generation_time_ms: number;
}

export async function designWithAgent(prompt: string): Promise<AgentDesignResponse> {
  const res = await fetch(`${API_BASE}/api/v1/agent/design`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ prompt }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(
      typeof err.detail === 'string' ? err.detail : 'Agent design failed'
    );
  }
  return res.json();
}
