/**
 * The topology sidecar and the semantic-edit routes.
 *
 * Everything goes through `requestJson`/`authedFetch` so a studio left open
 * past the 15-minute access-token life refreshes instead of 401-ing — the bug
 * that once made Save look broken. No `fetch` in this file.
 *
 * The split between the calls mirrors what they cost on the server:
 * `inspect` and `plan` touch no kernel and are free, so the UI may call them on
 * hover and on every frame of a drag; `commit` runs FreeCAD and is metered.
 */

import { API_BASE, requestJson, authedFetch, readError } from './http';
import type { TopologyRecord } from '../lib/faceMap';
import type { FeatureTree, StudioFiles, StudioStats } from './studioApi';
import type { VerificationReport } from './agentApi';

/** Where the user pointed. Exactly one field. */
export interface EditTarget {
    feature?: string;
    selector?: string;
    point?: number[];
}

export interface EditParameter {
    name: string;
    expression: string;
    value: number;
    variables: string[];
    /** True when the expression is one variable, so the value can be set. */
    direct: boolean;
    variable: string | null;
    /** Other places the same variables drive — the design's own linkages. */
    shared_with: string[];
}

export interface InspectResult {
    feature: string;
    resolved: {
        via: 'feature' | 'selector' | 'point';
        element?: { ref: string; stable?: string; surface?: string; area?: number };
        other_candidates?: { ref: string; feature: string | null; distance: number }[];
    };
    parameters: EditParameter[];
    editable: boolean;
}

export interface EditMove {
    path: string;
    expression: string;
    before: number;
    after: number;
}

export interface EditPlan {
    feature: string;
    parameter: string;
    variable: string;
    before: number;
    after: number;
    also_moves: EditMove[];
    assertions_moved: EditMove[];
    contract_preserved: boolean;
}

export interface CommitResult {
    success: boolean;
    plan: EditPlan;
    part_class: string;
    blueprint: Record<string, unknown> | null;
    variables: Record<string, number>;
    files: StudioFiles;
    feature_tree: FeatureTree | null;
    stats: StudioStats | null;
    verification: VerificationReport | null;
    /** Always false for a retune — carried, not assumed. */
    contract_broken: boolean;
    generation_time_ms: number;
    request_id: string;
    error: string | null;
}

/**
 * The full topology record for a build.
 *
 * Read from the artifact route rather than `/api/v1/topology/{id}`, which
 * returns only the summary: the viewer needs every face's surface parameters to
 * attribute triangles, and a tally cannot do that.
 *
 * Returns null rather than throwing. A part built before the sidecar existed
 * has none, and that must degrade to "clicking does nothing" rather than to an
 * error banner over a model that is otherwise fine.
 */
export async function fetchTopology(requestId: string): Promise<TopologyRecord | null> {
    if (!requestId) return null;
    try {
        const res = await authedFetch(
            `${API_BASE}/api/v1/artifacts/${requestId}/part.topology.json`,
        );
        if (!res.ok) return null;
        const record = (await res.json()) as TopologyRecord;
        return record && !record.error ? record : null;
    } catch {
        return null;
    }
}

export function inspectTarget(body: {
    blueprint: Record<string, unknown>;
    target: EditTarget;
    request_id?: string;
}): Promise<InspectResult> {
    return requestJson<InspectResult>('/api/v1/studio/edit/inspect', 'Inspect', {
        method: 'POST',
        body: JSON.stringify(body),
    });
}

export function planEdit(body: {
    blueprint: Record<string, unknown>;
    target: EditTarget;
    parameter: string;
    value: number;
    request_id?: string;
}): Promise<{ plan: EditPlan }> {
    return requestJson<{ plan: EditPlan }>('/api/v1/studio/edit/plan', 'Preview', {
        method: 'POST',
        body: JSON.stringify(body),
    });
}

export interface OperationSpec {
    kind: string;
    target: 'edge' | 'face';
    dimensions: {
        name: string;
        label: string;
        unit: string;
        default: number;
        min?: number;
        max?: number;
    }[];
    blurb: string;
}

export interface OperationCatalogue {
    operations: OperationSpec[];
    /** Not wired up yet, each with the reason — shown, not hidden. */
    planned: { kind: string; reason: string }[];
}

export interface PlannedOperation {
    kind: string;
    target_kind: 'edge' | 'face';
    selector: string;
    on_feature: string | null;
    variables: Record<string, number>;
    parameters: Record<string, unknown>;
    label: string;
    /** Always true: adding a feature puts geometry outside the authored contract. */
    contract_broken: boolean;
}

export interface AddResult extends Omit<CommitResult, 'plan'> {
    operation: PlannedOperation;
    /**
     * Why the operation did not reach the geometry, or null if it did.
     *
     * A build that produced a solid is not a build that applied the operation:
     * a failed dressup leaves the previous geometry standing, so the volume is
     * unchanged and every assertion still passes. This carries the kernel's own
     * reason so the panel can say what happened instead of showing a success
     * that changed nothing.
     */
    not_applied: string | null;
}

export function fetchOperations(): Promise<OperationCatalogue> {
    return requestJson<OperationCatalogue>(
        '/api/v1/studio/edit/operations',
        'Load operations',
    );
}

export function planAdd(body: {
    blueprint: Record<string, unknown>;
    operation: string;
    target: EditTarget;
    dimensions: Record<string, number>;
    request_id?: string;
}): Promise<{ operation: PlannedOperation }> {
    return requestJson('/api/v1/studio/edit/add/plan', 'Preview', {
        method: 'POST',
        body: JSON.stringify(body),
    });
}

export function commitAdd(body: {
    blueprint: Record<string, unknown>;
    operation: string;
    target: EditTarget;
    dimensions: Record<string, number>;
    request_id?: string;
}): Promise<AddResult> {
    return requestJson<AddResult>('/api/v1/studio/edit/add/commit', 'Apply', {
        method: 'POST',
        body: JSON.stringify(body),
    });
}

export function commitEdit(body: {
    blueprint: Record<string, unknown>;
    target: EditTarget;
    parameter: string;
    value: number;
    request_id?: string;
}): Promise<CommitResult> {
    return requestJson<CommitResult>('/api/v1/studio/edit/commit', 'Edit', {
        method: 'POST',
        body: JSON.stringify(body),
    });
}

export { readError };
