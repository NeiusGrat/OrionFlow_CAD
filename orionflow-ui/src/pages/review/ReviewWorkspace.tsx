/**
 * One revision's review: lens rail, main canvas, Inspector, status bar.
 *
 * Lenses appear here as they become real — a lens with nothing behind it is
 * not shown. Every lens reads the same Model Graph and the same selection
 * store, so switching lenses keeps what is selected.
 */
import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Box, ClipboardList, Cpu, GitCompare, LayoutDashboard, ListChecks, Search } from 'lucide-react';
import { Brand, ReviewRoot, StepList } from '../../components/Review/Shell';
import Viewer from '../../components/Review/Viewer';
import ProductTree from '../../components/Review/ProductTree';
import Inspector from '../../components/Review/Inspector';
import CommandPalette from '../../components/Review/CommandPalette';
import ContactsDrawer from '../../components/Review/ContactsDrawer';
import FindingsLens, { RunStatus } from '../../components/Review/FindingsLens';
import BomLens from '../../components/Review/BomLens';
import CompareLens from '../../components/Review/CompareLens';
import SimLens from '../../components/Review/SimLens';
import FindingPanel, { SevMark } from '../../components/Review/FindingPanel';
import {
    downloadReportJson, fetchViewerGlb, fmtBytes, getBom, getGraph, getProject, getRevision, getSim, listFindings, listOverrides, runReview, SEVERITIES,
    type BomPayload, type PartOverride, type SimPayload, type Finding, type FindingsPayload, type ModelGraph, type Project, type Revision,
} from '../../services/reviewApi';
import { useReview } from '../../store/reviewStore';

const LENSES = [
    { key: 'overview', label: 'Overview', icon: LayoutDashboard },
    { key: 'model', label: 'Model', icon: Box },
    { key: 'bom', label: 'BOM', icon: ClipboardList },
    { key: 'compare', label: 'Compare', icon: GitCompare },
    { key: 'sim', label: 'Sim', icon: Cpu },
    { key: 'findings', label: 'Findings', icon: ListChecks },
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

function Overview({ graph, rev, findings, onOpen }: { graph: ModelGraph; rev: Revision; findings: FindingsPayload | null; onOpen: (f: Finding) => void }) {
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
                        <span className="label">Readiness</span>
                        {findings ? (
                            <>
                                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', border: '1px solid var(--line)', marginTop: 8 }}>
                                    {SEVERITIES.map((s) => (
                                        <div key={s} style={{ padding: '10px 12px', borderRight: '1px solid var(--line)' }}>
                                            <SevMark s={s} />
                                            <div className="mono" style={{ fontSize: 24, marginTop: 4 }}>{findings.summary[s]}</div>
                                        </div>
                                    ))}
                                </div>
                                <p className="mono muted" style={{ fontSize: 11, margin: '6px 0 0' }}>
                                    open + deferred · {findings.check_runs.filter((r) => r.status === 'passed' || r.status === 'findings').length} checks run ·{' '}
                                    {findings.check_runs.filter((r) => r.status === 'not_run').length} not run
                                </p>
                            </>
                        ) : <div className="rv-empty" style={{ border: '1px solid var(--line)', marginTop: 8 }}>Loading findings…</div>}
                    </section>
                </div>

                {findings && findings.findings.length > 0 && (
                    <section style={{ marginTop: 28 }}>
                        <span className="label">Top findings</span>
                        <table className="rv-table" style={{ marginTop: 8 }}>
                            <tbody>
                                {findings.findings.filter((f) => f.status === 'open').slice(0, 5).map((f) => (
                                    <tr key={f.id} data-click onClick={() => onOpen(f)}>
                                        <td style={{ width: 92 }}><SevMark s={f.severity} /></td>
                                        <td>{f.title}<div className="muted" style={{ fontSize: 12 }}>{f.statement}</div></td>
                                        <td className="mono muted" style={{ fontSize: 11 }}>{f.check_id}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </section>
                )}

                {findings && (
                    <section style={{ marginTop: 28 }}>
                        <span className="label">What ran</span>
                        <table className="rv-table" style={{ marginTop: 8 }}>
                            <tbody>
                                {findings.check_runs.map((r) => (
                                    <tr key={r.check_id}>
                                        <td className="mono" style={{ fontSize: 11.5, width: 130 }}>{r.check_id}</td>
                                        <td>{r.title}</td>
                                        <td><RunStatus r={r} /></td>
                                        <td className="muted" style={{ fontSize: 12 }}>{r.status === 'not_run' ? r.reason : ''}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </section>
                )}

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
    const [params, setParams] = useSearchParams();
    const [project, setProject] = useState<Project | null>(null);
    const [graph, setGraph] = useState<ModelGraph | null>(null);
    const [glb, setGlb] = useState<ArrayBuffer | null>(null);
    const [error, setError] = useState('');
    const [palette, setPalette] = useState(false);
    const [findings, setFindings] = useState<FindingsPayload | null>(null);
    const [exporting, setExporting] = useState(false);
    const [bom, setBom] = useState<BomPayload | null>(null);
    const [sim, setSim] = useState<SimPayload | null>(null);
    const [overrides, setOverrides] = useState<PartOverride[]>([]);
    const selection = useReview((s) => s.selection);
    const select = useReview((s) => s.select);
    const reset = useReview((s) => s.reset);
    const active = (LENSES.find((l) => l.key === lens)?.key ?? 'model') as LensKey;

    useEffect(() => {
        let alive = true;
        reset();
        setGraph(null);
        setGlb(null);
        setFindings(null);
        setBom(null);
        setSim(null);
        setError('');
        getGraph(rid)
            .then(async (g) => {
                if (!alive) return;
                setGraph(g);
                const r = await getRevision(rid);
                getProject(r.project_id).then((p) => alive && setProject(p));
                fetchViewerGlb(rid).then((b) => alive && setGlb(b)).catch((e) => alive && setError(String(e.message)));
                listFindings(rid).then((f) => alive && setFindings(f)).catch(() => alive && setFindings(null));
                getBom(rid).then((b) => alive && setBom(b)).catch(() => alive && setBom(null));
                getSim(rid).then((x) => alive && setSim(x)).catch(() => alive && setSim({ sim: null }));
                listOverrides(r.project_id).then((o) => alive && setOverrides(o)).catch(() => {});
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

    useEffect(() => {
        const f = params.get('f');
        if (!f || !findings) return;
        if (findings.findings.some((x) => x.id === f)) select({ kind: 'finding', id: f });
        setParams({}, { replace: true });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [findings]);

    const rev = project?.revisions.find((r) => r.id === rid) ?? null;
    const selectedFinding = selection?.kind === 'finding' ? findings?.findings.find((f) => f.id === selection.id) : undefined;
    const onFindingChanged = (f: Finding) =>
        setFindings((d) => d && { ...d, findings: d.findings.map((x) => (x.id === f.id ? { ...x, ...f } : x)) });
    // a BOM pairing re-ran the checks and re-derived materials and masses: refresh both (the GLB is unchanged)
    const onBomChanged = (b: BomPayload) => {
        setBom(b);
        listFindings(rid).then(setFindings).catch(() => {});
        getGraph(rid).then(setGraph).catch(() => {});
    };
    // a sim mapping or a stated mass re-derived masses and re-ran the checks: refresh what depends on them
    const onSimChanged = (x?: SimPayload, ov?: PartOverride[]) => {
        if (x) setSim(x); else getSim(rid).then(setSim).catch(() => {});
        if (ov) setOverrides(ov);
        listFindings(rid).then(setFindings).catch(() => {});
        getGraph(rid).then(setGraph).catch(() => {});
        getBom(rid).then(setBom).catch(() => {});
    };
    const exportJson = async () => {
        if (!rev || !project) return;
        setExporting(true);
        try {
            await downloadReportJson(rid, `orionflow-review-${project.name}-${rev.label}.json`.replace(/\s+/g, '_'));
        } catch (e) {
            setError(String((e as Error).message));
        } finally {
            setExporting(false);
        }
    };
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
                    {graph && active === 'overview' && rev && (
                        <Overview graph={graph} rev={rev} findings={findings}
                            onOpen={(f) => { select({ kind: 'finding', id: f.id }); nav(`/review/r/${rid}/findings`); }} />
                    )}
                    {graph && active === 'bom' && (bom
                        ? <BomLens rid={rid} data={bom} onChanged={onBomChanged}
                            filename={`bom-reconciled-${project?.name ?? 'project'}-${rev?.label ?? ''}`.replace(/\s+/g, '_')} />
                        : <div className="rv-loading">Loading the BOM…</div>)}
                    {graph && active === 'compare' && project && (
                        <CompareLens rid={rid} revisions={project.revisions} targetGraph={graph} targetGlb={glb}
                            onOpenFinding={(f, revId) => {
                                if (revId === rid) {
                                    select({ kind: 'finding', id: f.id });
                                    nav(`/review/r/${rid}/findings`);
                                } else nav(`/review/r/${revId}/findings?f=${f.id}`);
                            }} />
                    )}
                    {graph && active === 'sim' && (sim && project
                        ? <SimLens rid={rid} pid={project.id} graph={graph} data={sim} overrides={overrides} onChanged={onSimChanged} />
                        : <div className="rv-loading">Loading the sim comparison…</div>)}
                    {graph && active === 'findings' && (findings
                        ? <FindingsLens data={findings} onExport={exportJson} exporting={exporting} />
                        : <div className="rv-loading">Loading findings…</div>)}
                    {graph && active === 'model' && (
                        <>
                            <ProductTree tree={graph.tree} parts={graph.parts} instances={graph.instances} />
                            <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
                                {glb ? (
                                    <Viewer glb={glb} instances={instances} parts={parts} features={graph.features ?? []} contacts={graph.contacts ?? []}
                                        findings={findings?.findings ?? []} />
                                ) : (
                                    <div className="rv-view"><div className="rv-loading">Loading the 3D model…</div></div>
                                )}
                                <ContactsDrawer contacts={graph.contacts ?? []} instances={instances} />
                            </div>
                        </>
                    )}
                </main>
                {graph && (selectedFinding
                    ? <FindingPanel finding={selectedFinding} graph={graph} onChanged={onFindingChanged}
                        onJump={() => active !== 'model' && nav(`/review/r/${rid}/model`)} />
                    : <Inspector graph={graph} findings={findings?.findings ?? []} />)}
            </div>
            <footer className="rv-status">
                {graph ? (
                    <>
                        <span><b>{graph.stats.instances}</b> instances</span>
                        <span><b>{graph.stats.parts}</b> parts</span>
                        <span><b>{graph.stats.features ?? 0}</b> features</span>
                        <span><b>{graph.stats.contacts ?? 0}</b> contacts</span>
                        <span><b>{findings ? findings.check_runs.filter((r) => r.status === 'passed' || r.status === 'findings').length : 0}</b> checks run</span>
                        {findings && <span><b>{findings.summary.open}</b> open findings</span>}
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
