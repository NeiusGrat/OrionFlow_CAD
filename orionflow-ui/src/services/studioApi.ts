/**
 * Studio API — the fine-tuned model, streamed.
 *
 * EventSource cannot POST, so the SSE frames are parsed off a fetch body
 * reader. Frames are split on a blank line and may arrive cut in half, so a
 * buffer is carried across chunks; dropping a partial frame would silently
 * lose whole tokens of the derivation.
 */

import type { VerificationReport } from './agentApi';

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

export interface StudioChatRequest {
    message: string;
    part?: Record<string, unknown> | null;
    history?: { role: string; content: string }[];
    intent?: 'design' | 'explain';
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
    const res = await fetch(`${API_BASE}/api/v1/studio/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(body),
        signal,
    });

    if (!res.ok || !res.body) {
        let detail = res.statusText;
        try {
            const j = await res.json();
            if (typeof j.detail === 'string') {
                detail = j.detail;
            } else if (j.detail && typeof j.detail.error === 'string') {
                // Structured refusals — the quota gate sends {error, reason,
                // used, limit} so the panel can say which limit was reached
                // rather than "Too Many Requests".
                detail = j.detail.error;
            }
        } catch {
            /* the body was not JSON; the status text stands */
        }
        onEvent({ type: 'error', error: detail || 'the studio request failed' });
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
        const res = await fetch(`${API_BASE}/api/v1/studio/health`, { headers: authHeaders() });
        return res.ok ? await res.json() : null;
    } catch {
        return null;
    }
}

/** Absolute URL for a server-relative artifact path. */
export function fullUrl(path?: string | null): string {
    if (!path) return '';
    return path.startsWith('http') ? path : `${API_BASE}${path}`;
}
