/**
 * Early-access intake.
 *
 * Deliberately a plain `fetch` rather than `authedFetch`: this runs before
 * anyone has an account, so a 401 here must not kick off a refresh-and-retry
 * cycle against a token that does not exist.
 *
 * Typeform was the other candidate for this and was measured rather than
 * assumed. Its free plan is capped at ten responses a month — a hard ceiling,
 * after which the form stops collecting — and carries no integrations or
 * webhooks, so the answers could not have reached anything we own. For a form
 * whose entire purpose is knowing who is trying the product, a cap of ten and
 * no way out of the vendor is not a smaller version of the job; it is a
 * different one. This posts to our own endpoint instead, which has no cap, no
 * third party in the path between the landing page and the studio, and keeps
 * the data where the rest of the account data already is.
 */

import { API_BASE } from './http';

export interface IntakeRequest {
    name: string;
    company: string;
    email: string;
    /** Which door they came through. */
    source?: string;
    /** Honeypot. Hidden on the real form; any value means a bot. */
    website?: string;
}

/**
 * Record an early-access signup.
 *
 * Resolves on success and throws with a readable message otherwise. The caller
 * decides whether a failure should stop the journey — it should not: someone
 * who wants to try the product must not be held at a form because our lead
 * capture had a bad minute.
 */
export async function joinEarlyAccess(body: IntakeRequest): Promise<void> {
    const res = await fetch(`${API_BASE}/api/v1/waitlist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            name: body.name.trim(),
            company: body.company.trim(),
            email: body.email.trim().toLowerCase(),
            source: body.source ?? 'try',
            website: body.website || undefined,
        }),
    });

    if (res.ok) return;

    if (res.status === 429) {
        throw new Error('Too many attempts from this network. Try again in a minute.');
    }
    if (res.status === 422) {
        throw new Error('That email address does not look right — check it and try again.');
    }
    throw new Error('We could not reach the server. Check your connection and try again.');
}
