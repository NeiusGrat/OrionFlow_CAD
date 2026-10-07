/**
 * The Review viewport.
 *
 * The GLB has one node per instance, named by the instance id, and one mesh
 * per part shared by its copies — so a pick resolves straight to the Model
 * Graph and the selection store, with no name matching.
 *
 * The look is a technical illustration, in black and white only: matte light
 * parts with drawn edges; the selection solid black with white edges; when
 * something is selected every other part drops to light grey at 35 %.
 *
 * STEP is Z-up in millimetres, the GLB is metres; three.js is Y-up, so the
 * model is rotated by CAD_Z_UP_TO_Y_UP and stood on the ground, centred.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import { Grid, Html, OrbitControls } from '@react-three/drei';
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { toCreasedNormals } from 'three/addons/utils/BufferGeometryUtils.js';
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib';
import { CAD_Z_UP_TO_Y_UP } from '../../lib/cadAppearance';
import { useReview } from '../../store/reviewStore';
import type { Finding, GraphContact, GraphFeature, GraphInstance, GraphPart, HoleFeature } from '../../services/reviewApi';

export type ViewName = 'iso' | 'front' | 'top' | 'right';

interface Props {
    glb: ArrayBuffer;
    instances: Map<string, GraphInstance>;
    parts: Map<string, GraphPart>;
    features: GraphFeature[];
    contacts: GraphContact[];
    findings?: Finding[];
    dark?: boolean;
}

/** part-frame point (mm) -> assembly frame (m), through the instance's 4x4 */
function place(T: number[][], p: number[]): THREE.Vector3 {
    return new THREE.Vector3(
        (T[0][0] * p[0] + T[0][1] * p[1] + T[0][2] * p[2] + T[0][3]) / 1000,
        (T[1][0] * p[0] + T[1][1] * p[1] + T[1][2] * p[2] + T[1][3]) / 1000,
        (T[2][0] * p[0] + T[2][1] * p[1] + T[2][2] * p[2] + T[2][3]) / 1000,
    );
}
function turn(T: number[][], d: number[]): THREE.Vector3 {
    return new THREE.Vector3(
        T[0][0] * d[0] + T[0][1] * d[1] + T[0][2] * d[2],
        T[1][0] * d[0] + T[1][1] * d[1] + T[1][2] * d[2],
        T[2][0] * d[0] + T[2][1] * d[1] + T[2][2] * d[2],
    ).normalize();
}

/** Ring of radius r (m) around axis through c, as line-segment pairs. */
function ring(c: THREE.Vector3, axis: THREE.Vector3, r: number, out: number[]) {
    const ref = Math.abs(axis.x) < 0.9 ? new THREE.Vector3(1, 0, 0) : new THREE.Vector3(0, 1, 0);
    const u = new THREE.Vector3().crossVectors(axis, ref).normalize();
    const v = new THREE.Vector3().crossVectors(axis, u);
    const n = 32;
    for (let k = 0; k < n; k++) {
        for (const t of [k, k + 1]) {
            const a = (t / n) * Math.PI * 2;
            const q = c.clone().addScaledVector(u, Math.cos(a) * r).addScaledVector(v, Math.sin(a) * r);
            out.push(q.x, q.y, q.z);
        }
    }
}

const C = {
    part: new THREE.Color('#E9E9E7'),
    partHover: new THREE.Color('#C9C9C6'),
    context: new THREE.Color('#D4D4D2'),
    selected: new THREE.Color('#141414'),
    edge: new THREE.Color('#1A1A1A'),
    edgeSelected: new THREE.Color('#FFFFFF'),
};

interface Item {
    id: string;
    mesh: THREE.Mesh;
    edges: THREE.LineSegments;
    home: THREE.Vector3;          // local position before explode
    dir: THREE.Vector3;           // explode direction (local)
}

function Lights() {
    const { gl, scene } = useThree();
    useEffect(() => {
        gl.toneMapping = THREE.NeutralToneMapping;
        gl.toneMappingExposure = 1.0;
        gl.localClippingEnabled = true;
        const pm = new THREE.PMREMGenerator(gl);
        const env = pm.fromScene(new RoomEnvironment(), 0.04).texture;
        scene.environment = env;
        return () => {
            env.dispose();
            pm.dispose();
            scene.environment = null;
        };
    }, [gl, scene]);
    return (
        <>
            <ambientLight intensity={0.35} />
            <directionalLight position={[3, 6, 4]} intensity={1.1} />
            <directionalLight position={[-4, 2, -3]} intensity={0.35} />
        </>
    );
}

function Model({ glb, instances, parts, features, contacts, findings = [], explode, section, view, viewTick }: Props & {
    explode: number;
    section: number | null;
    view: ViewName;
    viewTick: number;
}) {
    const { camera, controls, size } = useThree() as unknown as {
        camera: THREE.PerspectiveCamera;
        controls: OrbitControlsImpl | null;
        size: { width: number; height: number };
    };
    const selection = useReview((s) => s.selection);
    const hovered = useReview((s) => s.hovered);
    const hidden = useReview((s) => s.hidden);
    const isolated = useReview((s) => s.isolated);
    const fitRequest = useReview((s) => s.fitRequest);
    const select = useReview((s) => s.select);
    const hover = useReview((s) => s.hover);
    const hoveredFeature = useReview((s) => s.hoveredFeature);
    const showContacts = useReview((s) => s.showContacts);
    const outer = useRef<THREE.Group>(null);
    const [root, setRoot] = useState<THREE.Group | null>(null);
    const [items, setItems] = useState<Item[]>([]);
    const [extent, setExtent] = useState(1);
    const clip = useMemo(() => new THREE.Plane(new THREE.Vector3(0, -1, 0), 0), []);

    // ---- parse once ----------------------------------------------------------
    useEffect(() => {
        let alive = true;
        new GLTFLoader().parseAsync(glb.slice(0), '').then((gltf) => {
            if (!alive) return;
            const edgeCache = new Map<string, THREE.EdgesGeometry>();
            const list: Item[] = [];
            gltf.scene.traverse((o) => {
                const m = o as THREE.Mesh;
                if (!m.isMesh) return;
                const id = m.name;
                if (!instances.has(id)) return;
                const key = m.geometry.uuid;
                if (!m.geometry.attributes.normal) m.geometry = toCreasedNormals(m.geometry, Math.PI / 6);
                let eg = edgeCache.get(key);
                if (!eg) {
                    eg = new THREE.EdgesGeometry(m.geometry, 28);
                    edgeCache.set(key, eg);
                }
                m.material = new THREE.MeshStandardMaterial({
                    color: C.part.clone(), roughness: 0.82, metalness: 0, side: THREE.DoubleSide,
                    polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1,
                });
                const edges = new THREE.LineSegments(eg, new THREE.LineBasicMaterial({ color: C.edge.clone(), transparent: true, opacity: 0.55 }));
                edges.raycast = () => {};
                m.add(edges);
                list.push({ id, mesh: m, edges, home: m.position.clone(), dir: new THREE.Vector3() });
            });
            // explode direction: from the assembly centre to each instance's centre, in the parent's frame
            gltf.scene.updateMatrixWorld(true);
            const box = new THREE.Box3().setFromObject(gltf.scene);
            const centre = box.getCenter(new THREE.Vector3());
            for (const it of list) {
                const d = new THREE.Box3().setFromObject(it.mesh).getCenter(new THREE.Vector3()).sub(centre);
                const len = d.length();
                const parent = it.mesh.parent;
                if (parent && len > 0) {
                    // transformDirection normalises, so restore the distance after
                    d.transformDirection(new THREE.Matrix4().copy(parent.matrixWorld).invert()).multiplyScalar(len);
                }
                it.dir.copy(d);
            }
            setExtent(box.getSize(new THREE.Vector3()).length() || 1);
            setItems(list);
            setRoot(gltf.scene);
        });
        return () => {
            alive = false;
        };
    }, [glb, instances]);

    // ---- centre on the ground ------------------------------------------------
    useEffect(() => {
        const g = outer.current;
        if (!g || !root) return;
        g.position.set(0, 0, 0);
        g.updateMatrixWorld(true);
        const box = new THREE.Box3().setFromObject(g);
        const c = box.getCenter(new THREE.Vector3());
        g.position.set(-c.x, -box.min.y, -c.z);
        g.updateMatrixWorld(true);
    }, [root]);

    const selectedIds = useMemo(() => {
        if (!selection) return new Set<string>();
        if (selection.kind === 'instance') return new Set([selection.id]);
        if (selection.kind === 'contact') {
            const c = contacts.find((x) => x.id === selection.id);
            return new Set(c ? [c.a, c.b] : []);
        }
        if (selection.kind === 'finding') {
            const f = findings.find((x) => x.id === selection.id);
            const ids = new Set<string>();
            for (const e of f?.evidence ?? []) {
                if (e.type === 'instance' && e.id) ids.add(e.id);
                if (e.type === 'contact' && e.id) {
                    const c = contacts.find((x) => x.id === e.id);
                    if (c) { ids.add(c.a); ids.add(c.b); }
                }
                if (e.type === 'part' && e.id) for (const i of instances.values()) if (i.part_id === e.id) ids.add(i.id);
            }
            return ids;
        }
        return new Set([...instances.values()].filter((i) => i.part_id === selection.id).map((i) => i.id));
    }, [selection, instances, contacts, findings]);

    // measurement points of the selected finding (assembly frame, mm -> m)
    const evidencePoints = useMemo(() => {
        if (selection?.kind !== 'finding') return [];
        const f = findings.find((x) => x.id === selection.id);
        const out: { p: THREE.Vector3; label: string }[] = [];
        for (const e of f?.evidence ?? []) {
            if (e.type !== 'measurement' || !e.points) continue;
            for (const q of e.points.slice(0, 12)) {
                out.push({
                    p: new THREE.Vector3(q[0] / 1000, q[1] / 1000, q[2] / 1000),
                    label: e.value !== undefined && e.value !== null ? `${Number(e.value.toPrecision(4))} ${e.unit ?? ''}`.trim() : (e.label ?? ''),
                });
            }
        }
        return out;
    }, [selection, findings]);

    // ---- camera framing ---------------------------------------------------------
    const frame = (targets: THREE.Object3D[], dir?: THREE.Vector3) => {
        if (!targets.length) return;
        const box = new THREE.Box3();
        for (const t of targets) box.expandByObject(t);
        if (box.isEmpty()) return;
        const sphere = box.getBoundingSphere(new THREE.Sphere());
        const fov = (camera.fov * Math.PI) / 180;
        const aspect = size.width / Math.max(1, size.height);
        const fit = Math.max(sphere.radius / Math.sin(fov / 2), sphere.radius / Math.sin(Math.atan(Math.tan(fov / 2) * aspect)));
        const d = (dir ?? camera.position.clone().sub(controls?.target ?? new THREE.Vector3())).normalize();
        camera.position.copy(sphere.center).addScaledVector(d, fit * 1.15);
        camera.near = Math.max(fit / 1000, 1e-4);
        camera.far = fit * 100;
        camera.updateProjectionMatrix();
        if (controls) {
            controls.target.copy(sphere.center);
            controls.update();
        }
    };

    const visibleObjects = () => items.filter((i) => i.mesh.visible).map((i) => i.mesh);

    useEffect(() => {
        if (!items.length) return;
        // first view: the current selection if there is one (a finding opened with "Show in 3D"), else everything
        const sel = items.filter((i) => selectedIds.has(i.id)).map((i) => i.mesh);
        frame(sel.length ? sel : visibleObjects(), new THREE.Vector3(1, 0.75, 1));
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [items.length]);

    useEffect(() => {
        if (!items.length || fitRequest === 0) return;
        const sel = items.filter((i) => selectedIds.has(i.id));
        frame(sel.length ? sel.map((s) => s.mesh) : visibleObjects());
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [fitRequest]);

    useEffect(() => {
        if (!items.length || viewTick === 0) return;
        const dirs: Record<ViewName, THREE.Vector3> = {
            iso: new THREE.Vector3(1, 0.75, 1),
            front: new THREE.Vector3(0, 0, 1),
            top: new THREE.Vector3(0, 1, 0.0001),
            right: new THREE.Vector3(1, 0, 0),
        };
        frame(visibleObjects(), dirs[view]);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [viewTick]);

    // ---- explode ----------------------------------------------------------------
    useEffect(() => {
        for (const it of items) it.mesh.position.copy(it.home).addScaledVector(it.dir, explode * 0.9);
    }, [items, explode]);

    // ---- section plane (horizontal, height as a fraction of the model) -----------
    useEffect(() => {
        const g = outer.current;
        if (!g) return;
        if (section !== null) {
            const box = new THREE.Box3().setFromObject(g);
            clip.constant = box.min.y + (box.max.y - box.min.y) * section;
        }
        for (const it of items) {
            const mats = [it.mesh.material as THREE.Material, it.edges.material as THREE.Material];
            for (const m of mats) {
                m.clippingPlanes = section === null ? null : [clip];
                m.clipShadows = true;
                m.needsUpdate = true;
            }
        }
    }, [items, section, clip]);

    // ---- selection / hover / visibility styling ------------------------------------
    useEffect(() => {
        const any = selectedIds.size > 0;
        const iso = isolated ? new Set(isolated) : null;
        for (const it of items) {
            const mat = it.mesh.material as THREE.MeshStandardMaterial;
            const em = it.edges.material as THREE.LineBasicMaterial;
            const sel = selectedIds.has(it.id);
            it.mesh.visible = !hidden.has(it.id) && (!iso || iso.has(it.id));
            if (sel) {
                mat.color.copy(C.selected);
                mat.transparent = false; mat.opacity = 1; mat.depthWrite = true;
                em.color.copy(C.edgeSelected); em.opacity = 0.9;
            } else if (any) {
                mat.color.copy(it.id === hovered ? C.partHover : C.context);
                mat.transparent = true; mat.opacity = 0.35; mat.depthWrite = false;
                em.color.copy(C.edge); em.opacity = 0.18;
            } else {
                mat.color.copy(it.id === hovered ? C.partHover : C.part);
                mat.transparent = false; mat.opacity = 1; mat.depthWrite = true;
                em.color.copy(C.edge); em.opacity = 0.55;
            }
            mat.needsUpdate = true;
        }
    }, [items, selectedIds, hovered, hidden, isolated]);

    // ---- leader callout on the selection -------------------------------------------
    const callout = useMemo(() => {
        if (!selection || !items.length) return null;
        const sel = items.filter((i) => selectedIds.has(i.id) && i.mesh.visible);
        if (!sel.length || !outer.current) return null;
        const box = new THREE.Box3();
        for (const s of sel) box.expandByObject(s.mesh);
        const at = new THREE.Vector3(box.max.x, box.max.y, (box.min.z + box.max.z) / 2);
        outer.current.worldToLocal(at);
        const inst = instances.get(sel[0].id);
        const part = inst ? parts.get(inst.part_id) : undefined;
        const dims = part ? [...part.bbox.max].map((v, k) => v - part.bbox.min[k]).sort((a, b) => b - a) : [];
        if (selection.kind === 'finding') return null;        // a finding labels its own measurement points
        const contact = selection.kind === 'contact' ? contacts.find((x) => x.id === selection.id) : undefined;
        const fit = contact?.fits[0];
        const label = contact
            ? [contact.type, fit ? `Ø${fit.hole_diameter.toFixed(2)} / Ø${fit.shaft_diameter.toFixed(2)}` : '',
                contact.min_distance === null ? '' : `${contact.min_distance.toFixed(3)} mm`].filter(Boolean).join('  ')
            : selection.kind === 'part'
            ? `${part?.name ?? ''} ×${sel.length}`
            : `${inst?.name ?? ''}${dims.length ? `  ${dims.map((d) => d.toFixed(1)).join(' × ')} mm` : ''}`;
        if (contact?.point && explode === 0) {
            const cp = new THREE.Vector3(contact.point[0] / 1000, contact.point[1] / 1000, contact.point[2] / 1000);
            outer.current.updateMatrixWorld(true);
            const inner = outer.current.children[0];
            return { at: outer.current.worldToLocal(inner.localToWorld(cp)), label };
        }
        return { at, label };
         
    }, [selection, selectedIds, items, explode, instances, parts, contacts]);

    // ---- contact markers (assembly frame, metres) -------------------------------------
    const markers = useMemo(() => {
        const pts = contacts.filter((c) => c.point);
        const pos = new Float32Array(pts.length * 3);
        pts.forEach((c, k) => pos.set([c.point![0] / 1000, c.point![1] / 1000, c.point![2] / 1000], k * 3));
        const g = new THREE.BufferGeometry();
        g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
        return { geometry: g, ids: pts.map((c) => c.id) };
    }, [contacts]);

    // ---- hole rings on the selected part / instance ------------------------------------
    const holeRings = useMemo(() => {
        if (!selection || selection.kind === 'contact' || selection.kind === 'finding') return null;
        const ids = [...selectedIds];
        if (ids.length > 24) return null;
        const segs: number[] = [];
        const hot: number[] = [];
        let label: { at: THREE.Vector3; text: string } | null = null;
        for (const iid of ids) {
            const inst = instances.get(iid);
            if (!inst) continue;
            for (const f of features) {
                if (f.part_id !== inst.part_id || f.kind !== 'hole') continue;
                const h = f as HoleFeature;
                const ax = turn(inst.transform, h.axis);
                const c = place(inst.transform, h.center);
                const half = h.depth / 2000;
                const target = f.id === hoveredFeature ? hot : segs;
                for (const sgn of [-1, 1]) ring(c.clone().addScaledVector(ax, sgn * half), ax, h.diameter / 2000, target);
                if (f.id === hoveredFeature && !label) {
                    label = { at: c.clone().addScaledVector(ax, half), text: `Ø${h.diameter.toFixed(2)} ${h.through ? 'THRU' : `↧ ${h.depth.toFixed(2)}`}` };
                }
            }
        }
        const mk = (arr: number[]) => {
            const g = new THREE.BufferGeometry();
            g.setAttribute('position', new THREE.Float32BufferAttribute(arr, 3));
            return g;
        };
        return { all: mk(segs), hot: mk(hot), label };
    }, [selection, selectedIds, instances, features, hoveredFeature]);

    if (!root) return null;
    return (
        <group ref={outer}>
            <group rotation={CAD_Z_UP_TO_Y_UP}>
                <primitive
                    object={root}
                    onClick={(e: { stopPropagation: () => void; object: THREE.Object3D; delta: number }) => {
                        if (e.delta > 4) return;      // a drag, not a click
                        e.stopPropagation();
                        const id = e.object.name;
                        if (instances.has(id)) select({ kind: 'instance', id });
                    }}
                    onPointerOver={(e: { stopPropagation: () => void; object: THREE.Object3D }) => {
                        e.stopPropagation();
                        if (instances.has(e.object.name)) hover(e.object.name);
                    }}
                    onPointerOut={() => hover(null)}
                />
                {explode === 0 && evidencePoints.map((m, k) => (
                    <group key={k} position={m.p}>
                        <mesh renderOrder={20}>
                            <sphereGeometry args={[extent / 400, 12, 12]} />
                            <meshBasicMaterial color="#111111" depthTest={false} />
                        </mesh>
                        {m.label && k < 4 && (
                            <Html zIndexRange={[12, 0]} style={{ pointerEvents: 'none' }}>
                                <div className="rv-callout"><span>{m.label}</span></div>
                            </Html>
                        )}
                    </group>
                ))}
                {showContacts && explode === 0 && markers.ids.length > 0 && (
                    <points
                        geometry={markers.geometry}
                        renderOrder={10}
                        onClick={(e: { stopPropagation: () => void; index?: number; delta: number }) => {
                            if (e.delta > 4 || e.index === undefined) return;
                            e.stopPropagation();
                            select({ kind: 'contact', id: markers.ids[e.index] }, true);
                        }}
                    >
                        <pointsMaterial color="#111111" size={7} sizeAttenuation={false} depthTest={false} transparent opacity={0.9} />
                    </points>
                )}
                {holeRings && explode === 0 && (
                    <>
                        <lineSegments geometry={holeRings.all} renderOrder={11}>
                            <lineBasicMaterial color="#FFFFFF" depthTest={false} transparent opacity={0.85} />
                        </lineSegments>
                        <lineSegments geometry={holeRings.hot} renderOrder={12}>
                            <lineBasicMaterial color="#111111" depthTest={false} />
                        </lineSegments>
                        {holeRings.label && (
                            <Html position={holeRings.label.at} zIndexRange={[11, 0]} style={{ pointerEvents: 'none' }}>
                                <div className="rv-callout"><span>{holeRings.label.text}</span></div>
                            </Html>
                        )}
                    </>
                )}
            </group>
            {callout && (
                <Html position={callout.at} zIndexRange={[10, 0]} style={{ pointerEvents: 'none' }}>
                    <div className="rv-callout"><span>{callout.label}</span></div>
                </Html>
            )}
            <Grid
                position={[0, 0, 0]}
                args={[extent * 6, extent * 6]}
                cellSize={extent / 40}
                sectionSize={extent / 8}
                cellColor="#D8D8D6"
                sectionColor="#C4C4C2"
                fadeDistance={extent * 4}
                infiniteGrid
            />
        </group>
    );
}

export default function Viewer(props: Props) {
    const [explode, setExplode] = useState(0);
    const [section, setSection] = useState<number | null>(null);
    const [view, setView] = useState<ViewName>('iso');
    const [viewTick, setViewTick] = useState(0);
    const select = useReview((s) => s.select);
    const requestFit = useReview((s) => s.requestFit);
    const showAll = useReview((s) => s.showAll);
    const showContacts = useReview((s) => s.showContacts);
    const setShowContacts = useReview((s) => s.setShowContacts);

    const go = (v: ViewName) => {
        setView(v);
        setViewTick((t) => t + 1);
    };

    // keyboard: F fit, X explode toggle, S section toggle, Esc clear
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            const t = e.target as HTMLElement;
            if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
            if (e.metaKey || e.ctrlKey || e.altKey) return;
            const k = e.key.toLowerCase();
            if (k === 'f') requestFit();
            else if (k === 'x') setExplode((x) => (x > 0 ? 0 : 0.35));
            else if (k === 's') setSection((s) => (s === null ? 0.5 : null));
            else if (k === 'c') setShowContacts(!useReview.getState().showContacts);
            else if (k === 'escape') select(null);
            else return;
            e.preventDefault();
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [requestFit, select, setShowContacts]);

    return (
        <div className="rv-view">
            <Canvas
                camera={{ fov: 35, position: [1, 1, 1], near: 0.001, far: 100 }}
                dpr={[1, 2]}
                gl={{ antialias: true, preserveDrawingBuffer: false }}
                onPointerMissed={(e) => {
                    if (e.type === 'click') select(null);
                }}
                style={{ background: props.dark ? '#161616' : '#F6F6F6' }}
            >
                <Lights />
                <Model {...props} explode={explode} section={section} view={view} viewTick={viewTick} />
                <OrbitControls makeDefault enableDamping dampingFactor={0.12} />
            </Canvas>
            <div className="rv-view__tools" role="toolbar" aria-label="View tools">
                <button className="btn" onClick={() => requestFit()} title="Fit (F)">Fit</button>
                <button className="btn" onClick={() => go('iso')}>Iso</button>
                <button className="btn" onClick={() => go('front')}>Front</button>
                <button className="btn" onClick={() => go('top')}>Top</button>
                <button className="btn" onClick={() => go('right')}>Right</button>
                <span className="div" />
                <label className="btn" title="Explode (X)">
                    Explode
                    <input type="range" min={0} max={1} step={0.01} value={explode}
                        onChange={(e) => setExplode(Number(e.target.value))} style={{ width: 80 }} aria-label="Explode" />
                </label>
                <button className="btn" aria-pressed={section !== null} onClick={() => setSection((s) => (s === null ? 0.5 : null))} title="Section (S)">
                    Section
                </button>
                {section !== null && (
                    <input type="range" min={0.02} max={0.98} step={0.01} value={section}
                        onChange={(e) => setSection(Number(e.target.value))} style={{ width: 80 }} aria-label="Section height" />
                )}
                <button className="btn" aria-pressed={showContacts} onClick={() => setShowContacts(!showContacts)} title="Contact markers (C)">
                    Contacts
                </button>
                <span className="div" />
                <button className="btn" onClick={() => showAll()}>Show all</button>
            </div>
        </div>
    );
}
