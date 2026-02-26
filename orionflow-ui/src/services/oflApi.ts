const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export interface OFLParameter {
  name: string;
  value: number;
  line_number: number;
}

export interface OFLFileLinks {
  step: string | null;
  stl: string | null;
  glb: string | null;
}

export interface OFLResponse {
  success: boolean;
  ofl_code: string;
  files: OFLFileLinks;
  parameters: OFLParameter[];
  error: string | null;
  generation_time_ms: number;
}

export async function generateOFL(prompt: string): Promise<OFLResponse> {
  const res = await fetch(`${API_BASE}/api/v1/ofl/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Generation failed');
  }
  return res.json();
}

export async function rebuildOFL(oflCode: string): Promise<OFLResponse> {
  const res = await fetch(`${API_BASE}/api/v1/ofl/rebuild`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ofl_code: oflCode }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Rebuild failed');
  }
  return res.json();
}

export async function editOFL(oflCode: string, instruction: string): Promise<OFLResponse> {
  const res = await fetch(`${API_BASE}/api/v1/ofl/edit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ofl_code: oflCode, edit_instruction: instruction }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Edit failed');
  }
  return res.json();
}

export function getFullUrl(path: string | null): string | null {
  if (!path) return null;
  return `${API_BASE}${path}`;
}
