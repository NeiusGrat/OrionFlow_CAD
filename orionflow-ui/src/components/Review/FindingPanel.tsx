/**
 * One finding, in full: what was measured against what was expected, the
 * evidence (each chip jumps to the geometry), where the claim came from, the
 * recommendation, and the engineer's decision with its history.
 *
 * Rejecting needs a reason — the server enforces it, the form asks for it.
 */
import { useEffect, useState } from 'react';
import {
    commentFinding, getFinding, patchFinding,
    type Evidence, type Finding, type FindingEvent, type FindingStatus, type ModelGraph, type Quantity,
} from '../../services/reviewApi';
import { useReview } from '../../store/reviewStore';

const PROV: Record<string, string> = {
    geometry: 'Measured from B-rep geometry',
    rule: 'Derived by a rule from the model graph',
    ai_reading: 'Read by AI from a document — verify',
    ai_inference: 'Inferred by AI — verify',
};

export function SevMark({ s, label = true }: { s: string; label?: boolean }) {
    return <span className={`sev sev--${s}`}>{label ? s : ''}</span>;
}

function q(v: Quantity | null): string {
    if (!v) return '—';
    if (v.value !== undefined && v.value !== null) return `${fmt(v.value)}${v.unit ? ` ${v.unit}` : ''}${v.text ? ` (${v.text})` : ''}`;
    const parts = [];
    if (v.min !== undefined && v.min !== null) parts.push(`≥ ${fmt(v.min)}`);
    if (v.max !== undefined && v.max !== null) parts.push(`≤ ${fmt(v.max)}`);
    if (parts.length) return `${parts.join(' and ')}${v.unit ? ` ${v.unit}` : ''}`;
    return v.text ?? '—';
}

function fmt(n: number): string {
    if (Math.abs(n) >= 1000 || Number.isInteger(n)) return n.toLocaleString('en-US', { maximumFractionDigits: 3 });
    return n.toPrecision(4).replace(/\.?0+$/, '');
}

/** Grey band = expected range, black tick = measured. Only when both are numeric on one scale. */
function Compare({ m, e }: { m: Quantity | null; e: Quantity | null }) {
    if (!m || m.value === undefined || m.value === null || !e) return null;
    const lo = e.min ?? e.value ?? null;
    const hi = e.max ?? e.value ?? null;
    if (lo === null && hi === null) return null;
    const vals = [m.value, lo ?? m.value, hi ?? m.value];
    let a = Math.min(...vals);
    let b = Math.max(...vals);
    const pad = (b - a || Math.abs(b) || 1) * 0.25;
    a -= pad;
    b += pad;
    const x = (v: number) => `${((v - a) / (b - a)) * 100}%`;
    return (
        <div style={{ position: 'relative', height: 22, margin: '10px 0 2px' }} aria-hidden="true">
            <div style={{ position: 'absolute', top: 9, left: 0, right: 0, height: 1, background: 'var(--line-2)' }} />
            <div style={{
                position: 'absolute', top: 5, height: 9, background: 'var(--line-2)',
                left: lo !== null ? x(lo) : '0%', right: hi !== null ? `calc(100% - ${x(hi)})` : '0%',
            }} />
            <div style={{ position: 'absolute', top: 1, width: 2, height: 17, background: 'var(--text)', left: `calc(${x(m.value)} - 1px)` }} />
        </div>
    );
}

export function EvidenceChips({ evidence, graph, onJump }: { evidence: Evidence[]; graph: ModelGraph; onJump: () => void }) {
    const select = useReview((s) => s.select);
    const label = (e: Evidence) => {
        if (e.label) return e.label;
        if (e.type === 'instance') return graph.instances.find((i) => i.id === e.id)?.name ?? e.id;
        if (e.type === 'part') return graph.parts.find((p) => p.id === e.id)?.name ?? e.id;
        return e.id ?? e.type;
    };
    const jump = (e: Evidence) => {
        if (!e.id) return;
        if (e.type === 'instance' || e.type === 'part' || e.type === 'contact') {
            select({ kind: e.type, id: e.id }, true);
            onJump();
        } else if (e.type === 'feature') {
            const pid = e.id.split('.')[0];
            select({ kind: 'part', id: pid }, true);
            onJump();
        }
    };
    return (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {evidence.map((e, k) => {
                const clickable = !!e.id && ['instance', 'part', 'contact', 'feature'].includes(e.type);
                return (
                    <button key={k} className="btn" style={{ height: 'auto', minHeight: 24, padding: '2px 8px', whiteSpace: 'normal', textAlign: 'left' }}
                        disabled={!clickable} onClick={() => jump(e)} title={e.sha256 ? `SHA-256 ${e.sha256}` : `${e.type} ${e.id ?? ''}`}>
                        <span className="mono muted" style={{ fontSize: 10, textTransform: 'uppercase', marginRight: 4 }}>{e.type}</span>
                        {label(e)}
                    </button>
                );
            })}
        </div>
    );
}

const ACTIONS: { to: FindingStatus; label: string }[] = [
    { to: 'accepted', label: 'Accept' },
    { to: 'rejected', label: 'Reject' },
    { to: 'fixed', label: 'Mark fixed' },
    { to: 'deferred', label: 'Defer' },
];

export default function FindingPanel({ finding, graph, onChanged, onJump }: {
    finding: Finding;
    graph: ModelGraph;
    onChanged: (f: Finding) => void;
    onJump: () => void;
}) {
    const [events, setEvents] = useState<FindingEvent[]>([]);
    const [reason, setReason] = useState('');
    const [rejecting, setRejecting] = useState(false);
    const [comment, setComment] = useState('');
    const [owner, setOwner] = useState(finding.owner ?? '');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');

    useEffect(() => {
        let alive = true;
        setRejecting(false);
        setReason('');
        setOwner(finding.owner ?? '');
        getFinding(finding.id).then((f) => alive && setEvents(f.events)).catch(() => {});
        return () => {
            alive = false;
        };
    }, [finding.id, finding.owner, finding.updated_at]);

    const run = async (fn: () => Promise<Finding & { events: FindingEvent[] }>) => {
        setBusy(true);
        setError('');
        try {
            const f = await fn();
            setEvents(f.events);
            onChanged(f);
        } catch (e) {
            setError(String((e as Error).message));
        } finally {
            setBusy(false);
        }
    };

    const setStatus = (to: FindingStatus) => {
        if (to === 'rejected') {
            setRejecting(true);
            return;
        }
        run(() => patchFinding(finding.id, { status: to }));
    };

    // keyboard: A accept, R reject (the list handles J/K)
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            const t = e.target as HTMLElement;
            if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT')) return;
            if (e.metaKey || e.ctrlKey || e.altKey) return;
            if (e.key.toLowerCase() === 'a') { e.preventDefault(); run(() => patchFinding(finding.id, { status: 'accepted' })); }
            if (e.key.toLowerCase() === 'r') { e.preventDefault(); setRejecting(true); }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [finding.id]);

    const ai = finding.provenance === 'ai_reading' || finding.provenance === 'ai_inference';

    return (
        <aside className="rv-inspector" aria-label="Finding">
            <div className="rv-panel-head">
                <SevMark s={finding.severity} />
                <span className="mono muted" style={{ marginLeft: 'auto', fontSize: 11 }}>{finding.status}{finding.active ? '' : ' · no longer detected'}</span>
            </div>
            <div className="rv-sec">
                <h3 style={{ fontSize: 15, fontWeight: 500, lineHeight: 1.3 }}>{finding.title}</h3>
                <p style={{ margin: '6px 0 0', color: 'var(--text)' }}>{finding.statement}</p>
                {ai && <p className="rv-err" style={{ marginTop: 8 }}>AI-derived — verify before acting on it.</p>}
            </div>
            <div className="rv-sec">
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                    <div>
                        <div className="label">Measured</div>
                        <div className="mono" style={{ fontSize: 15, marginTop: 4 }}>{q(finding.measured)}</div>
                    </div>
                    <div>
                        <div className="label">Expected</div>
                        <div className="mono" style={{ fontSize: 15, marginTop: 4 }}>{q(finding.expected)}</div>
                    </div>
                </div>
                <Compare m={finding.measured} e={finding.expected} />
                {finding.expected?.basis && <div className="mono muted" style={{ fontSize: 11, marginTop: 4 }}>basis: {finding.expected.basis}</div>}
            </div>
            <div className="rv-sec">
                <h3>Evidence</h3>
                <EvidenceChips evidence={finding.evidence} graph={graph} onJump={onJump} />
            </div>
            {finding.recommendation && (
                <div className="rv-sec">
                    <h3>Recommendation</h3>
                    <p style={{ margin: 0 }}>{finding.recommendation}</p>
                </div>
            )}
            <div className="rv-sec">
                <h3>Decision</h3>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {ACTIONS.map((a) => (
                        <button key={a.to} className={`btn${finding.status === a.to ? ' btn--solid' : ''}`} disabled={busy}
                            onClick={() => setStatus(a.to)} title={a.to === 'accepted' ? 'A' : a.to === 'rejected' ? 'R' : undefined}>
                            {a.label}
                        </button>
                    ))}
                    {finding.status !== 'open' && <button className="btn btn--ghost" disabled={busy} onClick={() => setStatus('open')}>Reopen</button>}
                </div>
                {rejecting && (
                    <form style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}
                        onSubmit={(e) => {
                            e.preventDefault();
                            if (!reason.trim()) return;
                            run(() => patchFinding(finding.id, { status: 'rejected', note: reason.trim() })).then(() => setRejecting(false));
                        }}>
                        <textarea autoFocus value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why is this not a problem? (required)"
                            rows={3} style={{ border: '1px solid var(--line-2)', borderRadius: 2, padding: 8, resize: 'vertical' }} />
                        <div style={{ display: 'flex', gap: 4 }}>
                            <button className="btn btn--solid" disabled={!reason.trim() || busy}>Reject with reason</button>
                            <button type="button" className="btn btn--ghost" onClick={() => setRejecting(false)}>Cancel</button>
                        </div>
                    </form>
                )}
                <form style={{ display: 'flex', gap: 4, marginTop: 10 }}
                    onSubmit={(e) => {
                        e.preventDefault();
                        run(() => patchFinding(finding.id, owner.trim() ? { owner: owner.trim() } : { clear_owner: true }));
                    }}>
                    <input value={owner} onChange={(e) => setOwner(e.target.value)} placeholder="Owner" aria-label="Owner"
                        style={{ flex: 1, height: 28, border: '1px solid var(--line-2)', borderRadius: 2, padding: '0 8px' }} />
                    <button className="btn" disabled={busy || owner.trim() === (finding.owner ?? '')}>Set owner</button>
                </form>
                {error && <p className="rv-err">{error}</p>}
            </div>
            <div className="rv-sec">
                <h3>Discussion &amp; history</h3>
                <ol style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                    {events.map((ev) => (
                        <li key={ev.id} style={{ padding: '6px 0', borderBottom: '1px solid var(--line)' }}>
                            <div className="mono muted" style={{ fontSize: 10.5 }}>
                                {ev.created_at ? new Date(ev.created_at).toLocaleString() : ''} · {ev.user_id}
                            </div>
                            <div style={{ fontSize: 12.5 }}>
                                {ev.action === 'status' && <>status <b>{ev.from_status}</b> → <b>{ev.to_status}</b></>}
                                {ev.action === 'detected' && <>detected</>}
                                {ev.action === 'redetected' && <>detected again — reopened</>}
                                {ev.action === 'resolved' && <>no longer detected → <b>{ev.to_status}</b></>}
                                {ev.action === 'owner' && <>owner {ev.note ? <b>{ev.note}</b> : 'cleared'}</>}
                                {ev.action === 'comment' && null}
                                {ev.note && ev.action !== 'owner' && <div style={{ marginTop: 2 }}>{ev.note}</div>}
                            </div>
                        </li>
                    ))}
                </ol>
                <form style={{ display: 'flex', gap: 4, marginTop: 8 }}
                    onSubmit={(e) => {
                        e.preventDefault();
                        if (!comment.trim()) return;
                        run(() => commentFinding(finding.id, comment.trim())).then(() => setComment(''));
                    }}>
                    <input value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Add a comment" aria-label="Comment"
                        style={{ flex: 1, height: 28, border: '1px solid var(--line-2)', borderRadius: 2, padding: '0 8px' }} />
                    <button className="btn" disabled={!comment.trim() || busy}>Post</button>
                </form>
            </div>
            <div className="rv-sec">
                <dl className="rv-kv">
                    <dt>Check</dt><dd>{finding.check_id} v{finding.check_version}</dd>
                    <dt>Source</dt><dd style={{ fontFamily: 'var(--sans)' }}>{PROV[finding.provenance]}</dd>
                    <dt>Fingerprint</dt><dd>{finding.fingerprint}</dd>
                </dl>
            </div>
        </aside>
    );
}
