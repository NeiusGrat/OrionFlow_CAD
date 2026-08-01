/**
 * Plan and usage — what the account menu reports.
 *
 * Every number here comes off the billing tables. Nothing is estimated: if the
 * server cannot say what plan someone is on, the menu says the plan is unknown
 * rather than guessing "Free", because a user on a paid plan being told they
 * are on the free one is a support ticket.
 */

import { requestJson } from './http';

export interface Plan {
    id: string;
    name: string;
    display_name: string;
    description: string | null;
    price_monthly: number;
    price_yearly: number;
    generations_per_month: number;
    max_designs: number;
}

export interface Subscription {
    id: string;
    plan: Plan;
    status: string;
    current_period_start: string;
    current_period_end: string;
    generations_used: number;
    cancel_at_period_end: boolean;
}

export interface UsageLimit {
    allowed: boolean;
    reason: string | null;
    message: string | null;
    used: number;
    limit: number;
    remaining: number;
}

/**
 * The month's allowance and how much of it is gone.
 *
 * `/billing/usage/check` is the one endpoint that reports the limit and the
 * consumption together, from the same query the generation gate uses — so what
 * the menu shows and what actually refuses a build can never disagree.
 */
export async function fetchUsage(): Promise<UsageLimit | null> {
    try {
        return await requestJson<UsageLimit>('/api/v1/billing/usage/check', 'Loading usage');
    } catch {
        return null;
    }
}

/** Null for a user with no subscription row — which is the free tier. */
export async function fetchSubscription(): Promise<Subscription | null> {
    try {
        return await requestJson<Subscription>(
            '/api/v1/billing/subscription',
            'Loading your plan',
        );
    } catch {
        return null;
    }
}
