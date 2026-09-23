/**
 * An articulated reference assembly: move its joints, pick its parts.
 *
 * The GLB is one node per kinematic body with one mesh per placed part, and
 * the manifest beside it says how each body moves. Every frame each body's
 * matrix is set to `rest · R(axis, q)` — the composition the exporter checked
 * against the CAD placements at every named pose, and the tests check again
 * from the TypeScript side — so a slider here shows the robot the STEP file
 * describes at that angle, not an approximation of it.
 *
 * Deliberately separate from `Viewer`. That component is built around one
 * solid with a topology sidecar (faces, features, edits); this one is built
 * around many solids that move. Sharing a component would mean every branch in
 * one asking which of the two it is.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { ContactShadows, Grid, OrbitControls, useGLTF } from "@react-three/drei";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import * as THREE from "three";
import { Pause, Play, Eye, EyeOff, X, Layers, SlidersHorizontal, Boxes } from "lucide-react";
import {
    CAD_LIGHTS,
    CAD_Z_UP_TO_Y_UP,
    applyCadToneMapping,
    createPartMaterial,
} from "../../lib/cadAppearance";
import {
    SOURCE_LABEL,
    blend,
    bodyLocal,
    bodyPath,
    deg,
    drivingJoint,
    poseAngles,
    walkAngles,
    type Angles,
    type AssemblyManifest,
    type GeometrySource,
} from "../../lib/assembly";

/** Colours for "colour by geometry source" — how the part was recovered. */
const SOURCE_COLOR: Record<GeometrySource, string> = {
    modelled: "#6FCB92",
    revolved: "#B99CF0",
    slab: "#7FA6FF",
    faceted: "#D6A250",
};

const HOVER_EMISSIVE = new THREE.Color("#8A6B22");
const SELECT_EMISSIVE = new THREE.Color("#2B57B8");

type Motion =
    | { kind: "pose"; from: Angles; to: Angles; start: number; name: string }
    | { kind: "walk"; phase: number }
    | { kind: "manual" };

const TRANSITION_S = 0.9;
const WALK_HZ = 0.8;

export interface AssemblyViewerProps {
    manifestUrl: string;
    glbUrl: string;
    /** Named pose, or "walk". Changing it animates to it. */
    pose: string;
}

export default function AssemblyViewer({ manifestUrl, glbUrl, pose }: AssemblyViewerProps) {
    const [manifest, setManifest] = useState<AssemblyManifest | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let live = true;
        setManifest(null);
        fetch(manifestUrl)
            .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`manifest ${r.status}`))))
            .then((m) => live && setManifest(m))
            .catch((e) => live && setError(String(e?.message ?? e)));
        return () => {
            live = false;
        };
    }, [manifestUrl]);

    if (error) {
        return (
            <div style={{ padding: 24, color: "var(--st-redline)", fontSize: 12 }}>
                The assembly could not be loaded: {error}
            </div>
        );
    }
    if (!manifest) {
        return (
            <div className="of-label" style={{ padding: 24 }}>
                Loading assembly…
            </div>
        );
    }
    return <Loaded manifest={manifest} glbUrl={glbUrl} pose={pose} />;
}

function Loaded({ manifest, glbUrl, pose }: { manifest: AssemblyManifest; glbUrl: string; pose: string }) {
    // Motion lives in refs: it changes every frame, and React state would
    // re-render the panels sixty times a second to show numbers nobody reads.
    const angles = useRef<Angles>(poseAngles(manifest, "zero"));
    const motion = useRef<Motion>({ kind: "manual" });
    const [shown, setShown] = useState<Angles>(angles.current);
    const [activePose, setActivePose] = useState<string>("zero");

    const [selected, setSelected] = useState<string | null>(null);
    const [hovered, setHovered] = useState<string | null>(null);
    const [isolate, setIsolate] = useState(false);
    const [bySource, setBySource] = useState(false);
    const [tab, setTab] = useState<"joints" | "parts">("joints");
    const [panelOpen, setPanelOpen] = useState(true);

    const goTo = (name: string) => {
        setActivePose(name);
        if (name === "walk") {
            motion.current = { kind: "walk", phase: 0 };
            return;
        }
        motion.current = {
            kind: "pose",
            from: { ...angles.current },
            to: poseAngles(manifest, name),
            start: performance.now(),
            name,
        };
    };

    // A request from the conversation ("show it crouching") moves the robot.
    useEffect(() => {
        goTo(pose in manifest.poses || pose === "walk" ? pose : "zero");
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [pose, manifest]);

    const setJoint = (name: string, q: number) => {
        motion.current = { kind: "manual" };
        setActivePose("");
        angles.current = { ...angles.current, [name]: q };
        setShown(angles.current);
    };

    const inst = selected ? manifest.instances.find((i) => i.id === selected) ?? null : null;

    return (
        <div style={{ position: "absolute", inset: 0 }}>
            <Canvas
                camera={{ position: [320, 230, 320], fov: 35, near: 0.5, far: 20000 }}
                dpr={[1, 2]}
                shadows
                gl={{ antialias: true }}
                onCreated={({ gl }) => applyCadToneMapping(gl)}
                style={{
                    background:
                        "radial-gradient(120% 90% at 50% 32%, var(--studio-viewport-hi) 0%, var(--studio-viewport-lo) 72%)",
                }}
            >
                <Environment />
                <directionalLight
                    position={CAD_LIGHTS.key.position}
                    intensity={CAD_LIGHTS.key.intensity}
                    castShadow
                    shadow-mapSize={[1024, 1024]}
                />
                <directionalLight
                    position={CAD_LIGHTS.fill.position}
                    intensity={CAD_LIGHTS.fill.intensity}
                    color={CAD_LIGHTS.fill.color}
                />
                <directionalLight
                    position={CAD_LIGHTS.rim.position}
                    intensity={CAD_LIGHTS.rim.intensity}
                    color={CAD_LIGHTS.rim.color}
                />
                <ambientLight intensity={CAD_LIGHTS.ambient.intensity} />

                <Robot
                    manifest={manifest}
                    glbUrl={glbUrl}
                    angles={angles}
                    motion={motion}
                    onFrameAngles={setShown}
                    selected={selected}
                    hovered={hovered}
                    isolate={isolate}
                    bySource={bySource}
                    onHover={setHovered}
                    onSelect={setSelected}
                />

                <OrbitControls makeDefault enableDamping dampingFactor={0.08} minDistance={20} maxDistance={3000} />
            </Canvas>

            {/* ── top: what this is, and how to move it ── */}
            <div style={{ position: "absolute", top: 10, left: 46, right: panelOpen ? 300 : 56, display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", pointerEvents: "none" }}>
                <span
                    className="of-label"
                    title={manifest.source.note}
                    style={{ ...chip, color: "var(--st-caution)", borderColor: "var(--st-caution)" }}
                >
                    reference assembly
                </span>
                <span style={{ ...chip, color: "var(--st-ink)" }}>
                    {manifest.name} · {manifest.totals.instances} parts · {manifest.joints.length} joints
                </span>
                {[...Object.keys(manifest.poses), "walk"].map((p) => (
                    <button
                        key={p}
                        onClick={() => (p === "walk" && activePose === "walk" ? goTo("stand") : goTo(p))}
                        style={{ ...chip, ...button, ...(activePose === p ? active : {}) }}
                    >
                        {p === "walk" ? (activePose === "walk" ? <Pause size={11} /> : <Play size={11} />) : null}
                        {p === "walk" ? "Walk" : p[0].toUpperCase() + p.slice(1)}
                    </button>
                ))}
                <button onClick={() => setBySource((v) => !v)} style={{ ...chip, ...button, ...(bySource ? active : {}) }} title="Colour each part by how its geometry was recovered">
                    <Layers size={11} /> Geometry source
                </button>
            </div>

            {bySource && <SourceLegend manifest={manifest} />}

            {/* ── right: joints and parts ── */}
            {!panelOpen ? (
                <button onClick={() => setPanelOpen(true)} style={{ ...chip, ...button, position: "absolute", top: 10, right: 10 }} title="Joints and parts">
                    <SlidersHorizontal size={12} />
                </button>
            ) : (
                <div style={panel}>
                    <div style={{ display: "flex", borderBottom: "1px solid var(--st-rule)" }}>
                        <TabButton on={tab === "joints"} onClick={() => setTab("joints")} icon={<SlidersHorizontal size={11} />} label="Joints" />
                        <TabButton on={tab === "parts"} onClick={() => setTab("parts")} icon={<Boxes size={11} />} label={`Parts (${manifest.totals.parts})`} />
                        <button onClick={() => setPanelOpen(false)} style={{ ...iconBtn, marginLeft: "auto" }} title="Hide">
                            <X size={12} />
                        </button>
                    </div>
                    <div style={{ overflowY: "auto", padding: "8px 12px 12px", flex: 1 }}>
                        {tab === "joints" ? (
                            <JointList manifest={manifest} angles={shown} onChange={setJoint} highlight={inst ? drivingJoint(manifest, inst.body)?.name : undefined} />
                        ) : (
                            <PartList manifest={manifest} selected={inst?.part ?? null} onPick={(part) => {
                                const first = manifest.instances.find((i) => i.part === part);
                                if (first) setSelected(first.id);
                            }} />
                        )}
                    </div>
                </div>
            )}

            {/* ── bottom-left: the picked part ── */}
            {inst ? (
                <PartCard
                    manifest={manifest}
                    instanceId={inst.id}
                    angles={shown}
                    isolate={isolate}
                    onIsolate={() => setIsolate((v) => !v)}
                    onClose={() => {
                        setSelected(null);
                        setIsolate(false);
                    }}
                />
            ) : (
                <div className="of-label" style={{ position: "absolute", left: 12, bottom: 12, pointerEvents: "none" }}>
                    Click any part to inspect it · drag to orbit
                </div>
            )}
        </div>
    );
}

/* ═══════════════════════════ the 3D side ═══════════════════════════ */

function Environment() {
    const { gl, scene } = useThree();
    useEffect(() => {
        const pmrem = new THREE.PMREMGenerator(gl);
        const env = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
        scene.environment = env;
        return () => {
            scene.environment = null;
            env.dispose();
            pmrem.dispose();
        };
    }, [gl, scene]);
    return null;
}

interface RobotProps {
    manifest: AssemblyManifest;
    glbUrl: string;
    angles: React.MutableRefObject<Angles>;
    motion: React.MutableRefObject<Motion>;
    onFrameAngles: (a: Angles) => void;
    selected: string | null;
    hovered: string | null;
    isolate: boolean;
    bySource: boolean;
    onHover: (id: string | null) => void;
    onSelect: (id: string | null) => void;
}

function Robot(props: RobotProps) {
    const { manifest, glbUrl, angles, motion, onFrameAngles } = props;
    const { scene } = useGLTF(glbUrl);
    const { camera, controls } = useThree();

    // Resolve node names once. Bodies are driven by matrix, not by
    // position/rotation, so three must not rebuild their matrices itself.
    const rig = useMemo(() => {
        const bodies = manifest.bodies.map((b) => {
            const node = scene.getObjectByName(b.node);
            if (node) node.matrixAutoUpdate = false;
            return { body: b, node };
        });
        const meshes = new Map<string, THREE.Mesh>();
        for (const inst of manifest.instances) {
            const obj = scene.getObjectByName(inst.node);
            const mesh = (obj as THREE.Mesh)?.isMesh ? (obj as THREE.Mesh) : (obj?.children.find((c) => (c as THREE.Mesh).isMesh) as THREE.Mesh | undefined);
            if (!mesh) continue;
            const part = manifest.parts[inst.part];
            mesh.material = createPartMaterial({
                color: new THREE.Color(inst.color[0], inst.color[1], inst.color[2]),
                metalness: 0.08,
                roughness: 0.55,
                // An open shell shows its inside through the gap; drawing both
                // sides keeps it from reading as a hole in the robot.
                side: part?.closed_solid ? THREE.FrontSide : THREE.DoubleSide,
            });
            mesh.castShadow = true;
            mesh.receiveShadow = true;
            mesh.userData.instance = inst.id;
            meshes.set(inst.id, mesh);
        }
        return { bodies, meshes };
    }, [scene, manifest]);

    // The root body is fixed in space, exactly as the CAD poses are — so a
    // crouch would otherwise lift the feet off the floor. `lift` drops the
    // whole robot each frame until its lowest point touches the grid. Only the
    // viewer's placement moves; no joint and no CAD transform does.
    const lift = useRef<THREE.Group>(null);
    const box = useMemo(() => new THREE.Box3(), []);
    const settle = () => {
        const g = lift.current;
        if (!g) return;
        g.updateWorldMatrix(true, true);
        box.setFromObject(g);
        if (!box.isEmpty()) g.position.y -= box.min.y;
    };

    // Frame the robot once, at rest — on the first frame the orbit controls
    // exist, because framing before them leaves their target at the origin
    // and the camera looking at the robot's feet.
    const framed = useRef(false);
    const frameOnce = () => {
        if (framed.current || !controls || !lift.current) return;
        lift.current.updateWorldMatrix(true, true);
        const b = new THREE.Box3().setFromObject(lift.current);
        const centre = b.getCenter(new THREE.Vector3());
        const r = b.getBoundingSphere(new THREE.Sphere()).radius;
        // Nothing measurable yet (geometry still uploading): try next frame.
        if (b.isEmpty() || !(r > 0) || !Number.isFinite(r)) return;
        framed.current = true;
        const dist = (r / Math.tan(((camera as THREE.PerspectiveCamera).fov * Math.PI) / 360)) * 1.15;
        camera.position.copy(centre).add(new THREE.Vector3(1, 0.45, 1.25).normalize().multiplyScalar(dist));
        camera.lookAt(centre);
        (controls as unknown as { target: THREE.Vector3 }).target.copy(centre);
        (controls as unknown as { update: () => void }).update();
    };

    // Materials follow selection, hover, isolation and colouring.
    useEffect(() => {
        for (const inst of manifest.instances) {
            const mesh = rig.meshes.get(inst.id);
            if (!mesh) continue;
            const mat = mesh.material as THREE.MeshStandardMaterial;
            const src = manifest.parts[inst.part]?.source ?? "faceted";
            mat.color.set(props.bySource ? SOURCE_COLOR[src] : new THREE.Color(inst.color[0], inst.color[1], inst.color[2]));
            const isSel = props.selected === inst.id;
            const samePart = !!props.selected && manifest.instances.find((i) => i.id === props.selected)?.part === inst.part;
            mat.emissive.copy(isSel ? SELECT_EMISSIVE : props.hovered === inst.id ? HOVER_EMISSIVE : new THREE.Color(0));
            mat.emissiveIntensity = isSel ? 0.55 : samePart ? 0.18 : 0.3;
            if (samePart && !isSel) mat.emissive.copy(SELECT_EMISSIVE);
            const dim = props.isolate && props.selected && !samePart;
            mat.transparent = !!dim;
            mat.opacity = dim ? 0.08 : 1;
            mat.depthWrite = !dim;
            mesh.raycast = dim ? () => {} : THREE.Mesh.prototype.raycast;
            mat.needsUpdate = true;
        }
    }, [rig, manifest, props.selected, props.hovered, props.isolate, props.bySource]);

    const tmp = useMemo(() => new THREE.Matrix4(), []);
    const frame = useRef(0);
    useFrame((_, dt) => {
        const m = motion.current;
        if (m.kind === "pose") {
            const t = (performance.now() - m.start) / 1000 / TRANSITION_S;
            angles.current = blend(m.from, m.to, t);
            if (t >= 1) motion.current = { kind: "manual" };
        } else if (m.kind === "walk") {
            m.phase += dt * WALK_HZ * Math.PI * 2;
            angles.current = walkAngles(manifest, m.phase);
        }
        for (const { body, node } of rig.bodies) {
            if (!node) continue;
            const q = body.joint ? angles.current[body.joint.name] ?? 0 : 0;
            const e = bodyLocal(body, q);
            tmp.set(e[0], e[1], e[2], e[3], e[4], e[5], e[6], e[7], e[8], e[9], e[10], e[11], e[12], e[13], e[14], e[15]);
            node.matrix.copy(tmp);
            node.matrixWorldNeedsUpdate = true;
        }
        settle();
        frameOnce();
        // The panels show the angles a few times a second, not every frame.
        if (m.kind !== "manual" && ++frame.current % 6 === 0) onFrameAngles(angles.current);
        if (m.kind === "pose" && motion.current.kind === "manual") onFrameAngles(angles.current);
    });

    const pick = (e: { object: THREE.Object3D; stopPropagation: () => void }) => {
        e.stopPropagation();
        return (e.object.userData.instance as string | undefined) ?? null;
    };

    return (
        <>
            <group ref={lift}>
                <group
                    rotation={CAD_Z_UP_TO_Y_UP}
                    onPointerMove={(e) => props.onHover(pick(e))}
                    onPointerOut={() => props.onHover(null)}
                    onClick={(e) => props.onSelect(pick(e))}
                    onPointerMissed={() => props.onSelect(null)}
                >
                    <primitive object={scene} />
                </group>
            </group>
            <Ground />
        </>
    );
}

/** Grid and a live contact shadow under the feet. The robot is kept standing
 *  on y = 0 by `Robot`, so the floor never has to move. */
function Ground() {
    return (
        <group>
            <Grid infiniteGrid cellSize={10} sectionSize={50} cellThickness={0.6} sectionThickness={1.1} cellColor="#24262A" sectionColor="#31343A" fadeDistance={2400} fadeStrength={1.4} followCamera={false} />
            <ContactShadows position={[0, 0.2, 0]} opacity={0.45} blur={2.4} far={300} scale={600} resolution={256} frames={Infinity} />
        </group>
    );
}

/* ═══════════════════════════ panels ═══════════════════════════ */

function JointList({ manifest, angles, onChange, highlight }: { manifest: AssemblyManifest; angles: Angles; onChange: (name: string, q: number) => void; highlight?: string }) {
    const groups: [string, (n: string) => boolean][] = [
        ["Left leg", (n) => n.startsWith("left_")],
        ["Right leg", (n) => n.startsWith("right_")],
        ["Head", (n) => n.startsWith("neck") || n.startsWith("head")],
        // The skates' wheels spin freely; they have no range and no motor.
        ["Wheels (passive)", (n) => n.startsWith("passive_")],
    ];
    const joints = manifest.bodies.filter((b) => b.joint).map((b) => b.joint!);
    return (
        <>
            {groups.map(([title, test]) => (
                <div key={title} style={{ marginBottom: 10 }}>
                    <div className="of-label" style={{ margin: "6px 0 4px" }}>{title}</div>
                    {joints.filter((j) => test(j.name)).map((j) => {
                        const q = angles[j.name] ?? 0;
                        const [lo, hi] = j.range ?? [-Math.PI, Math.PI];
                        return (
                            <label key={j.name} style={{ display: "block", padding: "3px 0", borderRadius: 4, background: highlight === j.name ? "var(--st-blue-wash)" : "transparent" }}>
                                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11.5, color: "var(--st-graphite)" }}>
                                    <span>{j.label}</span>
                                    <span style={{ fontFamily: "var(--st-mono)", color: "var(--st-ink)" }}>{deg(q).toFixed(1)}°</span>
                                </div>
                                <input
                                    type="range"
                                    min={lo}
                                    max={hi}
                                    step={0.005}
                                    value={q}
                                    onChange={(e) => onChange(j.name, Number(e.target.value))}
                                    style={{ width: "100%" }}
                                    aria-label={j.label}
                                />
                                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--st-pencil)", fontFamily: "var(--st-mono)" }}>
                                    <span>{deg(lo).toFixed(0)}°</span>
                                    <span>{deg(hi).toFixed(0)}°</span>
                                </div>
                            </label>
                        );
                    })}
                </div>
            ))}
        </>
    );
}

function PartList({ manifest, selected, onPick }: { manifest: AssemblyManifest; selected: string | null; onPick: (part: string) => void }) {
    const parts = Object.entries(manifest.parts).sort((a, b) => a[1].label.localeCompare(b[1].label));
    return (
        <div>
            {parts.map(([id, p]) => (
                <button
                    key={id}
                    onClick={() => onPick(id)}
                    style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        width: "100%",
                        textAlign: "left",
                        padding: "5px 6px",
                        border: "none",
                        borderRadius: 4,
                        cursor: "pointer",
                        background: selected === id ? "var(--st-blue-wash)" : "transparent",
                        color: "var(--st-ink)",
                        fontSize: 12,
                    }}
                >
                    <span title={SOURCE_LABEL[p.source]} style={{ width: 8, height: 8, borderRadius: 2, background: SOURCE_COLOR[p.source], flexShrink: 0 }} />
                    <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.label}</span>
                    {p.instances > 1 && <span style={{ fontFamily: "var(--st-mono)", fontSize: 10.5, color: "var(--st-pencil)" }}>×{p.instances}</span>}
                </button>
            ))}
        </div>
    );
}

function PartCard({ manifest, instanceId, angles, isolate, onIsolate, onClose }: { manifest: AssemblyManifest; instanceId: string; angles: Angles; isolate: boolean; onIsolate: () => void; onClose: () => void }) {
    const inst = manifest.instances.find((i) => i.id === instanceId)!;
    const p = manifest.parts[inst.part];
    const body = manifest.bodies.find((b) => b.name === inst.body)!;
    const joint = drivingJoint(manifest, inst.body);
    const q = joint ? angles[joint.name] ?? 0 : 0;
    const rows: [string, React.ReactNode][] = [
        ["Geometry", <span key="g"><span style={{ color: SOURCE_COLOR[p.source] }}>{SOURCE_LABEL[p.source]}</span> — {p.source_note}</span>],
        ["Faces", `${p.faces.toLocaleString()} (${p.curved_faces} curved)`],
        ["Solid", p.closed_solid ? "Closed, valid solid" : "Open shell — not a closed volume"],
        ["Volume", `${(p.volume_mm3 / 1000).toFixed(2)} cm³`],
        ["Size", `${p.bbox_mm.map((v) => v.toFixed(1)).join(" × ")} mm`],
        ["In assembly", p.instances > 1 ? `${p.instances} instances` : "1 instance"],
        ["Mounted on", bodyPath(manifest, inst.body).join(" › ")],
        ["Moved by", joint ? `${joint.label} · ${deg(q).toFixed(1)}° (${joint.range ? `${deg(joint.range[0]).toFixed(0)}° to ${deg(joint.range[1]).toFixed(0)}°` : "free"})` : "Fixed to the trunk"],
        ["Body mass", `${body.mass_g.toFixed(1)} g (whole body, from the MJCF)`],
        ["Source file", <code key="f" style={{ fontFamily: "var(--st-mono)", fontSize: 11 }}>{p.file}</code>],
    ];
    return (
        <div style={{ position: "absolute", left: 12, bottom: 12, width: 360, maxWidth: "calc(100% - 24px)", background: "var(--st-sheet)", border: "1px solid var(--st-rule)", borderRadius: 8, boxShadow: "var(--st-shadow)", padding: "11px 13px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <div style={{ fontSize: 13.5, fontWeight: 600, color: "var(--st-ink)", flex: 1 }}>{p.label}</div>
                <button onClick={onIsolate} style={iconBtn} title={isolate ? "Show everything" : "Isolate this part"}>
                    {isolate ? <Eye size={13} /> : <EyeOff size={13} />}
                </button>
                <button onClick={onClose} style={iconBtn} title="Clear selection">
                    <X size={13} />
                </button>
            </div>
            <table style={{ width: "100%", marginTop: 8, borderCollapse: "collapse", fontSize: 11.5 }}>
                <tbody>
                    {rows.map(([k, v]) => (
                        <tr key={k}>
                            <td style={{ color: "var(--st-pencil)", padding: "2.5px 10px 2.5px 0", verticalAlign: "top", whiteSpace: "nowrap" }}>{k}</td>
                            <td style={{ color: "var(--st-graphite)", padding: "2.5px 0", lineHeight: 1.45 }}>{v}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}

function SourceLegend({ manifest }: { manifest: AssemblyManifest }) {
    const order: GeometrySource[] = ["modelled", "revolved", "slab", "faceted"];
    return (
        <div style={{ position: "absolute", top: 44, left: 46, display: "flex", gap: 10, flexWrap: "wrap", background: "var(--st-sheet)", border: "1px solid var(--st-rule)", borderRadius: 6, padding: "6px 10px", fontSize: 11, color: "var(--st-graphite)" }}>
            {order.map((s) => (
                <span key={s} style={{ display: "flex", alignItems: "center", gap: 5 }}>
                    <span style={{ width: 9, height: 9, borderRadius: 2, background: SOURCE_COLOR[s] }} />
                    {SOURCE_LABEL[s]} <span style={{ fontFamily: "var(--st-mono)", color: "var(--st-pencil)" }}>{manifest.totals.instances_by_source[s] ?? 0}</span>
                </span>
            ))}
        </div>
    );
}

function TabButton({ on, onClick, icon, label }: { on: boolean; onClick: () => void; icon: React.ReactNode; label: string }) {
    return (
        <button onClick={onClick} style={{ display: "flex", alignItems: "center", gap: 5, padding: "8px 12px", border: "none", background: "transparent", cursor: "pointer", fontSize: 11.5, color: on ? "var(--st-ink)" : "var(--st-pencil)", borderBottom: on ? "1px solid var(--st-ink)" : "1px solid transparent", marginBottom: -1 }}>
            {icon}
            {label}
        </button>
    );
}

/* ─────────────────────────── styles ─────────────────────────── */

const chip: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: 5,
    padding: "4px 9px",
    fontSize: 11,
    borderRadius: 5,
    // Longhand, because the active state and the reference chip override
    // only the colour, and React warns when a shorthand and its longhand mix.
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: "var(--st-rule)",
    background: "var(--st-sheet)",
    color: "var(--st-graphite)",
    boxShadow: "var(--st-shadow-sm)",
    pointerEvents: "auto",
};
const button: React.CSSProperties = { cursor: "pointer" };
const active: React.CSSProperties = { color: "var(--st-on-accent)", background: "var(--st-accent)", borderColor: "var(--st-accent)" };
const iconBtn: React.CSSProperties = { display: "flex", alignItems: "center", justifyContent: "center", width: 26, height: 26, border: "none", borderRadius: 4, background: "transparent", color: "var(--st-graphite)", cursor: "pointer" };
const panel: React.CSSProperties = {
    position: "absolute",
    top: 10,
    right: 10,
    bottom: 10,
    width: 280,
    display: "flex",
    flexDirection: "column",
    background: "var(--st-sheet)",
    border: "1px solid var(--st-rule)",
    borderRadius: 8,
    boxShadow: "var(--st-shadow)",
    overflow: "hidden",
};
