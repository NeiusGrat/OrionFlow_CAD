/**
 * Artifact link helpers and the shapes the agent endpoint still returns.
 *
 * The three generation calls that lived here — generate / rebuild / edit —
 * were removed with the routes behind them; the studio designs through
 * `studioApi`. What is left is `getFullUrl`, which every panel uses to turn a
 * server-relative artifact path into something the browser can fetch, and the
 * response types `agentApi` shares.
 */
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

export interface OFLGeometryStats {
  watertight: boolean;
  volume_mm3: number;
  bbox_mm: number[];
  triangles: number;
}

export interface OFLResponse {
  success: boolean;
  ofl_code: string;
  files: OFLFileLinks;
  parameters: OFLParameter[];
  error: string | null;
  generation_time_ms: number;
  repair_attempts?: number;
  stats?: OFLGeometryStats | null;
}

export function getFullUrl(path: string | null): string | null {
  if (!path) return null;
  if (path.startsWith('http')) return path; // already absolute (object storage)
  return `${API_BASE}${path}`;
}
