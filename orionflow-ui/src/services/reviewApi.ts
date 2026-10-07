/**
 * OrionFlow Review API — mounted in the main API at /review, behind the
 * studio's own sign-in. VITE_REVIEW_URL points elsewhere when the review
 * service is hosted separately.
 */
import { authedFetch, readError, requestJson } from './http';

export const REVIEW = (import.meta.env.VITE_REVIEW_URL as string | undefined)?.replace(/\/$/, '') || '/review';
const api = (p: string) => `${REVIEW}/api${p}`;

// ------------------------------------------------------------------ types

export type FileKind = 'step' | 'bom' | 'pdf' | 'urdf' | 'mjcf' | 'mesh' | 'other';
export const FILE_KINDS: FileKind[] = ['step', 'bom', 'pdf', 'urdf', 'mjcf', 'mesh', 'other'];

export interface ReviewFile {
    id: string;
    kind: FileKind;
    kind_source: 'auto' | 'user';
    name: string;
    sha256: string;
    size: number;
}

export type StepState = 'pending' | 'running' | 'done' | 'skipped' | 'failed';

export interface JobStep {
    key: string;
    label: string;
    state: StepState;
    seconds: number | null;
    note: string;
}

export interface Job {
    id: string;
    revision_id: string;
    state: 'queued' | 'running' | 'done' | 'failed' | 'cancelled';
    steps: JobStep[];
    error: string | null;
    created_at: string | null;
    started_at: string | null;
    ended_at: string | null;
}

export interface GraphStats {
    parts: number;
    instances: number;
    assemblies: number;
    max_depth: number;
    triangles: number;
    features?: number;
    contacts?: number;
    flat: boolean;
}

export interface Revision {
    findings?: { critical: number; major: number; minor: number; info: number; total: number; open: number } | null;
    id: string;
    project_id: string;
    label: string;
    git_repo: string | null;
    git_ref: string | null;
    status: 'draft' | 'queued' | 'running' | 'done' | 'failed';
    primary_file_id: string | null;
    created_at: string | null;
    files: ReviewFile[];
    job: Job | null;
    stats: GraphStats | null;
}

export interface ProjectSummary {
    id: string;
    name: string;
    description: string;
    revision_count: number;
    created_at: string;
}

export interface Project extends Omit<ProjectSummary, 'revision_count'> {
    revisions: Revision[];
}

export interface Bbox {
    min: number[];
    max: number[];
}

export interface GraphPart {
    id: string;
    name: string;
    hash: string;
    volume: number;
    area: number;
    bbox: Bbox;
    com: number[];
    valid: boolean;
    problems: string[];
    face_count: number;
    triangle_count: number;
    geometry_type: 'BREP' | 'MESH';
    material: string | null;
    process: string | null;
    mass: number | null;
    features?: string[];
    plane_count?: number;
}

/** Part frame, millimetres. */
export interface HoleFeature {
    id: string;
    part_id: string;
    kind: 'hole';
    center: number[];
    axis: number[];
    diameter: number;
    depth: number;
    through: boolean | null;
}
export interface CylinderFeature {
    id: string;
    part_id: string;
    kind: 'cylinder';
    center: number[];
    axis: number[];
    diameter: number;
    length: number;
}
export interface PatternFeature {
    id: string;
    part_id: string;
    kind: 'pattern';
    pattern: 'circle' | 'rect' | 'group';
    count: number;
    diameter: number;
    pcd: number | null;
    a: number | null;
    b: number | null;
    axis: number[];
    centroid: number[];
    holes: string[];
    description: string;
}
export type GraphFeature = HoleFeature | CylinderFeature | PatternFeature;

export interface ContactFit {
    shaft_on: 'a' | 'b';
    hole_diameter: number;
    shaft_diameter: number;
    clearance: number;
    axis: number[];
    point: number[];
}

/** Assembly frame, millimetres. */
export interface GraphContact {
    id: string;
    a: string;
    b: string;
    type: 'cylindrical' | 'coaxial-hole' | 'planar' | 'point' | 'adjacent';
    kinds: string[];
    min_distance: number | null;
    exact: boolean;
    point: number[] | null;
    planes: { point: number[]; normal: number[] }[];
    fits: ContactFit[];
    coaxial_holes: { diameter_a: number; diameter_b: number; axis: number[]; point: number[] }[];
    method: string;
}

export interface GraphInstance {
    id: string;
    part_id: string;
    path: string;
    name: string;
    transform: number[][];
    parent: string | null;
    bbox: Bbox;
}

export interface TreeNode {
    key: string;
    name: string;
    instance: string | null;
    children: TreeNode[];
}

export interface SourceFile {
    name: string;
    kind: FileKind;
    sha256: string;
    size: number;
}

export interface ModelGraph {
    schema_version: string;
    revision_id: string;
    units: 'mm';
    source: SourceFile;
    files: SourceFile[];
    stats: GraphStats;
    parts: GraphPart[];
    instances: GraphInstance[];
    tree: TreeNode;
    ingest_notes: string[];
    features?: GraphFeature[];
    contacts?: GraphContact[];
}

// ------------------------------------------------------------------ calls

export const listProjects = () => requestJson<ProjectSummary[]>(api('/projects'), 'Loading projects');
export const createProject = (name: string, description = '') =>
    requestJson<ProjectSummary>(api('/projects'), 'Creating the project', {
        method: 'POST',
        body: JSON.stringify({ name, description }),
    });
export const getProject = (pid: string) => requestJson<Project>(api(`/projects/${pid}`), 'Loading the project');
export const archiveProject = (pid: string) =>
    requestJson<void>(api(`/projects/${pid}`), 'Archiving the project', { method: 'DELETE' });

async function upload<T>(path: string, files: File[], fields: Record<string, string>, what: string): Promise<T> {
    const form = new FormData();
    for (const f of files) form.append('files', f, (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name);
    for (const [k, v] of Object.entries(fields)) if (v) form.append(k, v);
    const res = await authedFetch(api(path), { method: 'POST', body: form });
    if (!res.ok) throw new Error(await readError(res, what));
    return (await res.json()) as T;
}

export const createRevision = (pid: string, files: File[], label: string, gitRepo = '', gitRef = '') =>
    upload<Revision>(`/projects/${pid}/revisions`, files, { label, git_repo: gitRepo, git_ref: gitRef }, 'Uploading the package');
export const addFiles = (rid: string, files: File[]) =>
    upload<Revision>(`/revisions/${rid}/files`, files, {}, 'Adding files');
export const getRevision = (rid: string) => requestJson<Revision>(api(`/revisions/${rid}`), 'Loading the revision');
export const setPrimary = (rid: string, primary_file_id: string) =>
    requestJson<Revision>(api(`/revisions/${rid}`), 'Choosing the assembly', {
        method: 'PATCH',
        body: JSON.stringify({ primary_file_id }),
    });
export const setFileKind = (rid: string, fid: string, kind: FileKind) =>
    requestJson<ReviewFile>(api(`/revisions/${rid}/files/${fid}`), 'Changing the file type', {
        method: 'PATCH',
        body: JSON.stringify({ kind }),
    });
export const deleteFile = (rid: string, fid: string) =>
    requestJson<void>(api(`/revisions/${rid}/files/${fid}`), 'Removing the file', { method: 'DELETE' });
export const runReview = (rid: string) => requestJson<Job>(api(`/revisions/${rid}/run`), 'Starting the review', { method: 'POST' });
export const getJob = (jid: string) => requestJson<Job>(api(`/jobs/${jid}`), 'Checking the job');
export const getGraph = (rid: string) => requestJson<ModelGraph>(api(`/revisions/${rid}/graph`), 'Loading the model graph');
export const createYubiDemo = () => requestJson<Project>(api('/demo/yubi'), 'Fetching YUBI from GitHub', { method: 'POST' });

export async function fetchViewerGlb(rid: string): Promise<ArrayBuffer> {
    const res = await authedFetch(api(`/revisions/${rid}/viewer.glb`));
    if (!res.ok) throw new Error(await readError(res, 'Loading the 3D model'));
    return res.arrayBuffer();
}

// ------------------------------------------------------------------ format

export function fmtBytes(n: number): string {
    if (n < 1024) return `${n} B`;
    if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / 1024 ** 2).toFixed(1)} MB`;
}

/** Fixed-point mm with thin grouping, never scientific. */
export function fmtNum(v: number, digits = 2): string {
    return v.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

// ------------------------------------------------------------------ findings

export type Severity = 'critical' | 'major' | 'minor' | 'info';
export type FindingStatus = 'open' | 'accepted' | 'rejected' | 'fixed' | 'deferred';
export type Provenance = 'geometry' | 'rule' | 'ai_reading' | 'ai_inference';
export const SEVERITIES: Severity[] = ['critical', 'major', 'minor', 'info'];

export interface Quantity {
    value?: number;
    min?: number;
    max?: number;
    unit?: string;
    basis?: string;
    text?: string;
}

export interface Evidence {
    type: 'instance' | 'part' | 'feature' | 'contact' | 'measurement' | 'file' | 'bom_row' | 'document' | 'joint';
    id?: string;
    kind?: string;
    label?: string;
    points?: number[][];
    value?: number;
    unit?: string;
    sha256?: string;
}

export interface Finding {
    id: string;
    fingerprint: string;
    check_id: string;
    check_version: string;
    domain: string;
    severity: Severity;
    status: FindingStatus;
    provenance: Provenance;
    title: string;
    statement: string;
    measured: Quantity | null;
    expected: Quantity | null;
    evidence: Evidence[];
    recommendation: string;
    active: boolean;
    owner: string | null;
    created_at: string | null;
    updated_at: string | null;
}

export interface FindingEvent {
    id: string;
    user_id: string;
    action: 'detected' | 'status' | 'owner' | 'comment' | 'redetected' | 'resolved';
    from_status: FindingStatus | null;
    to_status: FindingStatus | null;
    note: string | null;
    created_at: string | null;
}

export interface CheckRun {
    check_id: string;
    check_version: string;
    domain: string;
    title: string;
    kind: 'deterministic' | 'ai_assisted';
    status: 'passed' | 'findings' | 'not_run' | 'error';
    reason: string | null;
    findings: number;
    seconds: number | null;
}

export interface FindingsSummary {
    critical: number;
    major: number;
    minor: number;
    info: number;
    total: number;
    open: number;
}

export interface FindingsPayload {
    findings: Finding[];
    check_runs: CheckRun[];
    summary: FindingsSummary;
    domains: Record<string, string>;
}

export const listFindings = (rid: string, includeResolved = false) =>
    requestJson<FindingsPayload>(api(`/revisions/${rid}/findings${includeResolved ? '?include_resolved=true' : ''}`), 'Loading findings');
export const getFinding = (fid: string) =>
    requestJson<Finding & { events: FindingEvent[] }>(api(`/findings/${fid}`), 'Loading the finding');
export const patchFinding = (fid: string, body: { status?: FindingStatus; owner?: string; clear_owner?: boolean; note?: string }) =>
    requestJson<Finding & { events: FindingEvent[] }>(api(`/findings/${fid}`), 'Updating the finding', {
        method: 'PATCH',
        body: JSON.stringify(body),
    });
export const commentFinding = (fid: string, text: string) =>
    requestJson<Finding & { events: FindingEvent[] }>(api(`/findings/${fid}/comments`), 'Posting the comment', {
        method: 'POST',
        body: JSON.stringify({ text }),
    });

/** Download the JSON report (authenticated fetch -> blob -> save). */
export async function downloadReportJson(rid: string, filename: string): Promise<void> {
    const res = await authedFetch(api(`/revisions/${rid}/report.json`));
    if (!res.ok) throw new Error(await readError(res, 'Exporting the report'));
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/** Findings that point at an instance (directly, through its part, or through a contact it is in). */
export function findingsFor(findings: Finding[], instanceId: string, partId: string, contactIds: Set<string>): Finding[] {
    return findings.filter((f) => f.evidence.some((e) =>
        (e.type === 'instance' && e.id === instanceId) || (e.type === 'part' && e.id === partId)
        || (e.type === 'contact' && e.id !== undefined && contactIds.has(e.id))));
}
