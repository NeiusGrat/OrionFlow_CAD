/**
 * Compare lens: base revision -> this revision.
 *
 * The change list says what changed and how each part was matched (by name,
 * by geometric signature, or by similar shape with its similarity). The
 * interchangeability matrix answers, part by part, whether the old part can
 * be fitted in the new assembly, naming the interface that breaks. The 3D
 * overlay ghosts the base revision as edges over the target, with changed
 * parts solid black.
 */
import { useEffect, useMemo, useState } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { toCreasedNormals } from 'three/addons/utils/BufferGeometryUtils.js';
import { CAD_Z_UP_TO_Y_UP } from '../../lib/cadAppearance';
import {
    compareRevisions, fetchViewerGlb, getGraph,
    type CompareResult, type Finding, type ModelGraph, type PartChange, type Revision,
} from '../../services/reviewApi';
import { useReview } from '../../store/reviewStore';
import { SevMark } from './FindingPanel';

const STATUS_MARK: Record<string, string> = { unchanged: 'sev--pass', modified: 'sev--major', added: 'sev--critical', removed: 'sev--notrun' };

function Overlay({ baseGlb, targetGlb, baseGraph, targetGraph, result }: {
    baseGlb: ArrayBuffer;
    targetGlb: ArrayBuffer;
    baseGraph: ModelGraph;
    targetGraph: ModelGraph;
    result: CompareResult;
}) {
    const { camera, controls, gl, scene } = useThree() as unknown as {
        camera: THREE.PerspectiveCamera;
        controls: { target: THREE.Vector3; update: () => void } | null;
        gl: THREE.WebGLRenderer;
        scene: THREE.Scene;
    };
    const [group, setGroup] = useState<THREE.Group | null>(null);
    const selection = useReview((s) => s.selection);
    const select = useReview((s) => s.select);

    useEffect(() => {
        gl.toneMapping = THREE.NeutralToneMapping;
        const pm = new THREE.PMREMGenerator(gl);
        const env = pm.fromScene(new RoomEnvironment(), 0.04).texture;
        scene.environment = env;
        return () => { env.dispose(); pm.dispose(); scene.environment = null; };
    }, [gl, scene]);

    useEffect(() => {
        let alive = true;
        const status = new Map<string, string>();         // target part id -> status
        const removed = new Set<string>();                // base part ids
        for (const c of result.changes) {
            if (c.target) status.set(c.target, c.status);
            if (c.status === 'removed' && c.base) removed.add(c.base);
        }
        const tPart = new Map(targetGraph.instances.map((i) => [i.id, i.part_id]));
        const bPart = new Map(baseGraph.instances.map((i) => [i.id, i.part_id]));
        Promise.all([new GLTFLoader().parseAsync(baseGlb.slice(0), ''), new GLTFLoader().parseAsync(targetGlb.slice(0), '')]).then(([b, t]) => {
            if (!alive) return;
            // target: solid, changed parts in black
            t.scene.traverse((o) => {
                const m = o as THREE.Mesh;
                if (!m.isMesh) return;
                const pid = tPart.get(m.name);
                const st = pid ? status.get(pid) ?? 'unchanged' : 'unchanged';
                if (!m.geometry.attributes.normal) m.geometry = toCreasedNormals(m.geometry, Math.PI / 6);
                const color = st === 'modified' ? '#141414' : st === 'added' ? '#5C5C5C' : '#E9E9E7';
                m.material = new THREE.MeshStandardMaterial({ color, roughness: 0.82, metalness: 0, side: THREE.DoubleSide,
                    polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
                m.userData = { pid, st };
                const e = new THREE.LineSegments(new THREE.EdgesGeometry(m.geometry, 28),
                    new THREE.LineBasicMaterial({ color: st === 'modified' || st === 'added' ? '#FFFFFF' : '#1A1A1A', transparent: true, opacity: 0.5 }));
                e.raycast = () => {};
                m.add(e);
            });
            // base: edges only, removed parts dark
            const ghost = new THREE.Group();
            b.scene.updateMatrixWorld(true);
            b.scene.traverse((o) => {
                const m = o as THREE.Mesh;
                if (!m.isMesh) return;
                const gone = removed.has(bPart.get(m.name) ?? '');
                const e = new THREE.LineSegments(new THREE.EdgesGeometry(m.geometry, 28),
                    new THREE.LineBasicMaterial({ color: gone ? '#111111' : '#9A9A9A', transparent: true, opacity: gone ? 0.9 : 0.35 }));
                e.applyMatrix4(m.matrixWorld);
                e.raycast = () => {};
                ghost.add(e);
            });
            // align the base to the target by envelope centre (revisions often move their origin)
            t.scene.updateMatrixWorld(true);
            const tb = new THREE.Box3().setFromObject(t.scene);
            const bb = new THREE.Box3().setFromObject(ghost);
            ghost.position.add(tb.getCenter(new THREE.Vector3()).sub(bb.getCenter(new THREE.Vector3())));
            const root = new THREE.Group();
            root.add(t.scene, ghost);
            root.rotation.set(...CAD_Z_UP_TO_Y_UP);
            const wrap = new THREE.Group();
            wrap.add(root);
            wrap.updateMatrixWorld(true);
            const box = new THREE.Box3().setFromObject(wrap);
            const c = box.getCenter(new THREE.Vector3());
            wrap.position.set(-c.x, -box.min.y, -c.z);
            setGroup(wrap);
            const r = box.getSize(new THREE.Vector3()).length();
            camera.position.set(r * 0.9, r * 0.7, r * 0.9);
            camera.near = r / 1000;
            camera.far = r * 100;
            camera.updateProjectionMatrix();
            if (controls) { controls.target.set(0, (box.max.y - box.min.y) / 2, 0); controls.update(); }
        });
        return () => { alive = false; };
    }, [baseGlb, targetGlb, baseGraph, targetGraph, result, camera, controls]);

    // highlight the selected part
    useEffect(() => {
        if (!group) return;
        const pid = selection?.kind === 'part' ? selection.id : null;
        group.traverse((o) => {
            const m = o as THREE.Mesh;
            if (!m.isMesh || !m.userData?.st) return;
            const mat = m.material as THREE.MeshStandardMaterial;
            const dim = pid && m.userData.pid !== pid;
            mat.transparent = !!dim;
            mat.opacity = dim ? 0.25 : 1;
            mat.depthWrite = !dim;
        });
    }, [group, selection]);

    if (!group) return null;
    return (
        <primitive object={group} onClick={(e: { stopPropagation: () => void; object: THREE.Object3D; delta: number }) => {
            if (e.delta > 4) return;
            e.stopPropagation();
            const pid = e.object.userData?.pid;
            if (pid) select({ kind: 'part', id: pid });
        }} />
    );
}

function FindingList({ items, onOpen }: { items: Finding[]; onOpen: (f: Finding) => void }) {
    if (!items.length) return <div className="muted" style={{ padding: '6px 0' }}>None.</div>;
    return (
        <table className="rv-table">
            <tbody>
                {items.map((f) => (
                    <tr key={f.id} data-click onClick={() => onOpen(f)}>
                        <td style={{ width: 90 }}><SevMark s={f.severity} /></td>
                        <td>{f.title}<div className="muted" style={{ fontSize: 12 }}>{f.statement}</div></td>
                        <td className="mono muted" style={{ fontSize: 11 }}>{f.check_id}</td>
                    </tr>
                ))}
            </tbody>
        </table>
    );
}

export default function CompareLens({ rid, revisions, targetGraph, targetGlb, onOpenFinding }: {
    rid: string;
    revisions: Revision[];
    targetGraph: ModelGraph;
    targetGlb: ArrayBuffer | null;
    onOpenFinding: (f: Finding, revisionId: string) => void;
}) {
    const others = revisions.filter((r) => r.id !== rid && r.status === 'done');
    const [base, setBase] = useState<string>(others[0]?.id ?? '');
    const [result, setResult] = useState<CompareResult | null>(null);
    const [baseGraph, setBaseGraph] = useState<ModelGraph | null>(null);
    const [baseGlb, setBaseGlb] = useState<ArrayBuffer | null>(null);
    const [tab, setTab] = useState<'changes' | 'interchange' | 'findings'>('changes');
    const [error, setError] = useState('');
    const [showUnchanged, setShowUnchanged] = useState(false);
    const select = useReview((s) => s.select);
    const selection = useReview((s) => s.selection);

    useEffect(() => {
        if (!base) return;
        let alive = true;
        setResult(null);
        setError('');
        compareRevisions(base, rid).then((r) => alive && setResult(r)).catch((e) => alive && setError(String(e.message)));
        getGraph(base).then((g) => alive && setBaseGraph(g)).catch(() => {});
        fetchViewerGlb(base).then((b) => alive && setBaseGlb(b)).catch(() => {});
        return () => { alive = false; };
    }, [base, rid]);

    const changes = useMemo(() => {
        const order = { removed: 0, added: 1, modified: 2, unchanged: 3 } as const;
        return (result?.changes ?? []).filter((c) => showUnchanged || c.status !== 'unchanged')
            .sort((a, b) => order[a.status] - order[b.status] || (a.target_name ?? a.base_name ?? '').localeCompare(b.target_name ?? b.base_name ?? ''));
    }, [result, showUnchanged]);

    if (!others.length) {
        return (
            <div className="rv-page" style={{ background: 'var(--bg)' }}>
                <div className="rv-empty" style={{ marginTop: 60 }}><b>Nothing to compare with</b>Add another revision to this project and run its review.</div>
            </div>
        );
    }

    const s = result?.summary;
    const label = (c: PartChange) => c.target_name ?? c.base_name ?? '';
    const v = (x: string) => (x === 'yes' ? 'sev--pass' : x === 'no' ? 'sev--critical' : 'sev--major');

    return (
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
            <div style={{ borderBottom: '1px solid var(--line)', padding: '10px 16px', display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center' }}>
                <span className="label">Compare</span>
                <select value={base} onChange={(e) => setBase(e.target.value)} aria-label="Base revision"
                    style={{ height: 28, border: '1px solid var(--line-2)', borderRadius: 2 }}>
                    {others.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
                </select>
                <span className="mono">→ {revisions.find((r) => r.id === rid)?.label}</span>
                {result?.base.flat && <span className="mono muted" style={{ fontSize: 11 }}>base has no part names: matched by geometry</span>}
            </div>
            {error && <p className="rv-err" style={{ margin: 12 }}>{error}</p>}
            {!result && !error && <div className="rv-loading" style={{ position: 'static', padding: 40 }}>Comparing…</div>}
            {result && s && (
                <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
                    <div style={{ flex: '1 1 55%', minWidth: 0, overflowY: 'auto', padding: '12px 16px 40px', background: 'var(--bg)' }}>
                        <div className="rv-console">{[
                            '> SUMMARY',
                            `> ${s.unchanged} parts unchanged, ${s.modified} modified, ${s.added} added, ${s.removed} removed.`,
                            `> Interchangeable: ${s.yes} yes, ${s.no} no, ${s.needs_review} need review.`,
                            `> Findings: ${s.new_findings} new, ${s.fixed_findings} fixed, ${s.unchanged_findings} unchanged.`,
                        ].join('\n')}</div>
                        <div style={{ display: 'flex', gap: 2, margin: '14px 0 8px' }}>
                            {([['changes', 'Changes'], ['interchange', 'Interchangeability'], ['findings', 'Findings delta']] as const).map(([k, l]) => (
                                <button key={k} className="btn btn--ghost" aria-pressed={tab === k} onClick={() => setTab(k)}
                                    style={tab === k ? { borderColor: 'var(--text)' } : undefined}>{l}</button>
                            ))}
                            {tab === 'changes' && (
                                <label className="muted" style={{ marginLeft: 'auto', fontSize: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
                                    <input type="checkbox" checked={showUnchanged} onChange={(e) => setShowUnchanged(e.target.checked)} /> show unchanged
                                </label>
                            )}
                        </div>
                        {tab === 'changes' && (
                            <table className="rv-table">
                                <thead><tr><th></th><th>Part</th><th>Matched</th><th>What changed</th></tr></thead>
                                <tbody>
                                    {changes.map((c, k) => (
                                        <tr key={k} data-click className={selection?.kind === 'part' && selection.id === c.target ? 'is-sel' : undefined}
                                            onClick={() => c.target && select({ kind: 'part', id: c.target })}>
                                            <td style={{ width: 96 }}><span className={`sev ${STATUS_MARK[c.status]}`}>{c.status}</span></td>
                                            <td>
                                                {label(c)}
                                                {c.base_name && c.target_name && c.base_name !== c.target_name && (
                                                    <div className="mono muted" style={{ fontSize: 11 }}>was {c.base_name}</div>
                                                )}
                                            </td>
                                            <td className="mono muted" style={{ fontSize: 11 }}>{c.method ? `${c.method}${c.method === 'shape' ? ` ${Math.round((c.similarity ?? 0) * 100)}%` : ''}` : '—'}</td>
                                            <td style={{ fontSize: 12 }}>{c.details.join(' · ')}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        )}
                        {tab === 'interchange' && (
                            <table className="rv-table">
                                <thead><tr><th>Part</th><th>Old part fits?</th><th>Why</th></tr></thead>
                                <tbody>
                                    {[...result.interchangeability].sort((a, b) => ['no', 'needs review', 'yes'].indexOf(a.verdict) - ['no', 'needs review', 'yes'].indexOf(b.verdict))
                                        .map((m) => (
                                            <tr key={m.target} data-click className={selection?.kind === 'part' && selection.id === m.target ? 'is-sel' : undefined}
                                                onClick={() => select({ kind: 'part', id: m.target })}>
                                                <td>{m.name}</td>
                                                <td style={{ width: 130 }}><span className={`sev ${v(m.verdict)}`}>{m.verdict}</span></td>
                                                <td style={{ fontSize: 12 }}>{m.reason}</td>
                                            </tr>
                                        ))}
                                </tbody>
                            </table>
                        )}
                        {tab === 'findings' && (
                            <>
                                <h3 style={{ fontSize: 13, margin: '6px 0' }}>New in {result.target.label} · {result.findings.new.length}</h3>
                                <FindingList items={result.findings.new} onOpen={(f) => onOpenFinding(f, rid)} />
                                <h3 style={{ fontSize: 13, margin: '18px 0 6px' }}>Fixed since {result.base.label} · {result.findings.fixed.length}</h3>
                                <FindingList items={result.findings.fixed} onOpen={(f) => onOpenFinding(f, base)} />
                                <h3 style={{ fontSize: 13, margin: '18px 0 6px' }}>Unchanged · {result.findings.unchanged.length}</h3>
                                <FindingList items={result.findings.unchanged} onOpen={(f) => onOpenFinding(f, rid)} />
                            </>
                        )}
                    </div>
                    <div className="rv-view" style={{ flex: '1 1 45%', borderLeft: '1px solid var(--line)' }}>
                        {baseGlb && targetGlb && baseGraph ? (
                            <Canvas camera={{ fov: 35, near: 0.001, far: 100 }} dpr={[1, 2]} style={{ background: '#F6F6F6' }}
                                onPointerMissed={(e) => e.type === 'click' && select(null)}>
                                <ambientLight intensity={0.35} />
                                <directionalLight position={[3, 6, 4]} intensity={1.1} />
                                <Overlay baseGlb={baseGlb} targetGlb={targetGlb} baseGraph={baseGraph} targetGraph={targetGraph} result={result} />
                                <OrbitControls makeDefault enableDamping dampingFactor={0.12} />
                            </Canvas>
                        ) : <div className="rv-loading">Loading both revisions…</div>}
                        <div className="rv-view__hud">
                            <b>{result.base.label}</b> edges, grey · <b>{result.target.label}</b> solid<br />
                            black = modified · dark grey = added · dark edges = removed<br />
                            aligned by envelope centre
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
