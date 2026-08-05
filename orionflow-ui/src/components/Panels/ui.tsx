/**
 * The small set of primitives the engineering panels are built from.
 *
 * Extracted rather than inlined because the panel's credibility comes from
 * repetition: a badge that means "verified" must look identical everywhere it
 * appears, and a table of dimensions must align with a table of dependencies.
 * Six components used consistently read as commercial software; sixty ad-hoc
 * divs read as a prototype, however carefully each one is styled.
 *
 * Everything here is presentational and stateless. No store access, no fetches.
 */

import { useState, type ReactNode } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { LABEL, MONO, TONES, type Tone } from './panelTokens';

export function Badge({
    tone = 'neutral',
    children,
    title,
}: {
    tone?: Tone;
    children: ReactNode;
    title?: string;
}) {
    const t = TONES[tone];
    return (
        <span
            title={title}
            style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                fontSize: 10,
                fontWeight: 600,
                letterSpacing: '0.04em',
                textTransform: 'uppercase',
                padding: '2px 7px',
                borderRadius: 4,
                color: t.fg,
                background: t.bg,
                border: `1px solid ${t.border}`,
                whiteSpace: 'nowrap',
            }}
        >
            {children}
        </span>
    );
}

export function Card({
    title,
    right,
    children,
    dense,
}: {
    title?: string;
    right?: ReactNode;
    children: ReactNode;
    dense?: boolean;
}) {
    return (
        <section
            style={{
                border: '1px solid var(--studio-border, #2a2e35)',
                borderRadius: 8,
                background: 'var(--studio-panel-2, rgba(255,255,255,0.02))',
                overflow: 'hidden',
            }}
        >
            {title && (
                <header
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                        padding: '8px 10px',
                        borderBottom: '1px solid var(--studio-border, #2a2e35)',
                    }}
                >
                    <span style={LABEL}>{title}</span>
                    <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>{right}</span>
                </header>
            )}
            <div style={{ padding: dense ? '6px 10px' : '10px' }}>{children}</div>
        </section>
    );
}

export function Collapsible({
    title,
    right,
    defaultOpen = false,
    children,
}: {
    title: string;
    right?: ReactNode;
    defaultOpen?: boolean;
    children: ReactNode;
}) {
    const [open, setOpen] = useState(defaultOpen);
    return (
        <section
            style={{
                border: '1px solid var(--studio-border, #2a2e35)',
                borderRadius: 8,
                background: 'var(--studio-panel-2, rgba(255,255,255,0.02))',
                overflow: 'hidden',
            }}
        >
            <button
                onClick={() => setOpen((v) => !v)}
                aria-expanded={open}
                style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    width: '100%',
                    padding: '8px 10px',
                    background: 'transparent',
                    border: 'none',
                    cursor: 'pointer',
                    color: 'inherit',
                    font: 'inherit',
                    textAlign: 'left',
                }}
            >
                {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                <span style={LABEL}>{title}</span>
                <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>{right}</span>
            </button>
            {open && (
                <div
                    style={{
                        padding: '4px 10px 10px',
                        borderTop: '1px solid var(--studio-border, #2a2e35)',
                    }}
                >
                    {children}
                </div>
            )}
        </section>
    );
}

/** A two-column property list. The workhorse of every engineering panel. */
export function Rows({ children }: { children: ReactNode }) {
    return <div style={{ display: 'grid', gap: 2 }}>{children}</div>;
}

export function Row({
    label,
    children,
    title,
}: {
    label: string;
    children: ReactNode;
    title?: string;
}) {
    return (
        <div
            title={title}
            style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'baseline',
                gap: 10,
                padding: '2px 0',
                minWidth: 0,
            }}
        >
            <span style={{ ...LABEL, flexShrink: 0 }}>{label}</span>
            <span
                style={{
                    fontFamily: MONO,
                    fontSize: 11,
                    textAlign: 'right',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                }}
            >
                {children}
            </span>
        </div>
    );
}

/** A real table, for anything with more than two columns. */
export function Table({
    head,
    children,
    empty,
}: {
    head: string[];
    children: ReactNode;
    empty?: string;
}) {
    const hasRows = Array.isArray(children) ? children.length > 0 : Boolean(children);
    if (!hasRows && empty) {
        return (
            <p style={{ fontSize: 11, color: 'var(--studio-text-dim)', margin: '4px 0' }}>
                {empty}
            </p>
        );
    }
    return (
        <div style={{ overflowX: 'auto' }}>
            <table
                style={{
                    width: '100%',
                    borderCollapse: 'collapse',
                    fontSize: 11,
                    fontFamily: MONO,
                }}
            >
                <thead>
                    <tr>
                        {head.map((h) => (
                            <th
                                key={h}
                                style={{
                                    ...LABEL,
                                    textAlign: 'left',
                                    padding: '3px 6px 5px 0',
                                    borderBottom: '1px solid var(--studio-border, #2a2e35)',
                                    fontFamily: 'inherit',
                                }}
                            >
                                {h}
                            </th>
                        ))}
                    </tr>
                </thead>
                <tbody>{children}</tbody>
            </table>
        </div>
    );
}

export function Cell({
    children,
    dim,
    align = 'left',
}: {
    children: ReactNode;
    dim?: boolean;
    align?: 'left' | 'right';
}) {
    return (
        <td
            style={{
                padding: '4px 6px 4px 0',
                textAlign: align,
                color: dim ? 'var(--studio-text-dim)' : 'inherit',
                borderBottom: '1px solid rgba(128,128,128,0.10)',
                whiteSpace: 'nowrap',
            }}
        >
            {children}
        </td>
    );
}

export function Button({
    children,
    onClick,
    disabled,
    tone = 'neutral',
    busy,
    full,
}: {
    children: ReactNode;
    onClick?: () => void;
    disabled?: boolean;
    tone?: 'neutral' | 'primary' | 'danger';
    busy?: boolean;
    full?: boolean;
}) {
    const primary = tone === 'primary';
    const off = disabled || busy;
    return (
        <button
            onClick={onClick}
            disabled={off}
            style={{
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 6,
                width: full ? '100%' : undefined,
                padding: '8px 12px',
                borderRadius: 6,
                fontSize: 12,
                fontWeight: 600,
                fontFamily: 'inherit',
                cursor: off ? 'default' : 'pointer',
                border: `1px solid ${
                    tone === 'danger'
                        ? TONES.danger.border
                        : primary
                          ? 'var(--studio-accent, #7C97D6)'
                          : 'var(--studio-border, #2a2e35)'
                }`,
                background:
                    primary && !off ? 'var(--studio-accent, #7C97D6)' : 'transparent',
                color: primary && !off ? '#12141a' : off ? 'var(--studio-text-dim)' : 'inherit',
                opacity: off ? 0.6 : 1,
                transition: 'background 120ms ease, opacity 120ms ease',
            }}
        >
            {busy && <Spinner />}
            {children}
        </button>
    );
}

export function Spinner({ size = 11 }: { size?: number }) {
    return (
        <span
            aria-hidden
            style={{
                width: size,
                height: size,
                border: '1.5px solid currentColor',
                borderTopColor: 'transparent',
                borderRadius: '50%',
                display: 'inline-block',
                animation: 'of-spin 700ms linear infinite',
            }}
        />
    );
}

/** A determinate bar. Used for anything with a real fraction — never as a
 *  decorative stand-in for "something is happening". */
export function Meter({ value, tone = 'ok' }: { value: number; tone?: Tone }) {
    const pct = Math.max(0, Math.min(1, value)) * 100;
    return (
        <div
            style={{
                height: 4,
                borderRadius: 2,
                background: 'rgba(128,128,128,0.18)',
                overflow: 'hidden',
            }}
        >
            <div
                style={{
                    width: `${pct}%`,
                    height: '100%',
                    background: TONES[tone].fg,
                    transition: 'width 200ms ease',
                }}
            />
        </div>
    );
}

export function Select({
    value,
    onChange,
    options,
    placeholder,
    disabled,
}: {
    value: string | null;
    onChange: (v: string | null) => void;
    options: { value: string; label: string; disabled?: boolean }[];
    placeholder?: string;
    disabled?: boolean;
}) {
    return (
        <select
            value={value ?? ''}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value || null)}
            style={{
                width: '100%',
                padding: '7px 8px',
                borderRadius: 6,
                fontSize: 12,
                fontFamily: 'inherit',
                background: 'var(--studio-panel-2, rgba(255,255,255,0.03))',
                border: '1px solid var(--studio-border, #2a2e35)',
                color: 'inherit',
                cursor: disabled ? 'default' : 'pointer',
            }}
        >
            {placeholder && <option value="">{placeholder}</option>}
            {options.map((o) => (
                <option key={o.value} value={o.value} disabled={o.disabled}>
                    {o.label}
                </option>
            ))}
        </select>
    );
}

export function NumberField({
    value,
    onChange,
    unit,
    min,
    max,
    step,
    disabled,
}: {
    value: number;
    onChange: (v: number) => void;
    unit?: string;
    min?: number;
    max?: number;
    step?: number;
    disabled?: boolean;
}) {
    return (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <input
                type="number"
                value={Number.isFinite(value) ? value : ''}
                min={min}
                max={max}
                step={step ?? 0.1}
                disabled={disabled}
                onChange={(e) => {
                    const n = Number(e.target.value);
                    if (Number.isFinite(n)) onChange(n);
                }}
                style={{
                    width: '100%',
                    padding: '6px 8px',
                    borderRadius: 6,
                    fontFamily: MONO,
                    fontSize: 12,
                    background: 'var(--studio-panel-2, rgba(255,255,255,0.03))',
                    border: '1px solid var(--studio-border, #2a2e35)',
                    color: 'inherit',
                }}
            />
            {unit && (
                <span style={{ ...LABEL, flexShrink: 0, textTransform: 'none' }}>{unit}</span>
            )}
        </div>
    );
}

export function Empty({ icon, children }: { icon?: ReactNode; children: ReactNode }) {
    return (
        <div
            style={{
                padding: '28px 18px',
                textAlign: 'center',
                color: 'var(--studio-text-dim)',
            }}
        >
            {icon && <div style={{ marginBottom: 10, opacity: 0.7 }}>{icon}</div>}
            <p style={{ fontSize: 12, lineHeight: 1.6, margin: 0 }}>{children}</p>
        </div>
    );
}

/** One keyframe set, injected once, so Spinner works without a global stylesheet. */
export function PanelKeyframes() {
    return <style>{`@keyframes of-spin { to { transform: rotate(360deg); } }`}</style>;
}
