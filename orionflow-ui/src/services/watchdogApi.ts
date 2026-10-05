/**
 * The watchdog's three engines, all behind the studio's own sign-in.
 *
 *   /verify/api/...           assembly analysis (interface_check service)
 *   /drawing/api/...          incoming drawing check (drawcheck)
 *   /api/v1/watchdog/...      engine status, samples, robot-model runs
 *
 * Every call goes through `authedFetch`, so an expired access token is
 * refreshed once instead of surfacing as a 401.
 */
import { authedFetch, readError, requestJson } from './http';

/** Where the assembly engine lives: the hosted interface-check service when
 *  VITE_VERIFY_URL is set (production), else mounted in the main API at /verify. */
export const VERIFY = (import.meta.env.VITE_VERIFY_URL as string | undefined)?.replace(/\/$/, '') || '/verify';

// ------------------------------------------------------------------ types

export type Severity = 'high' | 'medium' | 'low' | 'info';
export type StageStatus = 'PASS' | 'FAIL' | 'WARNING' | 'SKIPPED' | 'ERROR' | 'RUNNING' | 'DONE';

export interface Stage {
    stage_id: string;
    stage: string;
    status: StageStatus;
    duration_s?: number;
    reason?: string;
    measurements?: Record<string, unknown>;
}

export interface AssemblyFinding {
    fingerprint: string;
    rule_id: string;
    severity: Severity;
    message: string;
    parts: string[];
    instances: string[];
    measured: Record<string, unknown>;
    expected: Record<string, unknown>;
    location: number[] | null;
    method: string;
    source: string;
    change_status: 'new' | 'fixed' | 'unchanged' | null;
    review: string | null;
    review_note: string | null;
}

export interface AnalysisJob {
    id: string;
    label: string;
    state: 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED' | 'TIMED_OUT' | string;
    stage: string | null;
    failure_code: string | null;
    error: string | null;
    summary: Partial<Record<Severity, number>> | null;
    created_at: string;
    finished_at: string | null;
    terminal: boolean;
    documents?: { kind: string; filename: string; size_bytes: number }[];
    stages?: Stage[];
    narrative?: { status: string; summary: string; points: { text: string; cites: string[] }[] };
    stats?: Record<string, unknown>;
    downloads?: string[];
    findings?: AssemblyFinding[];
}

export interface PartChange {
    part: string;
    status: string;
    old_name: string;
    details: string[];
    interface_changed: boolean;
    neighbours: string[];
    instances: string[];
}

export interface AssemblyReport {
    changes: PartChange[];
    parts: { part: string; count: number; volume_mm3: number; holes: number; component: string | null; geometry_type: string }[];
    interfaces: { a: string; b: string; planes: number; exact: boolean; distance_mm: number | null }[];
    bom: { rows: Record<string, unknown>[]; matches: { row: number; part: string; how: string }[] } | Record<string, never>;
    assumptions: string[];
}

export interface Modules {
    assembly: { available: boolean; reason: string | null; what: string };
    drawing: { available: boolean; reason: string | null; what: string };
    robot: { available: boolean; reason: string | null; what: string };
    llm: { configured: boolean; name: string | null };
}

export interface Sample {
    id: string;
    label: string;
    about: string;
}

export interface DrawingFinding {
    id: string;
    rule: string;
    severity: 'error' | 'warning' | 'info';
    title: string;
    message: string;
    query: string;
    page: number | null;
    bbox: [number, number, number, number] | null;
    evidence: string;
    confidence: string;
    decision: '' | 'accepted' | 'rejected';
}

export interface DrawingRun {
    id: string;
    filename: string;
    customer: string;
    status: 'queued' | 'running' | 'done' | 'error';
    error?: string;
    created: number;
    errors?: number;
    warnings?: number;
    infos?: number;
    drawing_number?: string;
    pages?: { w: number; h: number; layer: string }[];
    report?: { findings: DrawingFinding[]; title: Record<string, string>; reader_warnings: string[] };
}

export interface RobotFinding {
    code: string;
    severity: 'error' | 'warning' | 'info';
    message: string;
    where: string;
}

export interface RobotCheck {
    source: string;
    format: 'urdf' | 'mjcf';
    loaded: boolean;
    ok: boolean;
    errors: number;
    warnings: number;
    stats: Record<string, unknown>;
    findings: RobotFinding[];
}

export interface RobotRun {
    id: string;
    mode: 'check' | 'compile';
    label: string;
    status: 'queued' | 'running' | 'done' | 'error';
    error?: string | null;
    accepted?: boolean | null;
    has_glb?: boolean;
    created: number;
    summary?: { errors: number; warnings: number; gates_failed: string[] };
    report?: {
        robot?: string;
        accepted?: boolean;
        total_mass_kg?: number;
        gates?: Record<string, { passed: boolean } & Record<string, unknown>>;
        robocheck?: Record<string, RobotCheck>;
        view?: { glb: boolean; error?: string; missing_meshes?: string[] };
        links?: Record<string, { mass_kg: number }>;
    };
}

// ------------------------------------------------------------------ engines

export const getModules = () => requestJson<Modules>('/api/v1/watchdog/modules', 'Loading engines');
export const listSamples = () => requestJson<Sample[]>('/api/v1/watchdog/samples', 'Loading samples');
export const runSample = (id: string) =>
    requestJson<AnalysisJob>(`/api/v1/watchdog/samples/${id}`, 'Starting the sample', { method: 'POST' });

// ------------------------------------------------------------------ assembly

export const ASSEMBLY_KINDS = {
    step: { label: 'Assembly STEP', accept: '.step,.stp', many: false, required: true },
    bom: { label: 'BOM', accept: '.csv,.tsv,.txt', many: false },
    prev_step: { label: 'Previous revision STEP', accept: '.step,.stp', many: false },
    prev_bom: { label: 'Previous BOM', accept: '.csv,.tsv,.txt', many: false },
    urdf: { label: 'Robot model URDF', accept: '.urdf,.xml', many: false },
    urdf_map: { label: 'URDF link map', accept: '.yaml,.yml', many: false },
    drawing: { label: 'Drawings', accept: '.pdf', many: true },
    datasheet: { label: 'Datasheets', accept: '.pdf', many: true },
    vendor_step: { label: 'Vendor STEP', accept: '.step,.stp', many: true },
} as const;
export type AssemblyKind = keyof typeof ASSEMBLY_KINDS;

export async function createAnalysis(files: Partial<Record<AssemblyKind, File[]>>, label: string): Promise<AnalysisJob> {
    const form = new FormData();
    for (const [kind, list] of Object.entries(files)) {
        for (const f of list ?? []) form.append(kind, f, f.name);
    }
    if (label) form.append('label', label);
    const res = await authedFetch(`${VERIFY}/api/analysis/direct`, { method: 'POST', body: form });
    if (!res.ok) throw new Error(await readError(res, 'Starting the analysis'));
    return res.json();
}

export const listAnalyses = () => requestJson<AnalysisJob[]>(`${VERIFY}/api/analysis`, 'Loading analyses');
export const getAnalysis = (id: string) => requestJson<AnalysisJob>(`${VERIFY}/api/analysis/${id}`, 'Loading the analysis');
export const cancelAnalysis = (id: string) =>
    requestJson<AnalysisJob>(`${VERIFY}/api/analysis/${id}/cancel`, 'Cancelling', { method: 'POST' });
export const deleteAnalysis = (id: string) =>
    requestJson<unknown>(`${VERIFY}/api/analysis/${id}`, 'Deleting the analysis', { method: 'DELETE' });
export const reviewFinding = (id: string, fp: string, verdict: 'real' | 'not_issue' | 'open', note = '') =>
    requestJson<unknown>(`${VERIFY}/api/analysis/${id}/findings/${fp}/review`, 'Saving the review', {
        method: 'POST',
        body: JSON.stringify({ verdict, note }),
    });

// ------------------------------------------------------------------ drawings

export async function createDrawingRun(file: File, customer: string, vision: 'off' | 'scanned' | 'all'): Promise<DrawingRun> {
    const form = new FormData();
    form.append('file', file, file.name);
    form.append('customer', customer);
    form.append('vision', vision);
    const res = await authedFetch('/drawing/api/runs', { method: 'POST', body: form });
    if (!res.ok) throw new Error(await readError(res, 'Uploading the drawing'));
    return res.json();
}

export const listDrawingRuns = () => requestJson<DrawingRun[]>('/drawing/api/runs', 'Loading drawings');
export const getDrawingRun = (id: string) => requestJson<DrawingRun>(`/drawing/api/runs/${id}`, 'Loading the drawing');
export const deleteDrawingRun = (id: string) =>
    requestJson<unknown>(`/drawing/api/runs/${id}`, 'Deleting the drawing', { method: 'DELETE' });
export const decideDrawingFinding = (id: string, fid: string, decision: '' | 'accepted' | 'rejected') =>
    requestJson<unknown>(`/drawing/api/runs/${id}/findings/${fid}`, 'Saving the decision', {
        method: 'POST',
        body: JSON.stringify({ decision }),
    });

// ------------------------------------------------------------------ robot

export async function createRobotRun(input: {
    mode: 'check' | 'compile';
    file?: File;
    meshes?: File[];
    target?: 'arm' | 'quadruped';
    label?: string;
}): Promise<RobotRun> {
    const form = new FormData();
    form.append('mode', input.mode);
    if (input.label) form.append('label', input.label);
    if (input.target) form.append('target', input.target);
    if (input.file) form.append('file', input.file, input.file.name);
    for (const m of input.meshes ?? []) form.append('meshes', m, m.name);
    const res = await authedFetch('/api/v1/watchdog/robot/runs', { method: 'POST', body: form });
    if (!res.ok) throw new Error(await readError(res, 'Starting the robot check'));
    return res.json();
}

export const listRobotRuns = () => requestJson<RobotRun[]>('/api/v1/watchdog/robot/runs', 'Loading robot runs');
export const getRobotRun = (id: string) => requestJson<RobotRun>(`/api/v1/watchdog/robot/runs/${id}`, 'Loading the robot run');
export const deleteRobotRun = (id: string) =>
    requestJson<unknown>(`/api/v1/watchdog/robot/runs/${id}`, 'Deleting the robot run', { method: 'DELETE' });

// ------------------------------------------------------------------ files

/** An authenticated file as an object URL (images, GLB). Revoke when done. */
export async function blobUrl(path: string, what: string): Promise<string> {
    const res = await authedFetch(path);
    if (!res.ok) throw new Error(await readError(res, what));
    return URL.createObjectURL(await res.blob());
}

/** Save an authenticated file to disk under `filename`. */
export async function download(path: string, filename: string): Promise<void> {
    const url = await blobUrl(path, `Downloading ${filename}`);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
}
