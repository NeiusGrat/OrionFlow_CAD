/**
 * Shared visual constants for the engineering panels.
 *
 * Separate from `ui.tsx` because a module that exports both components and
 * plain values breaks React Fast Refresh — the whole file stops hot-reloading,
 * which is exactly the kind of small friction that makes UI work slow.
 */

export const MONO = "'IBM Plex Mono', ui-monospace, SFMono-Regular, monospace";

/** The small-caps label used on every field, section header and table column. */
export const LABEL: React.CSSProperties = {
    fontSize: 10,
    letterSpacing: '0.09em',
    textTransform: 'uppercase',
    color: 'var(--studio-text-dim, #8a8f98)',
    fontWeight: 600,
};

export type Tone = 'neutral' | 'ok' | 'warn' | 'danger' | 'info';

export const TONES: Record<Tone, { fg: string; bg: string; border: string }> = {
    neutral: { fg: '#9aa1ad', bg: 'rgba(154,161,173,0.10)', border: 'rgba(154,161,173,0.30)' },
    ok: { fg: '#6E9E6E', bg: 'rgba(110,158,110,0.12)', border: 'rgba(110,158,110,0.35)' },
    warn: { fg: '#C39B4E', bg: 'rgba(195,155,78,0.12)', border: 'rgba(195,155,78,0.35)' },
    danger: { fg: '#C0705F', bg: 'rgba(192,112,95,0.12)', border: 'rgba(192,112,95,0.35)' },
    info: { fg: '#7C97D6', bg: 'rgba(124,151,214,0.12)', border: 'rgba(124,151,214,0.35)' },
};
