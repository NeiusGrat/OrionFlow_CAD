/**
 * The authenticated fetch every API client goes through.
 *
 * Access tokens live 15 minutes (`jwt_access_token_expire_minutes`). Nothing
 * was refreshing them, so a studio left open for a quarter of an hour started
 * 401-ing on every call — which is what made Save look broken and produced
 * "Loading designs failed:" with nothing after the colon. Two bugs, one
 * symptom:
 *
 *   1. Nobody called POST /auth/refresh, even though the refresh token was
 *      sitting in the persisted store and is good for seven days.
 *   2. The error text was read from `body.detail`, but this API's global
 *      handler emits `{error: {code, message}}` — so `detail` was undefined
 *      and the reason vanished, leaving a bare "failed:".
 *
 * Refresh is single-flight: a page that fires several requests at once must
 * not spend the refresh token several times, because each refresh issues a new
 * pair and the losers of that race would be retried with a token that has
 * already been rotated away.
 */

import { useAuthStore } from '../store/authStore';

export const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

/** In-flight refresh, shared by every caller that 401s while it runs. */
let refreshing: Promise<string | null> | null = null;

function accessToken(): string | null {
    return useAuthStore.getState().accessToken;
}

async function refreshAccessToken(): Promise<string | null> {
    if (!refreshing) {
        refreshing = useAuthStore
            .getState()
            .refresh()
            .finally(() => {
                refreshing = null;
            });
    }
    return refreshing;
}

export interface ApiFailure extends Error {
    status: number;
    /** True once the session is gone for good and the user must sign in. */
    unauthenticated: boolean;
}

function failure(message: string, status: number): ApiFailure {
    const err = new Error(message) as ApiFailure;
    err.status = status;
    err.unauthenticated = status === 401;
    return err;
}

/**
 * Every error shape this API can produce, in the order they are worth trying.
 *
 * `{error: {message}}` is the global handler's envelope and covers most of
 * them; FastAPI's own `detail` still comes through for validation errors, and
 * a 422 arrives as a list of field problems rather than a sentence.
 */
export async function readError(res: Response, what: string): Promise<string> {
    let reason = '';
    try {
        const body = await res.json();
        if (typeof body?.error?.message === 'string' && body.error.message) {
            reason = body.error.message;
        } else if (typeof body?.detail === 'string') {
            reason = body.detail;
        } else if (typeof body?.detail?.error === 'string') {
            reason = body.detail.error;
        } else if (Array.isArray(body?.detail) && body.detail.length) {
            // Pydantic: name the field that was rejected, not just "invalid".
            const first = body.detail[0];
            const field = Array.isArray(first?.loc) ? first.loc.slice(-1)[0] : '';
            reason = field ? `${field}: ${first?.msg ?? 'invalid'}` : (first?.msg ?? '');
        }
    } catch {
        /* not JSON — fall through to the status */
    }
    if (!reason) {
        // HTTP/2 drops the reason phrase, so statusText is empty in production
        // and only the code is left. Better than a sentence ending in a colon.
        reason = res.statusText || `HTTP ${res.status}`;
    }
    return `${what} failed: ${reason}`;
}

/**
 * Fetch with the bearer token attached, retried once through a token refresh.
 *
 * Returns the raw Response so streaming callers (the studio's SSE turn) can
 * read the body themselves. Throws only for a session that cannot be revived.
 */
export async function authedFetch(
    path: string,
    init: RequestInit = {},
): Promise<Response> {
    const url = path.startsWith('http') ? path : `${API_BASE}${path}`;

    const send = (token: string | null) => {
        const headers = new Headers(init.headers);
        if (token) headers.set('Authorization', `Bearer ${token}`);
        return fetch(url, { ...init, headers });
    };

    let res = await send(accessToken());
    if (res.status !== 401) return res;

    // The body of a 401 is never useful and holding it open leaks the
    // connection, so it is drained before the retry.
    try {
        await res.text();
    } catch {
        /* nothing to drain */
    }

    const fresh = await refreshAccessToken();
    if (!fresh) {
        useAuthStore.getState().logout();
        throw failure('your session expired — sign in again', 401);
    }

    res = await send(fresh);
    if (res.status === 401) {
        useAuthStore.getState().logout();
        throw failure('your session expired — sign in again', 401);
    }
    return res;
}

/** JSON request → parsed body, or a thrown error that says what went wrong. */
export async function requestJson<T>(
    path: string,
    what: string,
    init: RequestInit = {},
): Promise<T> {
    const headers = new Headers(init.headers);
    if (init.body && !headers.has('Content-Type')) {
        headers.set('Content-Type', 'application/json');
    }
    const res = await authedFetch(path, { ...init, headers });
    if (!res.ok) throw failure(await readError(res, what), res.status);
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
}

/** Absolute URL for a server-relative artifact path. */
export function fullUrl(path?: string | null): string {
    if (!path) return '';
    return path.startsWith('http') ? path : `${API_BASE}${path}`;
}
