/**
 * Motion lens: confirm a joint, sweep it through its range on exact geometry, read the clearance curve.
 *
 * Joints come from the sim model (axis placed in the CAD frame by its registration file) or from the
 * geometry (a boss running in a bore). Nothing is swept until the engineer confirms the axis, the
 * limits (with their source), the pose the CAD is drawn at and the parts that move. The scrubber poses
 * the model in the browser from the same axis and coupling the sweep used; the numbers come from the
 * sweep, which runs on the server against the B-rep.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import Viewer from './Viewer';
import {
    confirmJoint, getSweep, startSweep, unconfirmJoint,
    type GraphInstance, type GraphPart, type JointRow, type JointSpec, type ModelGraph, type MotionPayload, type Sweep, type SweepResult,
} from '../../services/reviewApi';
import { useReview } from '../../store/reviewStore';

const deg = (r: number) => (r * 180) / Math.PI;
const rad = (d: number) => (d * Math.PI) / 180;
const polyval = (c: number[], x: number) => c.reduce((s, v, k) => s + v * x ** k, 0);

/** 4x4 (mm) rotating by `a` about `axis` through `p`, or translating by `a` mm along it. */
function motionMatrix(kind: 'hinge' | 'slide', axis: number[], p: number[], a: number): number[][] {
    const n = Math.hypot(...axis) || 1;
    const [x, y, z] = axis.map((v) => v / n);
    if (kind === 'slide') return [[1, 0, 0, x * a], [0, 1, 0, y * a], [0, 0, 1, z * a], [0, 0, 0, 1]];
    const c = Math.cos(a), s = Math.sin(a), t = 1 - c;
    const R = [
        [t * x * x + c, t * x * y - s * z, t * x * z + s * y],
        [t * x * y + s * z, t * y * y + c, t * y * z - s * x],
        [t * x * z - s * y, t * y * z + s * x, t * z * z + c],
    ];
    const tr = [0, 1, 2].map((i) => p[i] - (R[i][0] * p[0] + R[i][1] * p[1] + R[i][2] * p[2]));
    return [[...R[0], tr[0]], [...R[1], tr[1]], [...R[2], tr[2]], [0, 0, 0, 1]];
}

function fmtQ(q: number, kind: 'hinge' | 'slide') {
    return kind === 'hinge' ? `${deg(q).toFixed(2)}°` : `${q.toFixed(3)} mm`;
}

function Chart({ r, q, onPick, minClear }: { r: SweepResult; q: number; onPick: (q: number) => void; minClear: number }) {
    const W = 640, H = 170, L = 44, B = 26, T = 10, R = 10;
    const j = r.joint;
    const lo = Math.min(j.lower ?? 0, ...r.samples.map((s) => s.q));
    const hi = Math.max(j.upper ?? 0, ...r.samples.map((s) => s.q));
    const cap = 10;
    const conv = (v: number) => (j.kind === 'hinge' ? deg(v) : v);
    const X = (v: number) => L + ((v - lo) / (hi - lo || 1)) * (W - L - R);
    const Y = (d: number) => T + (1 - Math.min(d, cap) / cap) * (H - T - B);
    const pts = r.samples
        .map((s) => `${X(s.q).toFixed(1)},${Y(s.min_distance ?? cap).toFixed(1)}`).join(' ');
    const svg = useRef<SVGSVGElement>(null);
    const ticks = 6;
    return (
        <svg ref={svg} viewBox={`0 0 ${W} ${H}`} width="100%" role="img" style={{ display: 'block', cursor: 'crosshair', userSelect: 'none' }}
            aria-label={`Clearance against ${j.kind === 'hinge' ? 'angle' : 'travel'}: minimum ${r.min_clearance ? r.min_clearance.distance.toFixed(3) + ' mm' : 'over 10 mm'}`}
            onClick={(e) => {
                const b = svg.current!.getBoundingClientRect();
                const x = ((e.clientX - b.left) / b.width) * W;
                onPick(Math.max(lo, Math.min(hi, lo + ((x - L) / (W - L - R)) * (hi - lo))));
            }}>
            <rect x={L} y={Y(minClear)} width={W - L - R} height={Y(0) - Y(minClear)} fill="var(--line-2)" opacity={0.6} />
            {[0, 2.5, 5, 7.5, 10].map((d) => (
                <g key={d}>
                    <line x1={L} x2={W - R} y1={Y(d)} y2={Y(d)} stroke="var(--line)" strokeWidth={0.5} />
                    <text x={L - 6} y={Y(d) + 3} fontSize={9} textAnchor="end" fill="var(--muted)" fontFamily="var(--mono)">{d === 10 ? '≥10' : d}</text>
                </g>
            ))}
            {Array.from({ length: ticks + 1 }, (_, k) => lo + ((hi - lo) * k) / ticks).map((v) => (
                <text key={v} x={X(v)} y={H - 8} fontSize={9} textAnchor="middle" fill="var(--muted)" fontFamily="var(--mono)">
                    {conv(v).toFixed(j.kind === 'hinge' ? 0 : 1)}
                </text>
            ))}
            <text x={W - R} y={H - 8 - 12} fontSize={9} textAnchor="end" fill="var(--muted)" fontFamily="var(--mono)">{j.kind === 'hinge' ? 'joint angle, deg' : 'travel, mm'}</text>
            <text x={4} y={T + 4} fontSize={9} fill="var(--muted)" fontFamily="var(--mono)">mm</text>
            {[j.lower, j.upper].map((v, k) => v !== null && (
                <line key={k} x1={X(v)} x2={X(v)} y1={T} y2={H - B} stroke="var(--text)" strokeDasharray="3 3" strokeWidth={1} />
            ))}
            <line x1={X(j.cad_q)} x2={X(j.cad_q)} y1={T} y2={H - B} stroke="var(--muted)" strokeWidth={0.75} />
            <text x={X(j.cad_q) + 3} y={T + 9} fontSize={9} fill="var(--muted)" fontFamily="var(--mono)">CAD</text>
            <polyline points={pts} fill="none" stroke="var(--text)" strokeWidth={1.5} />
            {r.samples.map((s) => <rect key={s.q} x={X(s.q) - 1.5} y={Y(s.min_distance ?? cap) - 1.5} width={3} height={3} fill="var(--text)" />)}
            {(['upper', 'lower'] as const).map((side) => {
                const c = r.collisions[side];
                if (!c) return null;
                return (
                    <g key={side}>
                        <rect x={X(c.q) - 5} y={Y(0) - 5} width={10} height={10} fill="var(--text)" />
                        <text x={X(c.q) + (side === 'upper' ? -8 : 8)} y={Y(0) - 9} fontSize={10} fontFamily="var(--mono)"
                            textAnchor={side === 'upper' ? 'end' : 'start'} fill="var(--text)">collision {fmtQ(c.q, j.kind)}</text>
                    </g>
                );
            })}
            <line x1={X(q)} x2={X(q)} y1={T} y2={H - B} stroke="var(--text)" strokeWidth={1.5} />
        </svg>
    );
}

function MovingPicker({ graph, value, onChange, onClose }: {
    graph: ModelGraph; value: string[]; onChange: (ids: string[]) => void; onClose: () => void;
}) {
    const [sel, setSel] = useState(new Set(value));
    const parts = useMemo(() => {
        const m = new Map<string, string[]>();
        for (const i of graph.instances) m.set(i.part_id, [...(m.get(i.part_id) ?? []), i.id]);
        return [...m.entries()].map(([pid, ids]) => ({ name: graph.parts.find((p) => p.id === pid)?.name ?? pid, ids }))
            .sort((a, b) => a.name.localeCompare(b.name));
    }, [graph]);
    return (
        <div style={{ border: '1px solid var(--line-2)', padding: 8, maxHeight: 260, overflowY: 'auto', background: 'var(--bg)', marginTop: 6 }}>
            {parts.map((p) => (
                <div key={p.name} style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', padding: '1px 0', fontSize: 12 }}>
                    <span style={{ minWidth: 170 }}>{p.name}</span>
                    {p.ids.map((id, k) => (
                        <label key={id} className="mono" style={{ fontSize: 11, display: 'inline-flex', gap: 3, alignItems: 'center' }}>
                            <input type="checkbox" checked={sel.has(id)} onChange={(e) => {
                                const n = new Set(sel);
                                if (e.target.checked) n.add(id); else n.delete(id);
                                setSel(n);
                            }} />{p.ids.length > 1 ? `#${k + 1}` : ''}
                        </label>
                    ))}
                </div>
            ))}
            <div style={{ display: 'flex', gap: 4, marginTop: 6 }}>
                <button className="btn btn--solid" onClick={() => { onChange([...sel]); onClose(); }}>Use these {sel.size}</button>
                <button className="btn btn--ghost" onClick={onClose}>Cancel</button>
            </div>
        </div>
    );
}

function Num({ label, value, onChange, step = 0.01, width = 74 }: { label: string; value: number; onChange: (v: number) => void; step?: number; width?: number }) {
    return (
        <label style={{ display: 'inline-flex', flexDirection: 'column', fontSize: 10, color: 'var(--muted)', gap: 2 }}>
            {label}
            <input type="number" value={Number.isFinite(value) ? Number(value.toFixed(4)) : ''} step={step}
                onChange={(e) => onChange(Number(e.target.value))}
                style={{ width, height: 26, border: '1px solid var(--line-2)', padding: '0 4px', fontFamily: 'var(--mono)', fontSize: 12 }} />
        </label>
    );
}

export default function MotionLens({ rid, graph, glb, data, onChanged }: {
    rid: string;
    graph: ModelGraph;
    glb: ArrayBuffer | null;
    data: MotionPayload;
    onChanged: (m?: MotionPayload) => void;
}) {
    const all = [...data.joints, ...data.inferred];
    const [key, setKey] = useState<string | null>(data.joints[0]?.candidate.key ?? null);
    const row: JointRow | undefined = all.find((r) => r.candidate.key === key);
    const [draft, setDraft] = useState<JointSpec | null>(null);
    const [picking, setPicking] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [sweep, setSweep] = useState<Sweep | null>(null);
    const [q, setQ] = useState(0);
    const [showInferred, setShowInferred] = useState(false);
    const select = useReview((s) => s.select);
    const names = useMemo(() => new Map(graph.instances.map((i) => [i.id, graph.parts.find((p) => p.id === i.part_id)?.name ?? i.name])), [graph]);
    const instances = useMemo(() => new Map<string, GraphInstance>(graph.instances.map((i) => [i.id, i])), [graph]);
    const parts = useMemo(() => new Map<string, GraphPart>(graph.parts.map((p) => [p.id, p])), [graph]);

    useEffect(() => {
        if (!row) return;
        const spec = row.confirmed ?? row.candidate;
        setDraft({ ...spec, moving: [...spec.moving], ignore: [...(spec.ignore ?? [])] });
        setSweep(row.sweep);
        setQ(spec.cad_q);
        setPicking(false);
        setError('');
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [key, row?.spec_hash, row?.sweep?.id]);

    // poll a running sweep
    useEffect(() => {
        if (!sweep || (sweep.state !== 'queued' && sweep.state !== 'running')) return;
        const t = setInterval(() => {
            getSweep(sweep.id).then((s) => {
                setSweep(s);
                if (s.state === 'done' || s.state === 'failed') onChanged();
            }).catch(() => {});
        }, 1500);
        return () => clearInterval(t);
    }, [sweep, onChanged]);

    const result = sweep?.state === 'done' && !row?.stale ? sweep.result : null;
    const spec = draft;
    const hinge = spec?.kind === 'hinge';
    const conv = (v: number) => (hinge ? deg(v) : v);
    const back = (v: number) => (hinge ? rad(v) : v);

    const pose = useMemo(() => {
        if (!spec) return undefined;
        const groups = result?.groups ?? [{ name: spec.name, kind: spec.kind, axis: spec.axis, point: spec.point, coef: [0, 1], source: 'swept joint', carried: [], moving: spec.moving }];
        const m = new Map<string, number[][]>();
        groups.forEach((g, k) => {
            const d = k === 0 ? q - spec.cad_q : polyval(g.coef, q) - polyval(g.coef, spec.cad_q);
            const M = motionMatrix(g.kind, g.axis, g.point, d);
            for (const id of g.moving) m.set(id, M);
        });
        return m;
    }, [spec, result, q]);

    const act = async (fn: () => Promise<void>) => {
        setBusy(true);
        setError('');
        try { await fn(); } catch (e) { setError(String((e as Error).message)); } finally { setBusy(false); }
    };

    const status = (r: JointRow) => {
        if (r.sweep && (r.sweep.state === 'queued' || r.sweep.state === 'running')) return `sweeping ${Math.round(r.sweep.progress * 100)} %`;
        if (!r.confirmed) return 'to confirm';
        if (r.stale || !r.sweep) return 'confirmed · not swept';
        if (r.sweep.state === 'failed') return 'sweep failed';
        const c = r.sweep.result?.collisions;
        const hits = c ? [c.upper, c.lower].filter(Boolean).length : 0;
        return hits ? `${hits} collision${hits > 1 ? 's' : ''}` : 'clear';
    };

    const canConfirm = !!spec && spec.lower !== null && spec.upper !== null && spec.limits_source.trim().length >= 3 &&
        spec.moving.length > 0 && spec.lower <= spec.cad_q && spec.cad_q <= spec.upper && spec.lower < spec.upper;
    const dirty = !!row && !!spec && JSON.stringify({ ...(row.confirmed ?? {}), followers: undefined }) !== JSON.stringify({ ...spec, followers: undefined });

    return (
        <div style={{ display: 'flex', flex: 1, minWidth: 0, minHeight: 0 }}>
            <aside style={{ width: 340, flex: 'none', borderRight: '1px solid var(--line)', overflowY: 'auto', background: 'var(--bg)' }} aria-label="Joints">
                <div style={{ padding: '14px 14px 6px' }}><span className="label">Joints</span></div>
                {data.joints.length === 0 && (
                    <p className="muted" style={{ padding: '0 14px', fontSize: 12 }}>
                        {data.sim_reason ? `No joints from a sim model: ${data.sim_reason}.` : 'No joints.'} Candidates from the geometry are below.
                    </p>
                )}
                {data.joints.map((r) => (
                    <button key={r.candidate.key} className="rv-jrow" aria-pressed={r.candidate.key === key} onClick={() => setKey(r.candidate.key)}>
                        <span className="mono" style={{ fontSize: 12 }}>{r.candidate.name}</span>
                        <span className="muted" style={{ fontSize: 11 }}>{r.candidate.source} · {r.candidate.kind} · {status(r)}</span>
                    </button>
                ))}
                {data.inferred.length > 0 && (
                    <div style={{ padding: '10px 14px' }}>
                        <button className="btn btn--ghost" onClick={() => setShowInferred(!showInferred)} aria-expanded={showInferred}>
                            {showInferred ? '▾' : '▸'} From the geometry ({data.inferred.length})
                        </button>
                        {showInferred && <p className="muted" style={{ fontSize: 11, margin: '6px 0 0' }}>A boss running in a bore with clearance. Most are pins and shoulder bolts: confirm only real joints, with their limits.</p>}
                    </div>
                )}
                {showInferred && data.inferred.map((r) => (
                    <button key={r.candidate.key} className="rv-jrow" aria-pressed={r.candidate.key === key} onClick={() => setKey(r.candidate.key)}>
                        <span style={{ fontSize: 12 }}>{r.candidate.name}</span>
                        <span className="muted" style={{ fontSize: 11 }}>{r.candidate.evidence} · {status(r)}</span>
                    </button>
                ))}

                {row && spec && (
                    <div style={{ padding: 14, borderTop: '1px solid var(--line)', marginTop: 8 }}>
                        <div className="mono" style={{ fontSize: 13 }}>{spec.name}</div>
                        <div className="muted" style={{ fontSize: 11, marginBottom: 8 }}>
                            {row.confirmed ? `confirmed by ${row.confirmed_by}` : 'not confirmed — check every value, then confirm'}
                        </div>
                        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                            {[0, 1, 2].map((k) => <Num key={k} label={`axis ${'xyz'[k]}`} value={spec.axis[k]} width={70}
                                onChange={(v) => setDraft({ ...spec, axis: spec.axis.map((a, i) => (i === k ? v : a)) })} />)}
                        </div>
                        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
                            {[0, 1, 2].map((k) => <Num key={k} label={`point ${'xyz'[k]} mm`} value={spec.point[k]} width={70} step={0.1}
                                onChange={(v) => setDraft({ ...spec, point: spec.point.map((a, i) => (i === k ? v : a)) })} />)}
                        </div>
                        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
                            <Num label={`lower ${hinge ? '°' : 'mm'}`} value={spec.lower === null ? NaN : conv(spec.lower)} step={0.1}
                                onChange={(v) => setDraft({ ...spec, lower: back(v) })} />
                            <Num label={`upper ${hinge ? '°' : 'mm'}`} value={spec.upper === null ? NaN : conv(spec.upper)} step={0.1}
                                onChange={(v) => setDraft({ ...spec, upper: back(v) })} />
                            <Num label={`CAD pose ${hinge ? '°' : 'mm'}`} value={conv(spec.cad_q)} step={0.1}
                                onChange={(v) => setDraft({ ...spec, cad_q: back(v) })} />
                            <Num label={`step ${hinge ? '°' : 'mm'}`} value={spec.step ? conv(spec.step) : hinge ? 2 : 0.5} step={0.5} width={60}
                                onChange={(v) => setDraft({ ...spec, step: back(v) })} />
                        </div>
                        <label style={{ display: 'block', fontSize: 10, color: 'var(--muted)', marginTop: 6 }}>Limits from (required)
                            <input value={spec.limits_source} onChange={(e) => setDraft({ ...spec, limits_source: e.target.value })}
                                style={{ display: 'block', width: '100%', height: 26, border: '1px solid var(--line-2)', padding: '0 6px', fontSize: 12 }} />
                        </label>
                        <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>CAD pose: {spec.cad_q_source || '—'}</div>
                        {(spec.followers ?? []).length > 0 && (
                            <div style={{ fontSize: 11, marginTop: 6 }}>
                                Moves with: {spec.followers!.map((f) => `${f.name} (q = ${f.coef.slice(0, 2).map((c) => +c.toFixed(4)).join(' + ')}·q, ${f.source})`).join('; ')}
                            </div>
                        )}
                        <div style={{ fontSize: 12, marginTop: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span><b>{spec.moving.length}</b> moving part{spec.moving.length === 1 ? '' : 's'}</span>
                            <button className="btn btn--ghost" onClick={() => setPicking(!picking)}>Edit…</button>
                        </div>
                        <div className="muted" style={{ fontSize: 11 }}>{[...new Set(spec.moving.map((i) => names.get(i)))].slice(0, 8).join(', ')}{spec.moving.length > 8 ? ' …' : ''}</div>
                        {picking && <MovingPicker graph={graph} value={spec.moving} onChange={(ids) => setDraft({ ...spec, moving: ids })} onClose={() => setPicking(false)} />}
                        {error && <p className="rv-err">{error}</p>}
                        <div style={{ display: 'flex', gap: 4, marginTop: 10, flexWrap: 'wrap' }}>
                            <button className="btn btn--solid" disabled={busy || !canConfirm || (!!row.confirmed && !dirty)}
                                onClick={() => act(async () => onChanged(await confirmJoint(rid, spec)))}>
                                {row.confirmed ? 'Save changes' : 'Confirm joint'}
                            </button>
                            <button className="btn" disabled={busy || !row.confirmed || dirty || sweep?.state === 'running' || sweep?.state === 'queued'}
                                onClick={() => act(async () => setSweep(await startSweep(rid, spec.key)))}>
                                {row.sweep && !row.stale ? 'Sweep again' : 'Run sweep'}
                            </button>
                            {row.confirmed && <button className="btn btn--ghost" disabled={busy}
                                onClick={() => act(async () => onChanged(await unconfirmJoint(rid, spec.key)))}>Unconfirm</button>}
                        </div>
                        {!canConfirm && <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>Needs limits with their source, at least one moving part, and the CAD pose within the limits.</div>}
                        {sweep && (sweep.state === 'queued' || sweep.state === 'running') && (
                            <div style={{ marginTop: 8 }}>
                                <div style={{ height: 4, background: 'var(--line)' }}><div style={{ height: 4, width: `${sweep.progress * 100}%`, background: 'var(--text)' }} /></div>
                                <div className="muted mono" style={{ fontSize: 10, marginTop: 3 }}>{sweep.state} · {sweep.note}</div>
                            </div>
                        )}
                        {sweep?.state === 'failed' && <p className="rv-err">{sweep.error?.split('\n')[0]}</p>}
                        {row.stale && <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>The joint changed since the last sweep: run it again.</div>}
                    </div>
                )}
            </aside>

            <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
                <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
                    {glb ? <Viewer glb={glb} instances={instances} parts={parts} features={[]} contacts={[]} pose={pose} />
                        : <div className="rv-loading">Loading the viewer…</div>}
                </div>
                {spec && (
                    <div style={{ borderTop: '1px solid var(--line)', background: 'var(--bg)', padding: '10px 14px', maxHeight: '46%', overflowY: 'auto' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                            <span className="label">{hinge ? 'Angle' : 'Travel'}</span>
                            <input type="range" aria-label="Joint position" style={{ flex: 1 }}
                                min={spec.lower ?? spec.cad_q - (hinge ? Math.PI : 10)} max={spec.upper ?? spec.cad_q + (hinge ? Math.PI : 10)}
                                step={hinge ? rad(0.1) : 0.01} value={q} onChange={(e) => setQ(Number(e.target.value))} />
                            <span className="mono" style={{ width: 84, textAlign: 'right', fontSize: 12 }}>{fmtQ(q, spec.kind)}</span>
                            <button className="btn btn--ghost" onClick={() => setQ(spec.cad_q)}>CAD pose</button>
                        </div>
                        {result ? (
                            <>
                                <Chart r={result} q={q} onPick={setQ} minClear={0.3} />
                                <div className="rv-console" style={{ marginTop: 6, fontSize: 11 }}>{[
                                    '> SUMMARY',
                                    `> ${result.joint.name} swept from the CAD pose (${fmtQ(result.joint.cad_q, spec.kind)}) to ${fmtQ(result.joint.lower!, spec.kind)} and ${fmtQ(result.joint.upper!, spec.kind)} in ${result.samples.length} poses, ${result.seconds} s.`,
                                    result.groups.length > 1 ? `> Coupled: ${result.groups.slice(1).map((g) => `${g.name} (${g.source})`).join('; ')}.` : '',
                                    ...(['upper', 'lower'] as const).map((side) => {
                                        const c = result.collisions[side];
                                        return c ? `> ${side}: ${names.get(c.moving)} meets ${names.get(c.other)} at ${fmtQ(c.q, spec.kind)} (clear until ${fmtQ(c.clear_until_q, spec.kind)}).`
                                            : `> ${side}: reaches the limit ${fmtQ(result.ends[side].q, spec.kind)} without collision.`;
                                    }),
                                    result.min_clearance ? `> Closest approach ${result.min_clearance.distance.toFixed(3)} mm, ${names.get(result.min_clearance.pair[0])} – ${names.get(result.min_clearance.pair[1])} at ${fmtQ(result.min_clearance.q, spec.kind)}.` : '> Nothing comes within 10 mm.',
                                    result.groups.some((g) => g.carried.length) ? `> Carried with the moving parts: ${[...new Set(result.groups.flatMap((g) => g.carried).map((i) => names.get(i)))].join(', ')}.` : '',
                                    result.drivers.length ? `> Not judged: ${result.drivers.map((d) => names.get(d.id)).join(', ')} — drives the joint (its output is bolted to the moving parts; housing and output are one solid in the CAD).` : '',
                                    `> Riding on the axis (unchanged by the motion): ${result.riding.length}; touching pairs tracked by overlap volume: ${result.tracked.length}.`,
                                ].filter(Boolean).join('\n')}</div>
                                <table className="rv-table" style={{ marginTop: 8 }}>
                                    <thead><tr><th>At</th><th>Moving part</th><th>Nearest part</th><th className="num">Distance</th></tr></thead>
                                    <tbody>
                                        {(['lower', 'upper'] as const).flatMap((side) => result.ends[side].nearest.slice(0, 3).map((n, k) => (
                                            <tr key={side + k} data-click onClick={() => { setQ(result.ends[side].q); select({ kind: 'instance', id: n.other }); }}>
                                                <td className="mono" style={{ fontSize: 11 }}>{k === 0 ? `${side} ${fmtQ(result.ends[side].q, spec.kind)}` : ''}</td>
                                                <td>{names.get(n.moving)}</td><td>{names.get(n.other)}</td>
                                                <td className="num">{n.distance.toFixed(3)} mm</td>
                                            </tr>
                                        )))}
                                    </tbody>
                                </table>
                                <p className="muted" style={{ fontSize: 10, marginTop: 6 }}>{result.method}</p>
                            </>
                        ) : (
                            <p className="muted" style={{ fontSize: 12, margin: '8px 0 0' }}>
                                {row?.confirmed ? 'Run the sweep to chart clearance against position.' : 'Confirm the joint to sweep it. The scrubber already poses the moving parts about the axis shown.'}
                            </p>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
}
