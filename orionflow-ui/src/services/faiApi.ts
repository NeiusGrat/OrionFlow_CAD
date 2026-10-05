/** OrionFlow Inspect API (/api/v1/fai). Every call goes through authedFetch. */
import { authedFetch, readError, requestJson } from './http';

export type Severity = 'critical' | 'major' | 'minor';
export type CharStatus = 'open' | 'pass' | 'fail' | 'accepted' | 'waived';
export type Decision = '' | 'accepted' | 'rejected' | 'ignored';

export interface Characteristic {
    no: number;
    page: number;
    zone: string;
    kind: 'dimension' | 'thread' | 'gdt' | 'surface' | 'note';
    type: string;
    designator: string;
    requirement: string;
    nominal: number | null;
    tol_minus: number | null;
    tol_plus: number | null;
    lower: number | null;
    upper: number | null;
    unit: string;
    count: number;
    tol_source: string;
    tol_note: string;
    confidence: string;
    bbox: number[];
    balloon: number[];
    inspect: boolean;
    method: string;
    cad_value: number | null;
    cad_count: number | null;
    cad_nodes: string[];
    cad_status: string;
    cad_note: string;
    result: string;
    status: CharStatus;
    nc_number: string;
    tooling: string;
    reviewer_note: string;
    key?: string;
    edited: boolean;
}

export interface Finding {
    id: string;
    severity: Severity;
    kind: 'cad' | 'bom' | 'drawing' | 'tolerance';
    title: string;
    message: string;
    char_no: number | null;
    drawing_value: string;
    cad_value: string;
    rule: string;
    page: number | null;
    bbox: number[];
    evidence: string;
    cad_nodes: string[];
    query: string;
    decision: Decision;
    note: string;
}

export interface Step {
    id: string;
    name: string;
    status: 'pending' | 'running' | 'done' | 'error' | 'waiting';
    detail?: string;
    duration_s?: number;
}

export interface Form1 {
    [k: string]: string;
}

export interface Form2Row {
    type: string;
    name: string;
    specification: string;
    code: string;
    supplier: string;
    approval: string;
    certificate: string;
    source: string;
}

export interface Result {
    status: 'done' | 'error';
    error?: string;
    title: Record<string, string>;
    options: Record<string, string>;
    characteristics: Characteristic[];
    findings: Finding[];
    steps: Step[];
    has_glb: boolean;
    warnings: string[];
    general_tolerance: { general_tolerance: { standard: string; linear_class: string; text: string } | null; applied_class: string | null; applied_source: string; units?: string; units_stated?: boolean; general_profile?: string | null };
    drawing: { pages: { w: number; h: number; layer: string; scanned: boolean }[]; warnings: string[] };
    cad: { extents: number[]; volume_mm3: number; faces: number; solids: number; warnings: string[] } | null;
    bom_row: Record<string, unknown> | null;
    files: Record<string, { name: string; sha256: string }>;
    forms: { form1: Form1; form2: Form2Row[]; form3: unknown[] };
    accuracy: Accuracy | null;
    vision: { model: string; pages: number; cost_usd: number; failed_pages: number } | null;
    title_from?: Record<string, string>;
    stats: { sheets: number; characteristics: number; runtime_s: number; model: string; cost_usd: number; engine_version: string; findings: Record<Severity, number> };
}

export interface Accuracy {
    key_source: string;
    total: number;
    matched: number;
    partial: number;
    missed: number;
    extra: number[];
    recall: number | null;
    recall_with_partial: number | null;
    precision: number | null;
    rows: { kind: 'dimension' | 'gdt'; status: 'matched' | 'partial' | 'missed'; char_no: number | null; key: string; read: string }[];
}

export interface Event {
    id: number;
    at: number;
    actor: string;
    action: string;
    target: string;
    detail: Record<string, unknown>;
    revision_id: string | null;
}

export interface Signoff {
    name: string;
    role: string;
    at: string;
    fai_scope: string;
    open_characteristics: number[];
}

export interface Revision {
    id: string;
    project_id: string;
    label: string;
    status: 'queued' | 'running' | 'done' | 'error' | 'signed';
    created: number;
    finished: number | null;
    drawing_name: string;
    drawing_sha: string;
    step_name: string | null;
    step_sha: string | null;
    bom_name: string | null;
    bom_sha: string | null;
    options: Record<string, string>;
    error: string | null;
    progress: Step[];
    signoff: Signoff | null;
    drawing_changed?: boolean | null;
    result?: Result;
    project?: Project;
    events?: Event[];
    previous?: { id: string; label: string; drawing_sha: string } | null;
    readiness?: { undecided_critical: string[]; open_characteristics: number[]; failed_without_nc: number[]; can_sign: boolean };
}

export interface Project {
    id: string;
    part_number: string;
    part_name: string;
    customer: string;
    created: number;
    revisions?: Revision[] | number;
    latest?: Revision | null;
    events?: Event[];
}

export interface CompareRow {
    status: 'same' | 'changed' | 'added' | 'removed';
    old: Characteristic | null;
    new: Characteristic | null;
    what: string;
}

export interface Comparison {
    rows: CompareRow[];
    counts: Record<'same' | 'changed' | 'added' | 'removed', number>;
    a: { id: string; label: string; drawing_sha: string; pages: { w: number; h: number }[]; title: Record<string, string> };
    b: { id: string; label: string; drawing_sha: string; pages: { w: number; h: number }[]; title: Record<string, string> };
    same_drawing: boolean;
}

const B = '/api/v1/fai';

export const listProjects = () => requestJson<Project[]>(`${B}/projects`, 'Loading projects');
export const getProject = (id: string) => requestJson<Project & { revisions: Revision[]; events: Event[] }>(`${B}/projects/${id}`, 'Loading the project');
export const createProject = (p: Partial<Project>) =>
    requestJson<Project>(`${B}/projects`, 'Creating the project', { method: 'POST', body: JSON.stringify(p) });
export const updateProject = (id: string, p: Partial<Project>) =>
    requestJson<Project>(`${B}/projects/${id}`, 'Saving the project', { method: 'PATCH', body: JSON.stringify(p) });
export const deleteProject = (id: string) => requestJson<unknown>(`${B}/projects/${id}`, 'Deleting the project', { method: 'DELETE' });
export const createSample = () => requestJson<Project>(`${B}/sample`, 'Creating the sample project', { method: 'POST' });

export async function createRevision(pid: string, input: {
    drawing: File; step?: File | null; bom?: File | null; standard: string; general_class: string; label?: string; po_number?: string;
}): Promise<Revision> {
    const form = new FormData();
    form.append('drawing', input.drawing, input.drawing.name);
    if (input.step) form.append('step', input.step, input.step.name);
    if (input.bom) form.append('bom', input.bom, input.bom.name);
    form.append('standard', input.standard);
    form.append('general_class', input.general_class);
    if (input.label) form.append('label', input.label);
    if (input.po_number) form.append('po_number', input.po_number);
    const res = await authedFetch(`${B}/projects/${pid}/revisions`, { method: 'POST', body: form });
    if (!res.ok) throw new Error(await readError(res, 'Uploading'));
    return res.json();
}

export const getRevision = (id: string) => requestJson<Revision>(`${B}/revisions/${id}`, 'Loading the inspection');
export const deleteRevision = (id: string) => requestJson<unknown>(`${B}/revisions/${id}`, 'Deleting the revision', { method: 'DELETE' });
export const editCharacteristic = (rid: string, no: number, fields: Partial<Characteristic>) =>
    requestJson<Characteristic>(`${B}/revisions/${rid}/characteristics/${no}`, 'Saving the characteristic', {
        method: 'PATCH', body: JSON.stringify(fields),
    });
export const decideFinding = (rid: string, fid: string, decision: Decision, note = '', for_customer = false) =>
    requestJson<Finding>(`${B}/revisions/${rid}/findings/${fid}`, 'Saving the decision', {
        method: 'POST', body: JSON.stringify({ decision, note, for_customer }),
    });
export const updateForm1 = (rid: string, fields: Record<string, string>) =>
    requestJson<Form1>(`${B}/revisions/${rid}/form1`, 'Saving Form 1', { method: 'PATCH', body: JSON.stringify(fields) });
export const signRevision = (rid: string, name: string, role: string) =>
    requestJson<Signoff>(`${B}/revisions/${rid}/sign`, 'Signing', { method: 'POST', body: JSON.stringify({ name, role }) });
export const compareRevisions = (a: string, b: string) =>
    requestJson<Comparison>(`${B}/compare?a=${a}&b=${b}`, 'Comparing revisions');

export const fileUrl = (rid: string, name: string) => `${B}/revisions/${rid}/files/${name}`;
export const pageUrl = (rid: string, n: number, dpi = 110) => `${B}/revisions/${rid}/pages/${n}.png?dpi=${dpi}`;
