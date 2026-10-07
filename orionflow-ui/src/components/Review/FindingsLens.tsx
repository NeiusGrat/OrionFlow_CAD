/**
 * Findings workboard: every finding, grouped by domain then severity, with
 * filters for status, provenance and severity. J / K move through the list;
 * the Inspector shows the selected finding (A accepts, R rejects).
 *
 * Below the list, every check in the catalogue with what it did: passed,
 * raised findings, did not run (and why), or failed (and how).
 */
import { useEffect, useMemo, useState } from 'react';
import type { CheckRun, Finding, FindingsPayload, Provenance, Severity } from '../../services/reviewApi';
import { SEVERITIES } from '../../services/reviewApi';
import { useReview } from '../../store/reviewStore';
import { SevMark } from './FindingPanel';

const STATUSES = ['open', 'accepted', 'rejected', 'fixed', 'deferred'] as const;
const PROVS: (Provenance | 'all')[] = ['all', 'geometry', 'rule', 'ai_reading', 'ai_inference'];

function short(f: Finding): string {
    const m = f.measured;
    if (!m) return '';
    if (m.value !== undefined && m.value !== null) return `${Number(m.value.toPrecision(4))}${m.unit ? ` ${m.unit}` : ''}`;
    return m.text ?? '';
}

export function RunStatus({ r }: { r: CheckRun }) {
    const cls = r.status === 'passed' ? 'sev--pass' : r.status === 'not_run' ? 'sev--notrun' : r.status === 'error' ? 'sev--critical' : 'sev--major';
    return <span className={`sev ${cls}`}>{r.status === 'findings' ? `${r.findings} finding${r.findings === 1 ? '' : 's'}` : r.status.replace('_', ' ')}</span>;
}

export default function FindingsLens({ data, onExport, exporting }: { data: FindingsPayload; onExport: () => void; exporting: boolean }) {
    const [sev, setSev] = useState<Set<Severity>>(new Set(SEVERITIES));
    const [status, setStatus] = useState<Set<string>>(new Set(['open', 'deferred']));
    const [prov, setProv] = useState<Provenance | 'all'>('all');
    const selection = useReview((s) => s.selection);
    const select = useReview((s) => s.select);

    const shown = useMemo(
        () => data.findings.filter((f) => sev.has(f.severity) && status.has(f.status) && (prov === 'all' || f.provenance === prov)),
        [data.findings, sev, status, prov],
    );
    const groups = useMemo(() => {
        const m = new Map<string, Finding[]>();
        for (const f of shown) m.set(f.domain, [...(m.get(f.domain) ?? []), f]);
        return [...m.entries()];
    }, [shown]);
    const flat = useMemo(() => groups.flatMap(([, fs]) => fs), [groups]);

    // J / K: next / previous finding in the visible order
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            const t = e.target as HTMLElement;
            if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT')) return;
            if (e.metaKey || e.ctrlKey || e.altKey) return;
            const k = e.key.toLowerCase();
            if (k !== 'j' && k !== 'k') return;
            e.preventDefault();
            const at = flat.findIndex((f) => selection?.kind === 'finding' && f.id === selection.id);
            const next = k === 'j' ? Math.min(flat.length - 1, at + 1) : Math.max(0, at === -1 ? 0 : at - 1);
            if (flat[next]) select({ kind: 'finding', id: flat[next].id });
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [flat, selection, select]);

    useEffect(() => {
        document.querySelector('.rv-findings tr.is-sel')?.scrollIntoView({ block: 'nearest' });
    }, [selection]);

    const toggle = <T,>(set: Set<T>, v: T, apply: (s: Set<T>) => void) => {
        const n = new Set(set);
        if (n.has(v)) n.delete(v);
        else n.add(v);
        apply(n);
    };
    const count = (s: Severity) => data.findings.filter((f) => f.severity === s && status.has(f.status)).length;
    const notRun = data.check_runs.filter((r) => r.status === 'not_run');

    return (
        <div className="rv-page rv-findings" style={{ background: 'var(--bg)' }}>
            <div style={{ position: 'sticky', top: 0, zIndex: 2, background: 'var(--bg)', borderBottom: '1px solid var(--line)', padding: '10px 16px', display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
                <span className="label">Findings</span>
                <span style={{ display: 'flex', gap: 2 }}>
                    {SEVERITIES.map((s) => (
                        <button key={s} className="btn btn--ghost" aria-pressed={sev.has(s)} onClick={() => toggle(sev, s, setSev)}
                            style={sev.has(s) ? { borderColor: 'var(--text)' } : { opacity: 0.5 }}>
                            <SevMark s={s} label={false} /> {s} <span className="mono muted">{count(s)}</span>
                        </button>
                    ))}
                </span>
                <span style={{ display: 'flex', gap: 2 }}>
                    {STATUSES.map((s) => (
                        <button key={s} className="btn btn--ghost" aria-pressed={status.has(s)} onClick={() => toggle(status, s as string, setStatus)}
                            style={status.has(s) ? { borderColor: 'var(--text)' } : { opacity: 0.5 }}>{s}</button>
                    ))}
                </span>
                <select value={prov} onChange={(e) => setProv(e.target.value as Provenance | 'all')} aria-label="Provenance"
                    style={{ height: 28, border: '1px solid var(--line-2)', borderRadius: 2 }}>
                    {PROVS.map((p) => <option key={p} value={p}>{p === 'all' ? 'any source' : p.replace('_', ' ')}</option>)}
                </select>
                <button className="btn" style={{ marginLeft: 'auto' }} onClick={onExport} disabled={exporting}>{exporting ? 'Exporting…' : 'Export JSON'}</button>
            </div>

            <div style={{ padding: '0 16px 40px' }}>
                {shown.length === 0 && (
                    <div className="rv-empty" style={{ border: '1px solid var(--line)', marginTop: 16 }}>
                        <b>{data.findings.length ? 'Nothing matches these filters' : 'No findings'}</b>
                        {data.findings.length ? 'Widen the severity or status filters.' : 'Every check that ran passed. See the checks below for what did not run.'}
                    </div>
                )}
                {groups.map(([domain, fs]) => (
                    <section key={domain} style={{ marginTop: 18 }}>
                        <div className="label" style={{ marginBottom: 4 }}>{data.domains[domain] ?? domain} · {fs.length}</div>
                        <table className="rv-table">
                            <tbody>
                                {fs.map((f) => (
                                    <tr key={f.id} data-click className={selection?.kind === 'finding' && selection.id === f.id ? 'is-sel' : undefined}
                                        onClick={() => select({ kind: 'finding', id: f.id })}>
                                        <td style={{ width: 92 }}><SevMark s={f.severity} /></td>
                                        <td>
                                            {f.title}
                                            {(f.provenance === 'ai_reading' || f.provenance === 'ai_inference') && <span className="mono" style={{ marginLeft: 6, fontSize: 10, border: '1px solid currentColor', padding: '0 3px' }}>AI</span>}
                                            <div className="muted" style={{ fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 560 }}>{f.statement}</div>
                                        </td>
                                        <td className="mono muted" style={{ fontSize: 11, width: 110 }}>{f.check_id}</td>
                                        <td className="num" style={{ width: 120 }}>{short(f)}</td>
                                        <td className="mono" style={{ fontSize: 11, width: 80 }}>{f.status}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </section>
                ))}

                <section style={{ marginTop: 32 }}>
                    <div className="label" style={{ marginBottom: 4 }}>
                        Checks · {data.check_runs.filter((r) => r.status === 'passed' || r.status === 'findings').length} run · {notRun.length} not run
                    </div>
                    <table className="rv-table">
                        <thead><tr><th>Check</th><th>Domain</th><th>Result</th><th>Reason</th><th className="num">Time</th></tr></thead>
                        <tbody>
                            {data.check_runs.map((r) => (
                                <tr key={r.check_id}>
                                    <td><span className="mono" style={{ fontSize: 11.5 }}>{r.check_id}</span> <span className="muted">v{r.check_version}</span><div style={{ fontSize: 12 }}>{r.title}</div></td>
                                    <td className="muted" style={{ fontSize: 12 }}>{data.domains[r.domain] ?? r.domain}</td>
                                    <td><RunStatus r={r} /></td>
                                    <td className="muted" style={{ fontSize: 12 }}>{r.status === 'error' ? 'the check failed — reported, not hidden' : r.reason ?? ''}</td>
                                    <td className="num">{r.seconds ? `${r.seconds.toFixed(2)} s` : ''}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </section>
            </div>
        </div>
    );
}
