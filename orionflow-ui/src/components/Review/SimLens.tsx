/**
 * Sim lens: the robot's URDF/MJCF against the CAD it was made from.
 *
 * Every number shows where it came from. Masses the BOM cannot give (a
 * servo, a camera, a part made of "A2024 / PLA") are entered here with a
 * stated source and apply to every revision of the project; the comparison
 * and the checks re-run immediately, without re-reading the STEP.
 */
import { useMemo, useState } from 'react';
import {
    deleteOverride, setOverride, setSimLink, fmtNum,
    type ModelGraph, type PartOverride, type SimBody, type SimPayload,
} from '../../services/reviewApi';
import { useReview } from '../../store/reviewStore';

/** Sim value (black tick) on a ±20 % window around the CAD value; the grey band is the tolerance. */
function Bar({ sim, cad, tol }: { sim: number; cad: number; tol: number }) {
    const span = 0.2;
    const x = (v: number) => `${Math.max(0, Math.min(100, ((v / cad - 1) / span / 2 + 0.5) * 100))}%`;
    return (
        <div style={{ position: 'relative', height: 14, minWidth: 140 }} aria-hidden="true">
            <div style={{ position: 'absolute', top: 6, height: 1, left: 0, right: 0, background: 'var(--line-2)' }} />
            <div style={{ position: 'absolute', top: 3, height: 8, left: x(cad * (1 - tol)), width: `${(tol / span) * 50}%`, background: 'var(--line-2)' }} />
            <div style={{ position: 'absolute', top: 2, height: 10, width: 1, left: '50%', background: 'var(--muted)' }} />
            <div style={{ position: 'absolute', top: 0, width: 2, height: 14, left: x(sim), background: 'var(--text)' }} />
        </div>
    );
}

function Snippet({ title, text, file }: { title: string; text: string; file: string }) {
    const [copied, setCopied] = useState(false);
    return (
        <div style={{ marginTop: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span className="label">{title}</span>
                <button className="btn btn--ghost" style={{ marginLeft: 'auto', height: 22 }}
                    onClick={() => navigator.clipboard.writeText(text).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1200); })}>
                    {copied ? 'Copied' : 'Copy'}
                </button>
                <button className="btn btn--ghost" style={{ height: 22 }} onClick={() => {
                    const url = URL.createObjectURL(new Blob([text], { type: 'text/xml' }));
                    const a = document.createElement('a');
                    a.href = url; a.download = file; a.click();
                    setTimeout(() => URL.revokeObjectURL(url), 1000);
                }}>Download</button>
            </div>
            <pre className="rv-console" style={{ margin: '4px 0 0', fontSize: 11, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{text}</pre>
        </div>
    );
}

function MapEditor({ body, graph, onSave, onAuto, onCancel }: {
    body: SimBody;
    graph: ModelGraph;
    onSave: (ids: string[]) => void;
    onAuto: () => void;
    onCancel: () => void;
}) {
    const [sel, setSel] = useState<Set<string>>(new Set(body.instances));
    const parts = useMemo(() => {
        const m = new Map<string, string[]>();
        for (const i of graph.instances) m.set(i.part_id, [...(m.get(i.part_id) ?? []), i.id]);
        return [...m.entries()].map(([pid, ids]) => ({ pid, name: graph.parts.find((p) => p.id === pid)?.name ?? pid, ids }))
            .sort((a, b) => a.name.localeCompare(b.name));
    }, [graph]);
    return (
        <div style={{ border: '1px solid var(--line-2)', padding: 10, marginTop: 6, maxHeight: 300, overflowY: 'auto', background: 'var(--bg)' }}>
            {parts.map((p) => (
                <div key={p.pid} style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', padding: '2px 0' }}>
                    <span style={{ minWidth: 220, fontSize: 12 }}>{p.name}</span>
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
            <div style={{ display: 'flex', gap: 4, marginTop: 8 }}>
                <button className="btn btn--solid" onClick={() => onSave([...sel])}>Save mapping</button>
                <button className="btn" onClick={onAuto}>Back to automatic</button>
                <button className="btn btn--ghost" onClick={onCancel}>Cancel</button>
            </div>
        </div>
    );
}

export default function SimLens({ rid, pid, graph, data, overrides, onChanged }: {
    rid: string;
    pid: string;
    graph: ModelGraph;
    data: SimPayload;
    overrides: PartOverride[];
    onChanged: (sim?: SimPayload, ov?: PartOverride[]) => void;
}) {
    const [editing, setEditing] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [form, setForm] = useState({ part_name: '', kind: 'mass_g', value: '', source: '' });
    const select = useReview((s) => s.select);
    const names = useMemo(() => new Map(graph.instances.map((i) => [i.id, i.name])), [graph]);
    const sim = data.sim;

    const act = async (fn: () => Promise<void>) => {
        setBusy(true);
        setError('');
        try { await fn(); } catch (e) { setError(String((e as Error).message)); } finally { setBusy(false); }
    };

    if (!sim || !sim.analysis) {
        return (
            <div className="rv-page" style={{ background: 'var(--bg)' }}>
                <div className="rv-empty" style={{ marginTop: 60 }}>
                    <b>No sim model in this revision</b>
                    Add the robot's URDF or MJCF to compare its masses, centres of mass, inertias and joint axes with the CAD.
                    Include a registration file (cad_origin_mm, cad_to_canonical_rotation) to enable the frame-dependent checks.
                </div>
            </div>
        );
    }
    const a = sim.analysis;
    const noMass = (data.parts ?? []).filter((p) => p.mass === null);

    return (
        <div className="rv-page" style={{ background: 'var(--bg)' }}>
            <div className="rv-page__in" style={{ maxWidth: 1180, paddingTop: 20 }}>
                <span className="label">Sim fidelity · {sim.format.toUpperCase()}</span>
                <h1 style={{ fontSize: 22 }}>{sim.file}</h1>
                <div className="rv-console" style={{ marginTop: 12 }}>{[
                    '> SUMMARY',
                    `> ${sim.model || 'model'}: ${a.bodies.length} bodies and ${a.joints.length} joints compared${sim.copies > 1 ? ` (the scene holds ${sim.copies} copies; the first is used)` : ''}.`,
                    `> Bodies mapped to CAD by ${[...new Set(a.bodies.map((b) => b.method))].join(', ')}; ${a.bodies.reduce((n, b) => n + b.instances.length, 0)} of ${graph.instances.length} CAD instances assigned.`,
                    sim.registration ? `> Frames registered by ${sim.registration}: centre of mass and joint axes are compared.` : '> No registration file: only mass and principal moments are compared.',
                    sim.manifest_source_sha256 ? `> The sim's manifest was built from STEP ${sim.manifest_source_sha256.slice(0, 12)}…, this revision is ${graph.source.sha256.slice(0, 12)}… — ${sim.manifest_source_sha256 === graph.source.sha256 ? 'the same file' : 'a different file'}.` : '',
                ].filter(Boolean).join('\n')}</div>
                {error && <p className="rv-err">{error}</p>}

                <h3 style={{ fontSize: 14, margin: '24px 0 6px' }}>Bodies</h3>
                <table className="rv-table">
                    <thead><tr><th>Body</th><th>Mapped by</th><th className="num">CAD parts</th><th className="num">Mass sim</th><th className="num">Mass CAD</th><th title="window ±20 % around the CAD mass; grey band = ±5 % tolerance">sim ▮ vs CAD ±5 %</th><th className="num">COM Δ</th><th className="num">Principal Δ</th><th></th></tr></thead>
                    <tbody>
                        {a.bodies.map((b) => {
                            const cad = b.cad;
                            const dm = cad && b.sim && cad.complete ? (cad.mass - b.sim.mass) / b.sim.mass : null;
                            let dcom: number | null = null;
                            if (cad?.complete && b.sim) {
                                if (b.frame === 'hinge' && cad.cyl_m && b.sim_cyl_m) dcom = Math.hypot(cad.cyl_m[0] - b.sim_cyl_m[0], cad.cyl_m[1] - b.sim_cyl_m[1]) * 1000;
                                else if (cad.com_m) dcom = Math.hypot(...cad.com_m.map((v, k) => v - b.sim!.com[k])) * 1000;
                            }
                            let dI: number | null = null;
                            if (cad?.complete && cad.principal_kg_m2 && b.sim) {
                                const ev = b.sim.inertia;
                                // eigenvalues of a symmetric 3x3 via the characteristic polynomial
                                const m = (ev[0][0] + ev[1][1] + ev[2][2]) / 3;
                                const K = ev.map((r, i) => r.map((v, j) => v - (i === j ? m : 0)));
                                const q = (K[0][0] * (K[1][1] * K[2][2] - K[1][2] * K[2][1]) - K[0][1] * (K[1][0] * K[2][2] - K[1][2] * K[2][0]) + K[0][2] * (K[1][0] * K[2][1] - K[1][1] * K[2][0])) / 2;
                                const p = Math.sqrt(K.flat().reduce((s, v) => s + v * v, 0) / 6);
                                const phi = p > 0 ? Math.acos(Math.max(-1, Math.min(1, q / p ** 3))) / 3 : 0;
                                const e = [m + 2 * p * Math.cos(phi), m + 2 * p * Math.cos(phi + (2 * Math.PI) / 3), m + 2 * p * Math.cos(phi + (4 * Math.PI) / 3)].sort((x, y) => x - y);
                                dI = Math.max(...e.map((v, k) => Math.abs(v - cad.principal_kg_m2![k]) / cad.principal_kg_m2![k]));
                            }
                            return (
                                <tr key={b.body} data-click onClick={() => b.instances[0] && select({ kind: 'instance', id: b.instances[0] })}>
                                    <td><span className="mono" style={{ fontSize: 12 }}>{b.body}</span>{b.frame === 'hinge' && <div className="muted" style={{ fontSize: 11 }}>hinged · CAD posed {b.pose_offset_deg?.toFixed(1)}° from sim zero</div>}</td>
                                    <td className="mono" style={{ fontSize: 11 }}>{b.method}</td>
                                    <td className="num">{b.instances.length}</td>
                                    <td className="num">{b.sim ? `${fmtNum(b.sim.mass * 1000, 1)} g` : '—'}</td>
                                    <td className="num" title={cad && !cad.complete ? `missing: ${b.missing.map((i) => names.get(i)).join(', ')}` : 'STEP volume × density / stated masses'}>
                                        {cad ? `${fmtNum(cad.mass * 1000, 1)} g${cad.complete ? '' : ' +?'}` : '—'}
                                    </td>
                                    <td>{cad?.complete && b.sim ? <Bar sim={b.sim.mass} cad={cad.mass} tol={0.05} /> : <span className="muted" style={{ fontSize: 11 }}>{cad ? `${b.missing.length} part${b.missing.length === 1 ? '' : 's'} without mass` : ''}</span>}</td>
                                    <td className="num">{dcom === null ? '—' : `${dcom.toFixed(2)} mm`}</td>
                                    <td className="num">{dI === null ? '—' : `${(dI * 100).toFixed(0)} %`}{dm !== null && <div className="muted" style={{ fontSize: 10 }}>CAD mass {dm >= 0 ? "+" : ""}{(dm * 100).toFixed(1)} %</div>}</td>
                                    <td><button className="btn btn--ghost" onClick={(e) => { e.stopPropagation(); setEditing(editing === b.body ? null : b.body); }}>Map…</button></td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
                {editing && (() => {
                    const b = a.bodies.find((x) => x.body === editing)!;
                    return (
                        <MapEditor body={b} graph={graph} onCancel={() => setEditing(null)}
                            onSave={(ids) => act(async () => { onChanged(await setSimLink(rid, b.body, ids)); setEditing(null); })}
                            onAuto={() => act(async () => { onChanged(await setSimLink(rid, b.body, null)); setEditing(null); })} />
                    );
                })()}

                <h3 style={{ fontSize: 14, margin: '24px 0 6px' }}>Joints</h3>
                <table className="rv-table">
                    <thead><tr><th>Joint</th><th>Type</th><th>Axis (root frame)</th><th>Range</th><th>CAD hinge bore</th><th className="num">Angle</th><th className="num">Offset</th></tr></thead>
                    <tbody>
                        {a.joints.map((j) => {
                            const c = j.cad_axes?.[0];
                            let ang: number | null = null;
                            let off: number | null = null;
                            if (c) {
                                const dot = Math.abs(j.axis_root.reduce((s, v, k) => s + v * c.axis_root[k], 0));
                                ang = (Math.acos(Math.min(1, dot)) * 180) / Math.PI;
                                const d = c.point_root.map((v, k) => v - j.pos_root[k]);
                                const t = d.reduce((s, v, k) => s + v * c.axis_root[k], 0);
                                off = Math.hypot(...d.map((v, k) => v - c.axis_root[k] * t)) * 1000;
                            }
                            return (
                                <tr key={j.name}>
                                    <td className="mono" style={{ fontSize: 12 }}>{j.name}</td>
                                    <td>{j.type}</td>
                                    <td className="mono" style={{ fontSize: 11 }}>{j.axis_root.map((v) => v.toFixed(3)).join(', ')}</td>
                                    <td className="mono" style={{ fontSize: 11 }}>{j.range ? j.range.map((v) => v.toFixed(3)).join(' … ') : '—'}</td>
                                    <td>{c ? `Ø${c.diameter}` : <span className="muted">no shared bore found</span>}</td>
                                    <td className="num">{ang === null ? '—' : `${ang.toFixed(2)}°`}</td>
                                    <td className="num">{off === null ? '—' : `${off.toFixed(2)} mm`}</td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>

                <h3 style={{ fontSize: 14, margin: '24px 0 6px' }}>Corrected inertials</h3>
                {a.bodies.filter((b) => b.corrected).length === 0 && (
                    <p className="muted">Available for a body once every one of its parts has a mass (see Part masses below).</p>
                )}
                {a.bodies.filter((b) => b.corrected).map((b) => (
                    <div key={b.body} style={{ marginBottom: 14 }}>
                        <div className="mono" style={{ fontSize: 12 }}>{b.body}</div>
                        {b.notes.map((n) => <div key={n} className="muted" style={{ fontSize: 11 }}>{n}</div>)}
                        <Snippet title="MJCF" text={b.corrected!.mjcf} file={`${b.body}_inertial.xml`} />
                        {b.corrected!.urdf && <Snippet title="URDF" text={b.corrected!.urdf} file={`${b.body}_inertial.urdf.xml`} />}
                    </div>
                ))}

                <h3 style={{ fontSize: 14, margin: '24px 0 6px' }}>Part masses</h3>
                <p className="muted" style={{ margin: '0 0 8px', fontSize: 12 }}>
                    Parts the BOM gives no usable material for. A stated value needs its source (datasheet, scale, assumption) and applies to every revision of this project.
                </p>
                <table className="rv-table">
                    <tbody>
                        {noMass.map((p) => (
                            <tr key={p.id}><td><span className="sev sev--notrun" /> {p.name}</td><td className="muted" style={{ fontSize: 12 }}>{p.material ?? 'no material'}</td>
                                <td><button className="btn btn--ghost" onClick={() => setForm({ ...form, part_name: p.name })}>Set…</button></td></tr>
                        ))}
                        {overrides.map((o) => (
                            <tr key={o.part_key}>
                                <td><span className="sev sev--pass" /> {o.part_name}</td>
                                <td style={{ fontSize: 12 }}>
                                    {o.mass_kg ? `${fmtNum(o.mass_kg * 1000, 1)} g each` : o.density ? `${o.density} kg/m³` : o.material}
                                    <span className="muted"> · {o.source}</span>
                                </td>
                                <td><button className="btn btn--ghost" disabled={busy} onClick={() => act(async () => onChanged(undefined, await deleteOverride(pid, o.part_name)))}>Remove</button></td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                <form style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10, alignItems: 'center' }}
                    onSubmit={(e) => {
                        e.preventDefault();
                        const v = form.value.trim();
                        if (!form.part_name || !v || form.source.trim().length < 3) return;
                        const body = form.kind === 'mass_g' ? { mass_kg: Number(v) / 1000 } : form.kind === 'density' ? { density: Number(v) } : { material: v };
                        act(async () => { onChanged(undefined, await setOverride(pid, { part_name: form.part_name, source: form.source.trim(), ...body })); setForm({ part_name: '', kind: 'mass_g', value: '', source: '' }); });
                    }}>
                    <select value={form.part_name} onChange={(e) => setForm({ ...form, part_name: e.target.value })} aria-label="Part"
                        style={{ height: 28, border: '1px solid var(--line-2)', maxWidth: 260 }}>
                        <option value="">Part…</option>
                        {graph.parts.map((p) => <option key={p.id} value={p.name}>{p.name}</option>)}
                    </select>
                    <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })} aria-label="What" style={{ height: 28, border: '1px solid var(--line-2)' }}>
                        <option value="mass_g">mass (g each)</option><option value="density">density (kg/m³)</option><option value="material">material</option>
                    </select>
                    <input value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} placeholder="value" aria-label="Value"
                        style={{ height: 28, width: 110, border: '1px solid var(--line-2)', padding: '0 6px' }} />
                    <input value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} placeholder="source (required)" aria-label="Source"
                        style={{ height: 28, flex: 1, minWidth: 220, border: '1px solid var(--line-2)', padding: '0 6px' }} />
                    <button className="btn btn--solid" disabled={busy || !form.part_name || !form.value || form.source.trim().length < 3}>Save</button>
                </form>
            </div>
        </div>
    );
}
