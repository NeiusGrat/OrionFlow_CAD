/**
 * The open design session, mirrored from the server.
 *
 * One rule governs this file: **the server owns the state and this store never
 * guesses it.** Every action replaces the whole `session` with what came back,
 * and the UI switches on `session.state`. No optimistic transitions, no
 * "probably building now" — the approval gate is enforced in backend code, and
 * a client that predicted its own state would eventually show an Approve button
 * for a design the server had already superseded.
 *
 * The event log is kept beside it for the timeline, and its cursor is what
 * makes reconnecting free: a dropped stream resumes from the last `seq` rather
 * than replaying a session from the beginning or, worse, missing the middle.
 */

import { create } from 'zustand';
import {
    acceptSession,
    approveRevision,
    buildSession,
    cancelSession,
    createSession,
    followSession,
    getSession,
    rejectRevision,
    reviseSession,
    type SessionEvent,
    type SessionRefusal,
    type SessionView,
} from '../services/sessionsApi';
import { showInViewer } from './studioStore';

/** A refusal worth showing as more than a sentence. */
export interface SessionError {
    message: string;
    reason: string;
    detail: Record<string, any>;
}

interface SessionStore {
    session: SessionView | null;
    events: SessionEvent[];
    cursor: number;
    /** Which action is in flight, so the right control shows a spinner. */
    busy: null | 'creating' | 'approving' | 'rejecting' | 'revising' | 'building' | 'accepting';
    error: SessionError | null;

    start: (prompt: string) => Promise<void>;
    open: (id: string) => Promise<void>;
    approve: (note?: string) => Promise<void>;
    reject: (note: string) => Promise<void>;
    revise: (instruction: string) => Promise<void>;
    build: (force?: boolean) => Promise<void>;
    accept: () => Promise<void>;
    cancel: () => Promise<void>;
    close: () => void;
    dismissError: () => void;
}

/** The live stream, if one is attached. Never more than one per session. */
let following: AbortController | null = null;

function asError(e: any): SessionError {
    const r = e as SessionRefusal;
    return {
        message: r?.message || 'something went wrong',
        reason: r?.reason || 'error',
        detail: r?.detail || {},
    };
}

/** States where the server will do nothing further without another request. */
const SETTLED = new Set([
    'questions',
    'awaiting_approval',
    'built',
    'needs_revision',
    'completed',
    'rejected',
    'cancelled',
    'failed',
]);

export const useSessionStore = create<SessionStore>((set, get) => {
    /** Replace the mirrored session, and push geometry to the viewer if new. */
    function adopt(session: SessionView) {
        const previous = get().session;
        set({ session, error: null });

        const rev = session.revision;
        const built = rev?.build_status === 'built' && rev.artifacts?.glb;
        const isNew =
            built &&
            (previous?.revision?.request_id !== rev?.request_id ||
                previous?.state !== session.state);
        if (built && isNew) {
            showInViewer(session.prompt, rev!.artifacts, rev!.stats);
        }
    }

    /**
     * Attach to the event log and follow until the session settles.
     *
     * Reattached after every action rather than held open across them: the
     * server closes the stream once nothing further can happen, so a stream
     * opened while awaiting approval is already finished by the time the user
     * approves.
     */
    async function follow() {
        following?.abort();
        const controller = new AbortController();
        following = controller;

        const id = get().session?.id;
        if (!id) return;

        try {
            const cursor = await followSession(
                id,
                get().cursor,
                (event) => {
                    set((s) => ({
                        events: [...s.events, event],
                        cursor: Math.max(s.cursor, event.seq || 0),
                    }));
                },
                controller.signal,
            );
            set((s) => ({ cursor: Math.max(s.cursor, cursor) }));
        } catch {
            // A stream that drops is not a failed design. The next action
            // refetches the session, which is the authoritative answer anyway.
            return;
        }
        if (controller.signal.aborted) return;

        // The stream ends when the session settles — but "settled" is the
        // server's view at the moment it stopped, so the session is refetched
        // once to be sure the store agrees with it.
        try {
            const fresh = await getSession(id);
            adopt(fresh);
            if (!SETTLED.has(fresh.state)) void follow();
        } catch {
            /* the next action will resolve it */
        }
    }

    async function act(
        busy: SessionStore['busy'],
        run: () => Promise<SessionView>,
    ): Promise<void> {
        set({ busy, error: null });
        try {
            adopt(await run());
            void follow();
        } catch (e: any) {
            set({ error: asError(e) });
        } finally {
            set({ busy: null });
        }
    }

    return {
        session: null,
        events: [],
        cursor: 0,
        busy: null,
        error: null,

        start: async (prompt: string) => {
            following?.abort();
            set({ session: null, events: [], cursor: 0 });
            await act('creating', () => createSession(prompt));
        },

        open: async (id: string) => {
            following?.abort();
            set({ events: [], cursor: 0 });
            await act(null, () => getSession(id));
        },

        approve: async (note = '') => {
            const s = get().session;
            if (!s?.revision) return;
            // The revision number is sent explicitly, never defaulted. If a
            // revision landed between the plan on screen and this click, the
            // server refuses with `stale_revision` rather than approving
            // something the user never read.
            await act('approving', () => approveRevision(s.id, s.revision!.number, note));
        },

        reject: async (note: string) => {
            const s = get().session;
            if (!s?.revision) return;
            await act('rejecting', () => rejectRevision(s.id, s.revision!.number, note));
        },

        revise: async (instruction: string) => {
            const s = get().session;
            if (!s) return;
            await act('revising', () => reviseSession(s.id, instruction));
        },

        build: async (force = false) => {
            const s = get().session;
            if (!s) return;
            await act('building', () => buildSession(s.id, force));
        },

        accept: async () => {
            const s = get().session;
            if (!s) return;
            await act('accepting', () => acceptSession(s.id));
        },

        cancel: async () => {
            const s = get().session;
            if (!s) return;
            await act(null, () => cancelSession(s.id));
        },

        close: () => {
            following?.abort();
            following = null;
            set({ session: null, events: [], cursor: 0, error: null, busy: null });
        },

        dismissError: () => set({ error: null }),
    };
});
