/**
 * Studio API — the fine-tuned model, streamed.
 *
 * EventSource cannot POST, so the SSE frames are parsed off a fetch body
 * reader. Frames are split on a blank line and may arrive cut in half, so a
 * buffer is carried across chunks; dropping a partial frame would silently
 * lose whole tokens of the derivation.
 */

import type { VerificationReport } from './agentApi';
import { API_BASE, authedFetch, readError, requestJson, fullUrl } from './http';

export { fullUrl };

export interface StudioStats {
    volume_mm3: number;
    bbox_mm: number[];
    watertight: boolean;
    solids?: number | null;
    valid?: boolean | null;
}

export interface StudioFiles {
    step?: string;
    stl?: string;
    glb?: string;
}

/** A stage that genuinely happened, reported when it happened. */
export interface StudioStep {
    id: string;
    label: string;
    status: 'active' | 'done' | 'fail';
    detail: string;
    items: string[];
}

/** One feature in the build history, as the kernel actually executed it. */
export interface FeatureNode {
    id: string;
    type: string;
    label: string;
    rationale: string;
    /** Dimensions as built. Empty when the Blueprint could not be resolved. */
    parameters: Record<string, number>;
    /** The expressions behind those numbers — why the feature is that size. */
    expressions: Record<string, string | number>;
    /** What this feature added (+) or removed (−). `null` means unmeasured,
     *  which is not the same as zero and must not be rendered as one. */
    volume_delta_mm3: number | null;
    cumulative_volume_mm3: number | null;
    status: 'success' | 'error' | 'unsupported' | 'unknown';
    error: string | null;
}

export interface FeatureTree {
    part_class: string;
    blueprint_hash: string;
    variables: Record<string, number>;
    features: FeatureNode[];
    /** False when no build record was found — every volume will be null. */
    evidence_available: boolean;
    parameters_resolved: boolean;
    verdict: string;
    built_where: string;
}

/** The readable account of a design, derived from the frozen Blueprint. */
export interface NarrativeSection {
    title: string;
    body: string;
    items?: string[];
}

export interface DesignNarrative {
    headline: string;
    sections: NarrativeSection[];
    verdict: string;
}

/** Terminal payload of a successful design turn. */
export interface StudioDesignResult {
    intent: 'design';
    success: true;
    model: string;
    part_class: string;
    variables: Record<string, number>;
    blueprint: Record<string, unknown> | null;
    narrative: DesignNarrative | null;
    /** Assembled server-side so a live part and a reopened one agree. */
    feature_tree: FeatureTree | null;
    thinking: string;
    files: StudioFiles;
    stats: StudioStats | null;
    verification: VerificationReport | null;
    generation_time_ms: number;
    request_id: string;
}

export interface StudioExplainResult {
    intent: 'explain';
    success: boolean;
    answer: string;
    model: string;
    error?: string | null;
}

export type StudioEvent =
    | { type: 'model'; model: string; provider: string }
    | { type: 'phase'; phase: 'reasoning' | 'building' }
    | { type: 'step'; step: StudioStep }
    | { type: 'narrative'; narrative: DesignNarrative }
    | { type: 'thinking'; text: string }
    | { type: 'answer'; text: string }
    | { type: 'built'; success: boolean; files: StudioFiles; stats: StudioStats | null; error: string | null }
    | { type: 'verification'; report: VerificationReport }
    | { type: 'done'; result: StudioDesignResult | StudioExplainResult }
    | { type: 'error'; error: string; raw_completion?: string; model?: string };

/** What the assistant is being asked to look at.
 *
 *  A lens only ever changes the conversation role. The design role is left
 *  exactly as the model was fine-tuned and graded — 94% VERIFIED was measured
 *  on that prompt distribution, and appending a manufacturing preamble to it
 *  would move the model off the distribution it was scored on.
 */
export type Lens =
    | 'modeling'
    | 'dfm'
    | 'dfm_3d_printing'
    | 'dfm_sheet_metal'
    | 'dfm_machining';

export const LENSES: { id: Lens; label: string; hint: string }[] = [
    { id: 'modeling', label: 'Modeling', hint: 'Geometry, features and dimensions' },
    { id: 'dfm', label: 'DFM', hint: 'Manufacturability, whatever the process' },
    { id: 'dfm_3d_printing', label: 'DFM · 3D printing', hint: 'Overhangs, supports, layer adhesion' },
    { id: 'dfm_sheet_metal', label: 'DFM · Sheet metal', hint: 'Bend radii, relief cuts, flat pattern' },
    { id: 'dfm_machining', label: 'DFM · Machining', hint: 'Tool access, internal radii, setups' },
];

export interface StudioChatRequest {
    message: string;
    part?: Record<string, unknown> | null;
    history?: { role: string; content: string }[];
    intent?: 'design' | 'explain';
    lens?: Lens;
}

/**
 * Stream one studio turn. `onEvent` fires for every server event in order.
 * Resolves once a terminal event (done/error) has been delivered.
 */
export async function streamStudioChat(
    body: StudioChatRequest,
    onEvent: (e: StudioEvent) => void,
    signal?: AbortSignal
): Promise<void> {
    let res: Response;
    try {
        res = await authedFetch('/api/v1/studio/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
            signal,
        });
    } catch (e: any) {
        // A dead session throws rather than returning a response; the panel
        // still has to say something, so it becomes an error event.
        onEvent({ type: 'error', error: e?.message || 'the studio request failed' });
        return;
    }

    if (!res.ok || !res.body) {
        // Structured refusals from the quota gate arrive with `reason`, `used`
        // and `limit` beside the message, so the panel names the limit that was
        // reached rather than saying "Too Many Requests".
        onEvent({ type: 'error', error: await readError(res, 'The studio request') });
        return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let split: number;
        while ((split = buffer.indexOf('\n\n')) !== -1) {
            const frame = buffer.slice(0, split);
            buffer = buffer.slice(split + 2);

            let event = '';
            let data = '';
            for (const line of frame.split('\n')) {
                if (line.startsWith('event:')) event = line.slice(6).trim();
                else if (line.startsWith('data:')) data += line.slice(5).trim();
            }
            if (!event || !data) continue;

            let parsed: any;
            try {
                parsed = JSON.parse(data);
            } catch {
                continue;
            }
            onEvent(toEvent(event, parsed));
        }
    }
}

function toEvent(event: string, d: any): StudioEvent {
    switch (event) {
        case 'model':
            return { type: 'model', model: d.model, provider: d.provider };
        case 'phase':
            return { type: 'phase', phase: d.phase };
        case 'step':
            return {
                type: 'step',
                step: {
                    id: d.id,
                    label: d.label,
                    status: d.status,
                    detail: d.detail ?? '',
                    items: d.items ?? [],
                },
            };
        case 'narrative':
            return { type: 'narrative', narrative: d as DesignNarrative };
        case 'thinking':
            return { type: 'thinking', text: d.text ?? '' };
        case 'answer':
            return { type: 'answer', text: d.text ?? '' };
        case 'built':
            return {
                type: 'built',
                success: !!d.success,
                files: d.files ?? {},
                stats: d.stats ?? null,
                error: d.error ?? null,
            };
        case 'verification':
            return { type: 'verification', report: d as VerificationReport };
        case 'done':
            return { type: 'done', result: d };
        default:
            return { type: 'error', error: d.error ?? 'unknown studio event', raw_completion: d.raw_completion, model: d.model };
    }
}

export interface StudioHealth {
    provider: string;
    fallback: string;
    /** True only when the configured provider serves OUR fine-tuned weights. */
    serving_our_model: boolean;
    model: string;
    /** Absent for anonymous callers — the server redacts our own GPU host on
     *  the open health route. */
    endpoint?: string;
    builder: string;
    builder_mode: string;
}

export async function fetchStudioHealth(): Promise<StudioHealth | null> {
    try {
        // Deliberately a plain fetch: health is reachable signed out, and a
        // 401 here must not trigger a refresh-and-retry cycle at page load.
        const res = await fetch(`${API_BASE}/api/v1/studio/health`);
        return res.ok ? await res.json() : null;
    } catch {
        return null;
    }
}

/* ────────────────────────── rebuild ────────────────────────── */

/** A hand edit to apply before rebuilding.
 *
 *  `variables` retunes numbers the Blueprint already declares — the assertions
 *  are expressions over those variables, so they still hold and the part is
 *  still graded. `add_feature` appends a new operation, which changes the
 *  template and therefore the contract: the server re-checks and re-hashes it,
 *  and the result is honestly a new Blueprint rather than the graded one.
 */
export interface RebuildRequest {
    blueprint: Record<string, unknown>;
    variables?: Record<string, number>;
    add_feature?: {
        type: string;
        label?: string;
        /** Named so they can be tuned later like any other dimension. */
        variables?: Record<string, number>;
        parameters?: Record<string, unknown>;
    };
}

export interface RebuildResult {
    success: boolean;
    part_class: string;
    variables: Record<string, number>;
    blueprint: Record<string, unknown> | null;
    feature_tree: FeatureTree | null;
    files: StudioFiles;
    stats: StudioStats | null;
    verification: VerificationReport | null;
    /** True when the template changed, so the model's original assertions no
     *  longer describe this geometry and the UI must stop implying they do. */
    contract_broken: boolean;
    generation_time_ms: number;
    request_id: string;
    error: string | null;
}

export async function rebuildPart(body: RebuildRequest): Promise<RebuildResult> {
    return requestJson<RebuildResult>('/api/v1/studio/rebuild', 'The rebuild', {
        method: 'POST',
        body: JSON.stringify(body),
    });
}
