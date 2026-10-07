/**
 * Inspector: whatever is selected, described with its numbers and their source.
 *
 * Every value carries its unit and, on hover, where it came from — "STEP
 * geometry (OpenCASCADE)" today; later "BOM row 12", "MJCF body", "AI
 * reading, unverified". A number with no stated source is not shown.
 */
import { Crosshair, Eye, Focus } from 'lucide-react';
import type { CylinderFeature, GraphContact, GraphInstance, GraphPart, HoleFeature, ModelGraph, PatternFeature } from '../../services/reviewApi';
import { fmtNum } from '../../services/reviewApi';
import { useReview } from '../../store/reviewStore';

const GEO = 'STEP geometry, measured by OpenCASCADE (GProp / Bnd_Box)';
const FEAT = 'cylindrical B-rep faces merged into holes and bosses; through = open across the whole end at both ends';
const DIST = 'exact BRepExtrema face-to-face distance';

function ContactPanel({ graph, contact }: { graph: ModelGraph; contact: GraphContact }) {
    const select = useReview((s) => s.select);
    const name = (id: string) => graph.instances.find((i) => i.id === id)?.name ?? id;
    return (
        <aside className="rv-inspector" aria-label="Inspector">
            <div className="rv-panel-head">
                <span className="label">Contact</span>
                <span className="mono muted" style={{ marginLeft: 'auto', fontSize: 11 }}>{contact.id}</span>
            </div>
            <div className="rv-sec">
                <h3 style={{ fontSize: 15, fontWeight: 500 }}>{contact.kinds.join(' + ')}</h3>
                <table className="rv-table">
                    <tbody>
                        {[contact.a, contact.b].map((iid, k) => (
                            <tr key={iid} data-click onClick={() => select({ kind: 'instance', id: iid }, true)}>
                                <td className="muted" style={{ width: 20 }}>{k ? 'B' : 'A'}</td>
                                <td>{name(iid)}</td>
                                <td className="mono muted" style={{ fontSize: 11 }}>{iid}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
            <div className="rv-sec">
                <h3>Measured</h3>
                <dl className="rv-kv">
                    <Row k="Minimum distance" v={contact.min_distance === null ? 'box overlap only' : contact.min_distance.toFixed(4)}
                        unit={contact.min_distance === null ? undefined : 'mm'} src={contact.min_distance === null ? 'a mesh body is involved: no exact distance' : DIST} />
                    <Row k="Contact planes" v={contact.planes.length} src="planar faces with opposite normals on one plane that meet" />
                    {contact.point && <Row k="Location" v={contact.point.map((v) => v.toFixed(2)).join(', ')} unit="mm" src="assembly frame" />}
                </dl>
            </div>
            {contact.fits.length > 0 && (
                <div className="rv-sec">
                    <h3>Cylindrical fits</h3>
                    <table className="rv-table">
                        <thead><tr><th>Shaft on</th><th className="num">Hole Ø</th><th className="num">Shaft Ø</th><th className="num">Clearance</th></tr></thead>
                        <tbody>
                            {contact.fits.map((f, k) => (
                                <tr key={k} title={`source: ${FEAT}`}>
                                    <td>{name(f.shaft_on === 'a' ? contact.a : contact.b)}</td>
                                    <td className="num">{f.hole_diameter.toFixed(3)}</td>
                                    <td className="num">{f.shaft_diameter.toFixed(3)}</td>
                                    <td className="num">{f.clearance.toFixed(3)}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                    <p className="muted" style={{ fontSize: 11, margin: '6px 0 0' }}>Diametral clearance, mm. Negative would be interference.</p>
                </div>
            )}
            {contact.coaxial_holes.length > 0 && (
                <div className="rv-sec">
                    <h3>Coaxial holes</h3>
                    <table className="rv-table">
                        <thead><tr><th className="num">Ø in A</th><th className="num">Ø in B</th></tr></thead>
                        <tbody>
                            {contact.coaxial_holes.map((h, k) => (
                                <tr key={k}><td className="num">{h.diameter_a.toFixed(3)}</td><td className="num">{h.diameter_b.toFixed(3)}</td></tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
            <div className="rv-sec">
                <h3>Method</h3>
                <p className="muted" style={{ margin: 0, fontSize: 12 }}>{contact.method}</p>
            </div>
        </aside>
    );
}

function FeatureSection({ graph, part }: { graph: ModelGraph; part: GraphPart }) {
    const hoverFeature = useReview((s) => s.hoverFeature);
    const feats = (graph.features ?? []).filter((f) => f.part_id === part.id);
    const holes = feats.filter((f): f is HoleFeature => f.kind === 'hole');
    const cyls = feats.filter((f): f is CylinderFeature => f.kind === 'cylinder');
    const pats = feats.filter((f): f is PatternFeature => f.kind === 'pattern');
    if (!feats.length) {
        return (
            <div className="rv-sec">
                <h3>Features</h3>
                <div className="muted">{part.geometry_type === 'MESH' ? 'Mesh body: no analytic features.' : 'No holes or cylinders.'}</div>
            </div>
        );
    }
    return (
        <div className="rv-sec">
            <h3>Features</h3>
            {holes.length > 0 && (
                <table className="rv-table" onMouseLeave={() => hoverFeature(null)}>
                    <thead><tr><th>Hole</th><th className="num">Ø</th><th className="num">Depth</th><th>End</th></tr></thead>
                    <tbody>
                        {holes.map((h) => (
                            <tr key={h.id} data-click onMouseEnter={() => hoverFeature(h.id)} title={`source: ${FEAT}`}>
                                <td className="mono muted" style={{ fontSize: 11 }}>{h.id.split('.').pop()}</td>
                                <td className="num">{h.diameter.toFixed(2)}</td>
                                <td className="num">{h.depth.toFixed(2)}</td>
                                <td className="mono" style={{ fontSize: 11 }}>{h.through === null ? '?' : h.through ? 'THRU' : 'blind'}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
            {pats.length > 0 && (
                <ul style={{ listStyle: 'none', margin: '10px 0 0', padding: 0 }}>
                    {pats.map((p) => (
                        <li key={p.id} className="mono" style={{ fontSize: 12, padding: '3px 0' }} title="holes grouped by parallel axis, diameter and plane">
                            ◇ {p.pattern === 'circle' ? `${p.count} × Ø${p.diameter.toFixed(2)} on PCD ${p.pcd?.toFixed(2)}`
                                : p.pattern === 'rect' ? `${p.count} × Ø${p.diameter.toFixed(2)} on ${p.a?.toFixed(2)} × ${p.b?.toFixed(2)}`
                                : `${p.count} × Ø${p.diameter.toFixed(2)} group`}
                        </li>
                    ))}
                </ul>
            )}
            {cyls.length > 0 && (
                <p className="mono muted" style={{ fontSize: 11, margin: '10px 0 0' }}>
                    Cylinders: {cyls.map((c) => `Ø${c.diameter.toFixed(2)}×${c.length.toFixed(1)}`).join(', ')}
                </p>
            )}
        </div>
    );
}

function Row({ k, v, unit, src = GEO }: { k: string; v: React.ReactNode; unit?: string; src?: string }) {
    return (
        <>
            <dt>{k}</dt>
            <dd title={`source: ${src}`}>
                {v}
                {unit && <small>{unit}</small>}
            </dd>
        </>
    );
}

function dims(p: GraphPart): number[] {
    return p.bbox.max.map((v, k) => v - p.bbox.min[k]);
}

export default function Inspector({ graph }: { graph: ModelGraph }) {
    const selection = useReview((s) => s.selection);
    const select = useReview((s) => s.select);
    const isolate = useReview((s) => s.isolate);
    const isolated = useReview((s) => s.isolated);

    if (selection?.kind === 'contact') {
        const c = (graph.contacts ?? []).find((x) => x.id === selection.id);
        if (c) return <ContactPanel graph={graph} contact={c} />;
    }
    if (!selection) {
        const s = graph.stats;
        return (
            <aside className="rv-inspector" aria-label="Inspector">
                <div className="rv-panel-head"><span className="label">Inspector</span></div>
                <div className="rv-sec">
                    <h3>{graph.tree.name}</h3>
                    <dl className="rv-kv">
                        <Row k="Part definitions" v={s.parts} />
                        <Row k="Placed instances" v={s.instances} />
                        <Row k="Sub-assemblies" v={s.assemblies} />
                        <Row k="Tree depth" v={s.max_depth} />
                        <Row k="Features" v={s.features ?? 0} src={FEAT} />
                        <Row k="Contacts" v={s.contacts ?? 0} src={DIST + ' <= 0.05 mm'} />
                        <Row k="Viewer triangles" v={s.triangles.toLocaleString('en-US')} src="tessellation of the STEP faces" />
                    </dl>
                </div>
                <div className="rv-sec">
                    <h3>Source</h3>
                    <dl className="rv-kv">
                        <Row k="File" v={graph.source.name} src="uploaded file" />
                        <Row k="SHA-256" v={<span title={graph.source.sha256}>{graph.source.sha256.slice(0, 16)}…</span>} src="computed on upload" />
                        <Row k="Units" v="mm" src="STEP header, converted to mm" />
                    </dl>
                </div>
                <div className="rv-empty"><b>Nothing selected</b>Click a part in the model or the tree. Double-click to frame it.</div>
            </aside>
        );
    }

    const instMap = new Map(graph.instances.map((i) => [i.id, i]));
    const partMap = new Map(graph.parts.map((p) => [p.id, p]));
    const inst: GraphInstance | undefined = selection.kind === 'instance' ? instMap.get(selection.id) : undefined;
    const part: GraphPart | undefined = partMap.get(inst ? inst.part_id : selection.id);
    if (!part) return <aside className="rv-inspector" />;
    const copies = graph.instances.filter((i) => i.part_id === part.id);
    const d = dims(part);
    const pos = inst ? inst.transform.slice(0, 3).map((r) => r[3]) : null;
    const ids = inst ? [inst.id] : copies.map((c) => c.id);
    const isIsolated = !!isolated && isolated.length === ids.length && ids.every((i) => isolated.includes(i));

    return (
        <aside className="rv-inspector" aria-label="Inspector">
            <div className="rv-panel-head">
                <span className="label">{inst ? 'Instance' : 'Part'}</span>
                <span style={{ marginLeft: 'auto', display: 'flex', gap: 2 }}>
                    <button className="icon-btn" title="Frame (F)" aria-label="Frame" onClick={() => select(selection, true)}><Crosshair size={15} /></button>
                    <button className="icon-btn" title={isIsolated ? 'Show everything' : 'Isolate'} aria-label="Isolate" aria-pressed={isIsolated}
                        onClick={() => isolate(isIsolated ? null : ids)}>{isIsolated ? <Eye size={15} /> : <Focus size={15} />}</button>
                </span>
            </div>
            <div className="rv-sec">
                <h3 style={{ fontSize: 15, fontWeight: 500, overflowWrap: 'anywhere' }}>{inst ? inst.name : part.name}</h3>
                {inst && <div className="mono muted" style={{ fontSize: 11, overflowWrap: 'anywhere' }}>{inst.path}</div>}
                {!part.valid && (
                    <div className="rv-err"><span className="sev sev--major">Invalid solid</span> {part.problems.join('; ')}</div>
                )}
            </div>
            <div className="rv-sec">
                <h3>Geometry</h3>
                <dl className="rv-kv">
                    <Row k="Envelope X" v={fmtNum(d[0])} unit="mm" />
                    <Row k="Envelope Y" v={fmtNum(d[1])} unit="mm" />
                    <Row k="Envelope Z" v={fmtNum(d[2])} unit="mm" />
                    <Row k="Volume" v={fmtNum(part.volume / 1000, 3)} unit="cm³" />
                    <Row k="Surface area" v={fmtNum(part.area / 100, 2)} unit="cm²" />
                    <Row k="Centre of mass" v={part.com.map((c) => c.toFixed(2)).join(', ')} unit="mm" src={`${GEO}; uniform density, part frame`} />
                    <Row k="Faces" v={part.face_count} />
                    <Row k="Body type" v={part.geometry_type === 'BREP' ? 'B-rep solid' : 'Mesh (triangles)'} />
                    <Row k="Mass" v={part.mass === null ? '—' : fmtNum(part.mass, 4)} unit={part.mass === null ? undefined : 'kg'}
                        src={part.mass === null ? 'needs a density: material from the BOM or Library' : 'volume × density'} />
                </dl>
            </div>
            {inst && pos && (
                <div className="rv-sec">
                    <h3>Placement</h3>
                    <dl className="rv-kv">
                        <Row k="Position" v={pos.map((v) => v.toFixed(2)).join(', ')} unit="mm" src="STEP assembly transform (XCAF location)" />
                        <Row k="Instance id" v={inst.id} src="assigned at ingest" />
                    </dl>
                </div>
            )}
            <div className="rv-sec">
                <h3>Identity</h3>
                <dl className="rv-kv">
                    <Row k="Part id" v={part.id} src="assigned at ingest" />
                    <Row k="Geometry hash" v={part.hash} src="volume, area and envelope, rounded — survives renames" />
                    <Row k="Copies in assembly" v={copies.length} src="STEP assembly structure" />
                </dl>
            </div>
            {copies.length > 1 && (
                <div className="rv-sec">
                    <h3>Copies</h3>
                    <table className="rv-table">
                        <tbody>
                            {copies.map((c, k) => (
                                <tr key={c.id} data-click aria-selected={inst?.id === c.id}
                                    onClick={() => select({ kind: 'instance', id: c.id }, true)}
                                    style={inst?.id === c.id ? { fontWeight: 600 } : undefined}>
                                    <td className="muted">{k + 1}</td>
                                    <td className="mono">{c.id}</td>
                                    <td className="num">{c.transform.slice(0, 3).map((r) => r[3].toFixed(1)).join(', ')}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
            <FeatureSection graph={graph} part={part} />
            {inst && (() => {
                const mine = (graph.contacts ?? []).filter((c) => c.a === inst.id || c.b === inst.id);
                return (
                    <div className="rv-sec">
                        <h3>Contacts <span className="muted mono" style={{ fontWeight: 400 }}>{mine.length}</span></h3>
                        {mine.length === 0 ? <div className="muted">Touches nothing (gap &gt; 0.05 mm everywhere).</div> : (
                            <table className="rv-table">
                                <tbody>
                                    {mine.map((c) => {
                                        const other = c.a === inst.id ? c.b : c.a;
                                        return (
                                            <tr key={c.id} data-click onClick={() => select({ kind: 'contact', id: c.id }, true)}>
                                                <td>{instMap.get(other)?.name ?? other}</td>
                                                <td className="mono muted" style={{ fontSize: 11 }}>{c.type}</td>
                                                <td className="num">{c.fits[0] ? `${c.fits[0].clearance.toFixed(2)} clr` : ''}</td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        )}
                    </div>
                );
            })()}
            <div className="rv-sec">
                <h3>Findings</h3>
                <div className="muted">No checks have run on this revision yet.</div>
            </div>
        </aside>
    );
}
