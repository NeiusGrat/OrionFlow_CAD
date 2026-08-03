/**
 * Design sessions: the studio workflow with a person in the middle.
 *
 * `studioApi` designs and builds in one call and streams the result. This is
 * the other shape — a design that stops, waits to be read, and is built only
 * once someone says so. The differences that matter to a client:
 *
 * **State is a field, never an inference.** Every response carries `state` from
 * the server's own state machine. The UI switches on it and nothing else; it
 * must never conclude "this is probably building" from the presence of some
 * text, because the server is the only thing that knows.
 *
 * **Progress is a log with a cursor, not a stream.** A build outlives the
 * request that started it, and an approval happens on human time, so events are
 * numbered and replayable. Reconnecting means sending the last `seq` seen — a
 * refresh, a dropped connection or a phone waking up loses nothing.
 *
 * **Refusals are typed.** A 403 `approval_required` and a 409 `stale_revision`
 * need different handling — one is a bug in the client's flow, the other means
 * refresh and look again — so the `reason` travels and the UI acts on it.
 */

import { API_BASE, authedFetch, requestJson } from './http';
import type { StudioCritique, StudioFiles, StudioStats } from './studioApi';
import type { VerificationReport } from './agentApi';

const ROOT = '/api/v1/studio/sessions';

/** Where a session is resting. Mirrors `app/domain/design_session.py`. */
export type SessionState =
    | 'draft'
    | 'questions'
    | 'awaiting_approval'
    | 'approved'
    | 'building'
    | 'built'
    | 'needs_revision'
    | 'completed'
    | 'rejected'
    | 'cancelled'
    | 'failed';

export type ApprovalState = 'pending' | 'approved' | 'rejected' | 'superseded';
export type BuildStatus = 'not_built' | 'building' | 'built' | 'failed';
export type RevisionOrigin = 'model' | 'repair' | 'revision' | 'retune';

/**
 * What arithmetic could settle about the geometry before the kernel ran.
 *
 * `blocking` means the part cannot be built as dimensioned — two holes that
 * overlap, a length that resolves to zero. `warning` is a manufacturing rule of
 * thumb, which a person may well overrule. The distinction is the server's and
 * the UI must not blur it.
 */
export interface MechanicalFinding {
    rule: string;
    severity: 'blocking' | 'warning' | 'note';
    message: string;
    feature: string;
    values: Record<string, number | string>;
}

export interface MechanicalReview {
    findings?: MechanicalFinding[];
    blocking?: number;
    warnings?: number;
    error?: string;
}

/** One frozen Blueprint, its verdict from a person, and what it built. */
export interface RevisionView {
    number: number;
    parent_number: number | null;
    origin: RevisionOrigin | null;
    instruction: string | null;
    blueprint_hash: string | null;
    part_class: string | null;
    variables: Record<string, number>;
    design_plan: Record<string, unknown>;
    critique: StudioCritique;
    /** The deterministic engineering review of the resolved geometry. */
    mechanical: MechanicalReview;
    approval: ApprovalState | null;
    decision_note: string | null;
    build_status: BuildStatus | null;
    request_id: string | null;
    verification: VerificationReport | Record<string, never>;
    stats: StudioStats | null;
    artifacts: StudioFiles;
    build_error: string | null;
    created_at: string | null;
    /** Only on the open revision — the history listing omits them for size. */
    blueprint?: Record<string, unknown> | null;
    assertions?: Record<string, unknown>[];
    thinking?: string;
    model?: string;
}

export interface SessionView {
    id: string;
    state: SessionState;
    prompt: string;
    part_class: string | null;
    /** What the request did not say. Non-empty only in the `questions` state. */
    open_questions: string[];
    reasoning: Record<string, unknown> | null;
    model: string | null;
    error: string | null;
    current_revision: number;
    revision: RevisionView | null;
    history: RevisionView[];
    created_at: string | null;
    updated_at: string | null;
    accepted_at: string | null;
}

export interface SessionSummary {
    id: string;
    state: SessionState;
    prompt: string;
    part_class: string | null;
    current_revision: number;
    created_at: string | null;
    updated_at: string | null;
}

export interface SessionEvent {
    seq: number;
    type: string;
    revision: number | null;
    data: Record<string, any>;
    at?: string | null;
}

/** A refusal the server gave a name to, so the UI can act on it. */
export interface SessionRefusal extends Error {
    status: number;
    reason: string;
    detail: Record<string, any>;
}

function refusal(message: string, status: number, detail: Record<string, any>) {
    const err = new Error(message) as SessionRefusal;
    err.status = status;
    err.reason = String(detail?.reason ?? 'error');
    err.detail = detail ?? {};
    return err;
}

/**
 * A session call, with the server's `reason` preserved.
 *
 * `requestJson` flattens everything to a message, which is right for most of
 * the API but loses exactly what this workflow needs: "you may not build this
 * yet" and "the revision you are looking at moved" are both refusals and the
 * UI has to tell them apart.
 */
async function call<T>(path: string, what: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    if (init.body && !headers.has('Content-Type')) {
        headers.set('Content-Type', 'application/json');
    }
    const res = await authedFetch(path, { ...init, headers });
    if (res.ok) return (await res.json()) as T;

    let detail: Record<string, any> = {};
    try {
        const body = await res.json();
        // The global handler wraps HTTPException details as {error: {...}}; the
        // session routes raise a dict, so it can arrive either way.
        detail = body?.detail ?? body?.error ?? body ?? {};
        if (typeof detail === 'string') detail = { error: detail };
    } catch {
        /* a body that is not JSON tells us nothing */
    }
    throw refusal(detail.error || detail.message || `${what} failed`, res.status, detail);
}

export function createSession(prompt: string): Promise<SessionView> {
    return call(ROOT, 'Starting the design', {
        method: 'POST',
        body: JSON.stringify({ prompt }),
    });
}

export function getSession(id: string): Promise<SessionView> {
    return call(`${ROOT}/${id}`, 'Loading the design');
}

export function listSessions(limit = 50): Promise<{ items: SessionSummary[] }> {
    return requestJson(`${ROOT}?limit=${limit}`, 'Loading your designs');
}

export function approveRevision(
    id: string,
    revision: number,
    note = '',
): Promise<SessionView> {
    return call(`${ROOT}/${id}/approve`, 'Approving the plan', {
        method: 'POST',
        body: JSON.stringify({ revision, note }),
    });
}

export function rejectRevision(
    id: string,
    revision: number,
    note: string,
): Promise<SessionView> {
    return call(`${ROOT}/${id}/reject`, 'Rejecting the plan', {
        method: 'POST',
        body: JSON.stringify({ revision, note }),
    });
}

export function reviseSession(id: string, instruction: string): Promise<SessionView> {
    return call(`${ROOT}/${id}/revise`, 'Revising the design', {
        method: 'POST',
        body: JSON.stringify({ instruction }),
    });
}

export function buildSession(id: string, force = false): Promise<SessionView> {
    return call(`${ROOT}/${id}/build${force ? '?force=true' : ''}`, 'Building the part', {
        method: 'POST',
    });
}

export function acceptSession(id: string): Promise<SessionView> {
    return call(`${ROOT}/${id}/accept`, 'Accepting the part', { method: 'POST' });
}

export function cancelSession(id: string): Promise<SessionView> {
    return call(`${ROOT}/${id}/cancel`, 'Cancelling the design', { method: 'POST' });
}

/**
 * Follow a session's event log from `after`, calling `onEvent` in order.
 *
 * Resolves when the stream ends — which the server does deliberately once the
 * session reaches a state where nothing further can happen without another
 * request. That is not a failure and the caller should not treat it as one: it
 * is the server declining to hold a connection open while a person reads.
 *
 * Returns the last cursor seen, so the caller can resume exactly where it
 * stopped.
 */
export async function followSession(
    id: string,
    after: number,
    onEvent: (e: SessionEvent) => void,
    signal?: AbortSignal,
): Promise<number> {
    let cursor = after;

    const res = await authedFetch(`${ROOT}/${id}/events?after=${after}`, { signal });
    if (!res.ok || !res.body) return cursor;

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const frames = buffer.split('\n\n');
        buffer = frames.pop() ?? '';

        for (const frame of frames) {
            let name = '';
            let data = '';
            for (const line of frame.split('\n')) {
                if (line.startsWith('event:')) name = line.slice(6).trim();
                else if (line.startsWith('data:')) data += line.slice(5).trim();
            }
            if (!name || !data) continue;
            try {
                const parsed = JSON.parse(data) as SessionEvent;
                // `idle` is the server saying "nothing more without another
                // request". It carries no history, so it must not advance the
                // cursor — doing so would skip the next real event.
                if (name !== 'idle' && typeof parsed.seq === 'number') {
                    cursor = parsed.seq;
                }
                onEvent({ ...parsed, type: name });
            } catch {
                continue;
            }
        }
    }
    return cursor;
}

export { API_BASE };
