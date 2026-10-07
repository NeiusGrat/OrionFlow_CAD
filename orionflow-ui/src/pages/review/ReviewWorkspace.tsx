/**
 * One revision's review: lens rail, main canvas, Inspector, status bar.
 *
 * Lenses appear here as they become real — a lens with nothing behind it is
 * not shown. Every lens reads the same Model Graph and the same selection
 * store, so switching lenses keeps what is selected.
 */
import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Box, LayoutDashboard, Search } from 'lucide-react';
import { Brand, ReviewRoot, StepList } from '../../components/Review/Shell';
import Viewer from '../../components/Review/Viewer';
import ProductTree from '../../components/Review/ProductTree';
import Inspector from '../../components/Review/Inspector';
import CommandPalette from '../../components/Review/CommandPalette';
import ContactsDrawer from '../../components/Review/ContactsDrawer';
import {
    fetchViewerGlb, fmtBytes, getGraph, getProject, getRevision, runReview,
    type ModelGraph, type Project, type Revision,
} from '../../services/reviewApi';
import { useReview } from '../../store/reviewStore';

const LENSES = [
    { key: 'overview', label: 'Overview', icon: LayoutDashboard },
    { key: 'model', label: 'Model', icon: Box },
] as const;
type LensKey = (typeof LENSES)[number]['key'];

/** What each kind of input unlocks — shown when it is missing. */
const UNLOCKS: { kind: string; label: string; unlocks: string }[] = [
    { kind: 'step', label: 'STEP assembly', unlocks: 'model graph, structure, interfaces, clearance, motion' },
    { kind: 'bom', label: 'BOM', unlocks: 'BOM ↔ CAD reconciliation, materials and mass' },
    { kind: 'pdf', label: 'Drawings / instructions (PDF)', unlocks: 'drawing ↔ geometry and instruction ↔ BOM checks' },
    { kind: 'urdf|mjcf', label: 'URDF or MJCF', unlocks: 'sim fidelity (mass, CoM, inertia, axes) and joint sweeps' },
];

function summary(g: ModelGraph, rev: Revision): string {
    const s = g.stats;
    const multi = g.parts.filter((p) => g.instances.filter((i) => i.part_id === p.id).length > 1);
    const copies = multi.reduce((a, p) => a + g.instances.filter((i) => i.part_id === p.id).length, 0);
    const invalid = g.parts.filter((p) => !p.valid);
    const lines = [
        `> SUMMARY`,
        `> ${g.source.name} was read as ${s.parts} part definitions placed ${s.instances} times` +
            (s.flat ? ' (no assembly structure in the file: one body per solid).' : ` in ${s.assemblies} assembl${s.assemblies === 1 ? 'y' : 'ies'}, ${s.max_depth} levels deep.`),
        `> ${multi.length} parts are used more than once, accounting for ${copies} of the ${s.instances} instances.`,
        ...(g.contacts ? [`> ${g.contacts.length} touching pairs: ${['cylindrical', 'coaxial-hole', 'planar', 'point'].map((t) => `${g.contacts!.filter((c) => c.type === t).length} ${t}`).join(', ')}. ${(g.features ?? []).filter((f) => f.kind === 'hole').length} holes in ${(g.features ?? []).filter((f) => f.kind === 'pattern').length} patterns.`] : []),
        invalid.length ? `> ${invalid.length} part${invalid.length === 1 ? '' : 's'} failed the solid validity check: ${invalid.map((p) => p.name).join(', ')}.`
            : `> Every solid passed the OpenCASCADE validity check.`,
        rev.git_repo ? `> Source pinned to ${rev.git_repo}@${rev.git_ref}, SHA-256 ${g.source.sha256.slice(0, 12)}…` : `> Source SHA-256 ${g.source.sha256.slice(0, 12)}…`,
    ];
    return lines.join('\n');
}

function Overview({ graph, rev }: { graph: ModelGraph; rev: Revision }) {
    const kinds = new Set(rev.files.map((f) => f.kind));
    const has = (k: string) => k.split('|').some((x) => kinds.has(x as never));
    const missing = UNLOCKS.filter((u) => !has(u.kind));
    return (
        <div className="rv-page" style={{ background: 'var(--bg)' }}>
            <div className="rv-page__in" style={{ maxWidth: 980, paddingTop: 28 }}>
                <span className="label">Overview · {rev.label}</span>
                <h1 style={{ fontSize: 26 }}>{graph.tree.name}</h1>
                <div className="rv-console" style={{ marginTop: 18 }}>{summary(graph, rev)}</div>

                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 28, marginTop: 28 }}>
                    <section>
                        <span className="label">Inputs</span>
                        <table className="rv-table" style={{ marginTop: 8 }}>
                            <tbody>
                                {UNLOCKS.map((u) => (
                                    <tr key={u.kind}>
                                        <td style={{ width: 18 }}><span className={`sev ${has(u.kind) ? 'sev--pass' : 'sev--notrun'}`} aria-label={has(u.kind) ? 'present' : 'missing'} /></td>
                                        <td>{u.label}</td>
                                        <td className="muted" style={{ fontSize: 12 }}>{has(u.kind) ? 'present' : 'missing'}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </section>
                    <section>
                        <span className="label">Checks</span>
                        <div className="rv-empty" style={{ border: '1px solid var(--line)', marginTop: 8, padding: 18 }}>
                            <b>No checks have run on this revision</b>
                            The model graph is built. Findings appear here once checks run.
                        </div>
                    </section>
                </div>

                {missing.length > 0 && (
                    <section style={{ marginTop: 28 }}>
                        <span className="label">What would make this review more complete</span>
                        <ul style={{ margin: '8px 0 0', paddingLeft: 18 }}>
                            {missing.map((u) => <li key={u.kind} style={{ margin: '4px 0' }}>Add a <b>{u.label}</b> to enable {u.unlocks}.</li>)}
                        </ul>
                    </section>
                )}

                {rev.job && (
                    <section style={{ marginTop: 28 }}>
                        <span className="label">Last run</span>
                        <div style={{ marginTop: 8 }}><StepList steps={rev.job.steps} /></div>
                    </section>
                )}

                <section style={{ marginTop: 28 }}>
                    <span className="label">Files</span>
                    <table className="rv-table" style={{ marginTop: 8 }}>
                        <thead><tr><th>File</th><th>Type</th><th className="num">Size</th><th>SHA-256</th></tr></thead>
                        <tbody>
                            {rev.files.map((f) => (
                                <tr key={f.id}>
                                    <td>{f.name}{f.name === graph.source.name && <span className="muted"> · analysed</span>}</td>
                                    <td className="mono">{f.kind.toUpperCase()}</td>
                                    <td className="num">{fmtBytes(f.size)}</td>
                                    <td className="mono muted" style={{ fontSize: 11 }} title={f.sha256}>{f.sha256.slice(0, 16)}…</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </section>

                {graph.ingest_notes.length > 0 && (
                    <section style={{ marginTop: 28 }}>
                        <span className="label">Repairs made while reading</span>
                        <ul style={{ margin: '8px 0 0', paddingLeft: 18 }}>
                            {graph.ingest_notes.map((n) => <li key={n} className="mono" style={{ fontSize: 12 }}>{n}</li>)}
                        </ul>
                    </section>
                )}
            </div>
        </div>
    );
}

export default function ReviewWorkspace() {
    const { rid = '', lens = 'model' } = useParams();
    const nav = useNavigate();
    const [project, setProject] = useState<Project | null>(null);
    const [graph, setGraph] = useState<ModelGraph | null>(null);
    const [glb, setGlb] = useState<ArrayBuffer | null>(null);
    const [error, setError] = useState('');
    const [palette, setPalette] = useState(false);
    const reset = useReview((s) => s.reset);
    const active = (LENSES.find((l) => l.key === lens)?.key ?? 'model') as LensKey;

    useEffect(() => {
        let alive = true;
        reset();
        setGraph(null);
        setGlb(null);
        setError('');
        getGraph(rid)
            .then(async (g) => {
                if (!alive) return;
                setGraph(g);
                const r = await getRevision(rid);
                getProject(r.project_id).then((p) => alive && setProject(p));
                fetchViewerGlb(rid).then((b) => alive && setGlb(b)).catch((e) => alive && setError(String(e.message)));
            })
            .catch((e) => alive && setError(String(e.message)));
        return () => {
            alive = false;
        };
    }, [rid, reset]);

    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
                e.preventDefault();
                setPalette((p) => !p);
            }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, []);

    const rev = project?.revisions.find((r) => r.id === rid) ?? null;
    const instances = useMemo(() => new Map((graph?.instances ?? []).map((i) => [i.id, i])), [graph]);
    const parts = useMemo(() => new Map((graph?.parts ?? []).map((p) => [p.id, p])), [graph]);

    return (
        <ReviewRoot>
            <header className="rv-top">
                <Brand />
                <nav className="rv-crumbs" aria-label="Project and revision">
                    <Link className="crumb" to={project ? `/review/p/${project.id}` : '/review'}>{project?.name ?? '…'}</Link>
                    <span className="sep">/</span>
                    <select value={rid} aria-label="Revision" onChange={(e) => nav(`/review/r/${e.target.value}/${active}`)}>
                        {(project?.revisions ?? []).map((r) => (
                            <option key={r.id} value={r.id} disabled={r.status !== 'done'}>{r.label}{r.status !== 'done' ? ` (${r.status})` : ''}</option>
                        ))}
                        {!project && <option value={rid}>…</option>}
                    </select>
                </nav>
                <button className="rv-search" onClick={() => setPalette(true)} aria-label="Search parts (Ctrl K)">
                    <Search size={14} /><span>Search parts</span><kbd>⌘K</kbd>
                </button>
                <button className="btn" disabled={!rev || rev.status === 'running' || rev.status === 'queued'}
                    onClick={async () => {
                        if (!rev) return;
                        await runReview(rev.id);
                        nav(`/review/p/${rev.project_id}`);
                    }}>Run review</button>
            </header>
            <div className="rv-body">
                <nav className="rv-rail" aria-label="Lenses">
                    {LENSES.map(({ key, label, icon: Icon }) => (
                        <Link key={key} to={`/review/r/${rid}/${key}`} aria-current={active === key ? 'page' : undefined}>
                            <Icon />{label}
                        </Link>
                    ))}
                </nav>
                <main className="rv-main">
                    {error && <div className="rv-loading"><span className="rv-err">{error}</span></div>}
                    {!error && !graph && <div className="rv-loading">Loading the model graph…</div>}
                    {graph && active === 'overview' && rev && <Overview graph={graph} rev={rev} />}
                    {graph && active === 'model' && (
                        <>
                            <ProductTree tree={graph.tree} parts={graph.parts} instances={graph.instances} />
                            <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
                                {glb ? (
                                    <Viewer glb={glb} instances={instances} parts={parts} features={graph.features ?? []} contacts={graph.contacts ?? []} />
                                ) : (
                                    <div className="rv-view"><div className="rv-loading">Loading the 3D model…</div></div>
                                )}
                                <ContactsDrawer contacts={graph.contacts ?? []} instances={instances} />
                            </div>
                        </>
                    )}
                </main>
                {graph && <Inspector graph={graph} />}
            </div>
            <footer className="rv-status">
                {graph ? (
                    <>
                        <span><b>{graph.stats.instances}</b> instances</span>
                        <span><b>{graph.stats.parts}</b> parts</span>
                        <span><b>{graph.stats.features ?? 0}</b> features</span>
                        <span><b>{graph.stats.contacts ?? 0}</b> contacts</span>
                        <span><b>0</b> checks run</span>
                        <span>units mm</span>
                        <span className="push">graph schema {graph.schema_version}</span>
                        <span title={graph.source.sha256}>{graph.source.name} · {graph.source.sha256.slice(0, 10)}</span>
                    </>
                ) : <span>…</span>}
            </footer>
            {palette && graph && (
                <CommandPalette graph={graph} onClose={() => setPalette(false)} onPick={() => active !== 'model' && nav(`/review/r/${rid}/model`)} />
            )}
        </ReviewRoot>
    );
}
