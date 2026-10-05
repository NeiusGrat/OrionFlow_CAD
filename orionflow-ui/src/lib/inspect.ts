/** Shared vocabulary for OrionFlow Inspect screens. */
import type { Characteristic, Revision } from '../services/faiApi';

export const TOL_SOURCE: Record<string, string> = {
    drawing: 'drawing',
    iso286: 'ISO 286 fit',
    general_note: 'general note',
    selected_class: 'selected class',
    gdt: 'GD&T frame',
    reviewer: 'reviewer',
    none: 'none',
};

export const CAD_WORD: Record<string, string> = {
    agrees: 'agrees',
    deviates: 'disagrees',
    count: 'count differs',
    not_found: 'not in model',
    not_measurable: 'n/a',
    no_model: 'no model',
    '': '—',
};

export function fmt(v: number | null | undefined, digits = 4): string {
    if (v === null || v === undefined || Number.isNaN(v)) return '';
    const s = v.toFixed(digits).replace(/0+$/, '').replace(/\.$/, '');
    return s === '-0' ? '0' : s;
}

export function limits(c: Characteristic): string {
    if (c.lower !== null && c.upper !== null) return `${fmt(c.lower)} – ${fmt(c.upper)}`;
    if (c.upper !== null) return `≤ ${fmt(c.upper)}`;
    if (c.lower !== null) return `≥ ${fmt(c.lower)}`;
    return '';
}

/** Workflow status shown in tables: Draft / Checking / In review / Signed / Failed. */
export function revStatus(r?: Revision | null): { word: string; cls: string } {
    if (!r) return { word: 'No revision', cls: '' };
    if (r.signoff || r.status === 'signed') return { word: 'Signed', cls: 'signed' };
    if (r.status === 'error') return { word: 'Failed', cls: 'failed' };
    if (r.status === 'queued' || r.status === 'running') return { word: 'Checking', cls: 'checking' };
    return { word: 'In review', cls: 'review' };
}

export function when(t: number | null | undefined): string {
    if (!t) return '';
    const d = new Date(t * 1000);
    return d.toLocaleString(undefined, { year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

export const short = (sha?: string | null) => (sha ? sha.slice(0, 10) : '—');

export const ACTION_WORD: Record<string, string> = {
    project_created: 'Project created',
    project_updated: 'Project details changed',
    revision_uploaded: 'Revision uploaded',
    revision_checked: 'Checked',
    revision_failed: 'Check failed',
    characteristic_edited: 'Characteristic edited',
    finding_decided: 'Finding decided',
    form1_updated: 'Form 1 updated',
    draft_exported: 'Draft exported',
    revision_signed: 'Signed',
    revision_deleted: 'Revision deleted',
};
