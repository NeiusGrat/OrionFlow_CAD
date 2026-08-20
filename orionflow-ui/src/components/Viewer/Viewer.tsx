import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ViewCube from "./ViewCube";
import PreviewMesh from "./PreviewMesh";
import { Canvas, useThree, useFrame } from "@react-three/fiber";
import {
    OrbitControls,
    useGLTF,
    Grid,
    ContactShadows,
} from "@react-three/drei";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import {
    CAD_EDGE,
    CAD_Z_UP_TO_Y_UP,
    CAD_LIGHTS,
    applyCadToneMapping,
    createEdgeMaterial,
    createPartMaterial,
} from "../../lib/cadAppearance";
import { useDesignStore } from "../../store/designStore";
import { useUIStore } from "../../store/uiStore";
import { useEditStore } from "../../store/editStore";
import { useStudioStore } from "../../store/studioStore";
import { buildFaceMap, faceOverlay, pickEdge } from "../../lib/faceMap";
import { useManifoldPreview } from "../../hooks/useManifoldPreview";
import * as THREE from "three";
import { Box as BoxIcon } from "lucide-react";

/** Read a design token at call time.
 *
 *  The grid and the overlay are painted by three.js, which cannot resolve a
 *  CSS custom property — so the values are pulled from the document and
 *  recomputed when the theme changes. Hard-coding them is what would leave the
 *  light theme with a dark grid drawn on pale vellum. */
function token(name: string, fallback: string): string {
    if (typeof window === "undefined") return fallback;
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
}

/** Machined-aluminium PBR set — the "real CAD" read.
 *
 *  The base surface and the edge treatment live in `lib/cadAppearance` so that
 *  every renderer in the app (this viewport, the thumbnail grid) shows one
 *  material. The interaction states below are this viewport's alone and are
 *  derived from that base rather than restating it. */
const MAT_BASE = createPartMaterial();
const MAT_HOVER = createPartMaterial({
    color: new THREE.Color("#c9ced6"),
    roughness: 0.26,
    envMapIntensity: 1.2,
});
const MAT_SELECTED = createPartMaterial({
    color: new THREE.Color("#A8BDEE"),
    metalness: 0.65,
    roughness: 0.3,
    emissive: new THREE.Color("#24468F"),
    emissiveIntensity: 0.12,
    envMapIntensity: 1.1,
});

/** The rest of the feature the selected face belongs to.
 *
 *  Deliberately faint. Professional CAD lights the *face* you picked and gives
 *  its feature only a wash, because a bright feature and a bright face read as
 *  the same state and the user loses track of what is actually selected. */
const MAT_FEATURE_CONTEXT = createPartMaterial({
    color: new THREE.Color("#b6c2dc"),
    metalness: 0.68,
    roughness: 0.3,
    emissive: new THREE.Color("#1b3468"),
    emissiveIntensity: 0.06,
    envMapIntensity: 1.1,
});

/** The face under the cursor. Warm, so hover never reads as selection. */
const MAT_FACE_HOVER = createPartMaterial({
    color: new THREE.Color("#E8D9AE"),
    metalness: 0.55,
    roughness: 0.28,
    emissive: new THREE.Color("#8A6B22"),
    emissiveIntensity: 0.22,
    envMapIntensity: 1.1,
    // Drawn on top of the face it covers; without the offset the two surfaces
    // are coplanar and stipple against each other as the camera moves.
    polygonOffset: true,
    polygonOffsetFactor: -2,
    polygonOffsetUnits: -2,
});

/** The selected face. The one thing on screen that must be unmistakable. */
const MAT_FACE_SELECTED = createPartMaterial({
    color: new THREE.Color("#8FB0F5"),
    metalness: 0.45,
    roughness: 0.24,
    emissive: new THREE.Color("#2B57B8"),
    emissiveIntensity: 0.45,
    envMapIntensity: 1.2,
    polygonOffset: true,
    polygonOffsetFactor: -3,
    polygonOffsetUnits: -3,
});

const EDGE_MAT = createEdgeMaterial();
const EDGE_MAT_SELECTED = createEdgeMaterial({
    color: new THREE.Color("#5B7FD4"),
    opacity: 0.95,
});

/** The edge the user picked, and the one under the cursor. Drawn over the part
 *  with depth testing off so a chamfer target stays visible against the face
 *  behind it — an edge highlight that z-fights is worse than none. */
const EDGE_MAT_PICKED = new THREE.LineBasicMaterial({
    color: new THREE.Color("#7FA6FF"),
    depthTest: false,
    transparent: true,
    opacity: 1,
});
const EDGE_MAT_HOVERED = new THREE.LineBasicMaterial({
    color: new THREE.Color("#E8C879"),
    depthTest: false,
    transparent: true,
    opacity: 0.9,
});

export type SceneBounds = { minY: number; radius: number; center: THREE.Vector3 };


/** Attach crisp CAD edge lines to a mesh exactly once. */
function ensureEdges(mesh: THREE.Mesh) {
    if (mesh.userData.__edgesAdded) return;
    const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(mesh.geometry, CAD_EDGE.thresholdDeg),
        EDGE_MAT
    );
    edges.name = "__edges";
    edges.raycast = () => {}; // edges must never steal pointer picks
    mesh.add(edges);
    mesh.userData.__edgesAdded = true;
}

function styleMesh(mesh: THREE.Mesh, state: "base" | "hover" | "selected") {
    mesh.material =
        state === "selected" ? MAT_SELECTED : state === "hover" ? MAT_HOVER : MAT_BASE;
    const edges = mesh.getObjectByName("__edges") as THREE.LineSegments | undefined;
    if (edges) edges.material = state === "selected" ? EDGE_MAT_SELECTED : EDGE_MAT;
}

/**
 * Model component — loads a GLB, applies machined-metal styling + edges,
 * frames the camera, and reports scene bounds for the grid/shadows.
 *
 * When a topology sidecar exists for the build on screen, the mesh's triangles
 * are regrouped by the Blueprint feature that authored them (see
 * `lib/faceMap.ts`) and picking becomes semantic: a click reports a CAD face
 * and the feature behind it, and a whole feature can be lit with a material of
 * its own. Without a sidecar the viewer behaves exactly as it did — the part is
 * one object, selectable as a whole.
 */
function Model({ url, onBounds }: { url: string; onBounds: (b: SceneBounds) => void }) {
    const { scene } = useGLTF(url);
    const { camera, controls } = useThree();
    const hasFramed = useRef(false);
    const [selectedMesh, setSelectedMesh] = useState<string | null>(null);
    const [hoveredMesh, setHoveredMesh] = useState<string | null>(null);

    const topology = useEditStore((s) => s.topology);
    const topologyFor = useEditStore((s) => s.topologyFor);
    const faceMap = useEditStore((s) => s.faceMap);
    const setFaceMap = useEditStore((s) => s.setFaceMap);
    const selectedFeature = useEditStore((s) => s.selectedFeature);
    const selectedElement = useEditStore((s) => s.selectedFace);
    const hoveredElement = useEditStore((s) => s.hoveredFace);
    const selectedFaceRef = selectedElement?.ref ?? null;
    const hoveredFaceRef = hoveredElement?.ref ?? null;
    const hover = useEditStore((s) => s.hover);
    const selectFace = useEditStore((s) => s.selectFace);

    /** Build the triangle→feature join once per (model, sidecar) pair.
     *
     *  Keyed on the sidecar's build id as well as the url because the geometry
     *  is mutated in place — grouping a mesh against the previous part's
     *  topology would light the wrong triangles. */
    useEffect(() => {
        if (!scene || !topology) return;
        let mesh: THREE.Mesh | null = null;
        scene.traverse((child) => {
            if (!mesh && (child as THREE.Mesh).isMesh) mesh = child as THREE.Mesh;
        });
        if (!mesh) return;

        const target = mesh as THREE.Mesh;
        if (target.userData.__faceMapFor === topologyFor) return;
        const map = buildFaceMap(target.geometry, topology);
        target.userData.__faceMapFor = topologyFor;
        setFaceMap(map, topologyFor);
    }, [scene, topology, topologyFor, setFaceMap]);

    /** One material per draw group. The feature gets a wash; the face itself
     *  is lit by an overlay below, so picking one face of a six-face pad does
     *  not light the whole pad. */
    useEffect(() => {
        if (!scene || !faceMap) return;
        scene.traverse((child) => {
            if (!(child as THREE.Mesh).isMesh) return;
            const mesh = child as THREE.Mesh;
            mesh.material = faceMap.groups.map((g) =>
                g.feature && g.feature === selectedFeature
                    ? MAT_FEATURE_CONTEXT
                    : MAT_BASE,
            );
        });
    }, [scene, faceMap, selectedFeature]);

    /** Overlay geometry for the picked and hovered faces.
     *
     *  Rebuilt only when the ref changes, and disposed on the way out — a
     *  viewer that leaks a BufferGeometry per hover will exhaust GPU memory in
     *  a few minutes of use. */
    const baseGeometry = useMemo<THREE.BufferGeometry | null>(() => {
        if (!scene) return null;
        const found: THREE.BufferGeometry[] = [];
        scene.traverse((child) => {
            if (!found.length && (child as THREE.Mesh).isMesh) {
                found.push((child as THREE.Mesh).geometry);
            }
        });
        return found[0] ?? null;
    }, [scene]);

    /** How close a click must land to count as aiming at an edge rather than
     *  the face behind it. Scaled to the part: a fixed millimetre value makes
     *  edges unhittable on a 500 mm bracket and swallows whole faces on a
     *  20 mm one. */
    const edgeTolerance = useMemo(() => {
        if (!baseGeometry) return 1;
        baseGeometry.computeBoundingSphere();
        return Math.max((baseGeometry.boundingSphere?.radius ?? 20) * 0.035, 0.4);
    }, [baseGeometry]);

    const isEdge = (ref?: string | null) =>
        !!ref && (ref.split(".").pop() || "").startsWith("e");

    const selectedGeometry = useMemo(() => {
        if (!baseGeometry || !faceMap || isEdge(selectedFaceRef)) return null;
        return faceOverlay(baseGeometry, faceMap, selectedFaceRef);
    }, [baseGeometry, faceMap, selectedFaceRef]);

    const hoveredGeometry = useMemo(() => {
        if (!baseGeometry || !faceMap || isEdge(hoveredFaceRef)) return null;
        if (!hoveredFaceRef || hoveredFaceRef === selectedFaceRef) return null;
        return faceOverlay(baseGeometry, faceMap, hoveredFaceRef);
    }, [baseGeometry, faceMap, hoveredFaceRef, selectedFaceRef]);

    /** A selected edge is drawn as its own bright line rather than by tinting
     *  a face, because the thing being operated on is the boundary itself. */
    const edgeLine = useMemo(() => {
        const rec = selectedElement ?? hoveredElement;
        if (!rec || !isEdge(rec.ref) || !rec.ends || rec.ends.length !== 2) return null;
        const g = new THREE.BufferGeometry();
        g.setAttribute(
            "position",
            new THREE.Float32BufferAttribute(
                [...rec.ends[0], ...rec.ends[1]].map(Number),
                3,
            ),
        );
        return g;
    }, [selectedElement, hoveredElement]);

    useEffect(() => () => selectedGeometry?.dispose(), [selectedGeometry]);
    useEffect(() => () => hoveredGeometry?.dispose(), [hoveredGeometry]);
    useEffect(() => () => edgeLine?.dispose(), [edgeLine]);

    useEffect(() => {
        if (!scene || hasFramed.current) return;

        const timer = setTimeout(() => {
            const box = new THREE.Box3();
            let hasMesh = false;
            scene.traverse((child) => {
                if ((child as THREE.Mesh).isMesh && (child as THREE.Mesh).geometry) {
                    box.expandByObject(child);
                    hasMesh = true;
                }
            });

            if (!hasMesh || box.isEmpty()) return;

            const center = box.getCenter(new THREE.Vector3());
            const sphere = box.getBoundingSphere(new THREE.Sphere());
            const radius = sphere.radius;
            if (radius <= 0) return;

            onBounds({ minY: box.min.y, radius, center });

            if ((camera as THREE.PerspectiveCamera).isPerspectiveCamera) {
                const pCam = camera as THREE.PerspectiveCamera;
                const fov = pCam.fov * (Math.PI / 180);
                const fitDistance = radius / Math.tan(fov / 2);
                const distance = fitDistance * 1.4;
                const dir = new THREE.Vector3(1, 0.72, 1).normalize();
                const finalPos = new THREE.Vector3().copy(center).add(dir.multiplyScalar(distance));
                camera.position.copy(finalPos);
            }

            camera.lookAt(center);

            if (controls) {
                (controls as any).target.copy(center);
                (controls as any).update();
            }

            hasFramed.current = true;
        }, 50);

        return () => clearTimeout(timer);
    }, [scene, url, camera, controls, onBounds]);

    useEffect(() => {
        hasFramed.current = false;
        setSelectedMesh(null);
    }, [url]);

    /** Whole-mesh styling, for a part with no sidecar. Skipped once the mesh is
     *  grouped by feature, because that path owns the material array. */
    useEffect(() => {
        if (!scene) return;
        scene.traverse((child) => {
            if ((child as THREE.Mesh).isMesh) {
                const mesh = child as THREE.Mesh;
                ensureEdges(mesh);
                if (faceMap) return;
                const state =
                    mesh.uuid === selectedMesh
                        ? "selected"
                        : mesh.uuid === hoveredMesh
                          ? "hover"
                          : "base";
                styleMesh(mesh, state);
            }
        });
    }, [scene, selectedMesh, hoveredMesh, faceMap]);

    const pickMesh = (e: any): THREE.Object3D => {
        let obj = e.object;
        while (obj && !(obj as THREE.Mesh).isMesh) obj = obj.parent;
        return obj || e.object;
    };

    /** What the pointer is over: an edge if the hit landed near one, else the face.
     *
     *  `e.faceIndex` is the triangle in the *reordered* index buffer, which is
     *  the order `buildFaceMap` wrote, so the face costs a single array lookup.
     *
     *  Edges need the extra work. They are drawn with picking disabled — a
     *  one-pixel line that stole every click would make faces unselectable — so
     *  an edge is resolved by proximity to the hit point instead. Without this
     *  a chamfer or a fillet could never be aimed at anything, because both
     *  need an edge and nothing in the viewport could produce one. */
    const pickElement = (e: any) => {
        if (!faceMap) return null;
        const face =
            typeof e.faceIndex === "number" ? faceMap.faceOf(e.faceIndex) : null;
        if (!topology || !e.point || !e.object) return face;

        // The hit is in world space; the sidecar is in FreeCAD's frame, and the
        // model group is rotated between the two. `worldToLocal` undoes it, so
        // this keeps working if the orientation is ever changed again.
        const local = (e.object as THREE.Object3D).worldToLocal(e.point.clone());
        const edge = pickEdge(topology, local, edgeTolerance);
        return edge ?? face;
    };

    const handlePointerOver = (e: any) => {
        e.stopPropagation();
        setHoveredMesh(pickMesh(e).uuid);
        document.body.style.cursor = "pointer";
    };

    const handlePointerMove = (e: any) => {
        if (!faceMap) return;
        e.stopPropagation();
        hover(pickElement(e));
    };

    const handlePointerOut = () => {
        setHoveredMesh(null);
        hover(null);
        document.body.style.cursor = "auto";
    };

    const handleClick = (e: any) => {
        e.stopPropagation();
        const element = pickElement(e);
        if (element) {
            void selectFace(element);
            return;
        }
        setSelectedMesh(pickMesh(e).uuid);
    };

    const handleMiss = () => {
        setSelectedMesh(null);
        if (faceMap) void selectFace(null);
    };

    return (
        <group
            rotation={CAD_Z_UP_TO_Y_UP}
            onPointerOver={handlePointerOver}
            onPointerMove={handlePointerMove}
            onPointerOut={handlePointerOut}
            onClick={handleClick}
            onPointerMissed={handleMiss}
        >
            <primitive object={scene} />
            {/* Highlights are separate meshes, not recoloured groups: one draw
                call each, and the part keeps a single material array however
                many faces it has. `raycast` is disabled so an overlay can never
                shadow the face beneath it and break the next pick. */}
            {selectedGeometry && (
                <mesh
                    geometry={selectedGeometry}
                    material={MAT_FACE_SELECTED}
                    raycast={() => {}}
                    renderOrder={2}
                />
            )}
            {hoveredGeometry && (
                <mesh
                    geometry={hoveredGeometry}
                    material={MAT_FACE_HOVER}
                    raycast={() => {}}
                    renderOrder={1}
                />
            )}
            {edgeLine && (
                <lineSegments
                    geometry={edgeLine}
                    material={
                        isEdge(selectedFaceRef) ? EDGE_MAT_PICKED : EDGE_MAT_HOVERED
                    }
                    raycast={() => {}}
                    renderOrder={3}
                />
            )}
        </group>
    );
}

function ViewManager() {
    const viewAction = useDesignStore((state) => state.viewAction);
    const { camera, scene, controls } = useThree();

    useEffect(() => {
        if (!viewAction || !scene) return;

        const box = new THREE.Box3();
        scene.traverse((child) => {
            if ((child as THREE.Mesh).isMesh) box.expandByObject(child);
        });

        if (box.isEmpty()) return;

        const center = box.getCenter(new THREE.Vector3());
        const sphere = box.getBoundingSphere(new THREE.Sphere());
        const radius = sphere.radius;

        const fov = ((camera as THREE.PerspectiveCamera).fov || 50) * (Math.PI / 180);
        const dist = (radius / Math.tan(fov / 2)) * 1.5;

        if (viewAction.type === "reset" || viewAction.type === "iso") {
            const dir = new THREE.Vector3(1, 0.72, 1).normalize();
            camera.position.copy(center).add(dir.multiplyScalar(dist));
        } else if (viewAction.type === "ortho") {
            camera.position.set(center.x, center.y + dist, center.z);
        }

        camera.lookAt(center);

        if (controls) {
            (controls as any).target.copy(center);
            (controls as any).update();
        }
    }, [viewAction, camera, scene, controls]);

    return null;
}

function ZoomGuard() {
    const { camera, scene, controls } = useThree();

    useFrame(() => {
        let hasMesh = false;
        scene.traverse((c) => {
            if ((c as any).isMesh) hasMesh = true;
        });
        if (!hasMesh) return;

        const cameraDist = camera.position.length();
        if (cameraDist > 5000) {
            const box = new THREE.Box3().setFromObject(scene);
            const center = box.getCenter(new THREE.Vector3());
            const radius = box.getBoundingSphere(new THREE.Sphere()).radius;
            const dist = (radius / Math.sin(((camera as any).fov * Math.PI) / 360)) * 1.5;

            camera.position.set(center.x + dist, center.y + dist, center.z + dist);
            camera.lookAt(center);
            if (controls) {
                (controls as any).target.copy(center);
                (controls as any).update();
            }
        }
    });

    return null;
}

/** Neutral studio environment (three built-in RoomEnvironment) — deterministic,
 * no network fetch, and guarantees metal has reflections (no env = black metal). */
function StudioEnvironment() {
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

export default function Viewer({ url }: { url: string }) {
    const isGenerating = useDesignStore((state) => state.isGenerating);
    const current = useDesignStore((state) => state.current);
    const theme = useUIStore((state) => state.theme);

    // Recomputed on a theme change; the dependency is the whole point.
    const palette = useMemo(
        () => ({
            cell: token("--st-grid-cell", "#2c3037"),
            section: token("--st-grid-section", "#3a3f47"),
            scrim: theme === "light" ? "rgba(242,236,224,0.78)" : "rgba(19,20,23,0.72)",
        }),
        [theme],
    );

    const featureGraph = current?.featureGraph;
    const { mesh: previewMesh, isLoading: isPreviewLoading } = useManifoldPreview(featureGraph);

    // The sidecar for whatever part is on screen. Fetched here rather than in
    // the store that builds parts, because it is only ever needed by something
    // rendering one — a headless rebuild has no use for it.
    const requestId = useStudioStore((s) => s.part?.requestId ?? "");
    const loadTopology = useEditStore((s) => s.loadTopology);
    useEffect(() => {
        if (requestId) void loadTopology(requestId);
    }, [requestId, loadTopology]);

    const isValidUrl = !!url && url.endsWith(".glb");
    const showPreview = !isValidUrl && previewMesh && !isPreviewLoading;

    const [bounds, setBounds] = useState<SceneBounds | null>(null);
    const onBounds = useCallback((b: SceneBounds) => setBounds(b), []);
    useEffect(() => {
        if (!isValidUrl) setBounds(null);
    }, [isValidUrl, url]);

    const groundY = bounds ? bounds.minY - 0.02 : 0;
    const extent = bounds ? Math.max(bounds.radius, 10) : 60;

    return (
        <div style={{ height: "100%", width: "100%", position: "relative" }}>
            {/* Generating overlay — quiet, engineering-grade */}
            {isGenerating && (
                <div
                    style={{
                        position: "absolute",
                        zIndex: 100,
                        inset: 0,
                        background: palette.scrim,
                        backdropFilter: "blur(3px)",
                        display: "flex",
                        flexDirection: "column",
                        alignItems: "center",
                        justifyContent: "center",
                        color: "var(--studio-text)",
                    }}
                >
                    <div
                        style={{
                            width: "52px",
                            height: "52px",
                            borderRadius: "12px",
                            border: "1px solid var(--studio-border)",
                            background: "var(--studio-panel-2)",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            animation: "pulse 1.6s ease-in-out infinite",
                        }}
                    >
                        <BoxIcon size={24} color="var(--studio-accent)" />
                    </div>
                    <p style={{ marginTop: "18px", fontSize: "14px", fontWeight: 600 }}>
                        Generating geometry…
                    </p>
                    <p style={{ marginTop: "6px", fontSize: "12px", color: "var(--studio-text-dim)" }}>
                        intent → parametric code → B-rep → mesh
                    </p>
                    <style>{`@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.45; } }`}</style>
                </div>
            )}

            {/* 3D Canvas — machined part, neutral gray environment */}
            <Canvas
                // A shallower, slightly raised three-quarter view — the angle
                // CAD packages open on, because it shows three faces at once
                // and reads the part's proportions immediately.
                camera={{ position: [90, 62, 90], fov: 35, near: 0.1, far: 20000 }}
                dpr={[1, 2]}
                shadows
                gl={{ antialias: true }}
                // ACES filmic keeps metal highlights from clipping to flat
                // white, which is what makes an untonemapped metallic part read
                // as plastic. Without it the whole PBR set is wasted.
                onCreated={({ gl }) => applyCadToneMapping(gl)}
                style={{
                    background:
                        "radial-gradient(120% 90% at 50% 32%, var(--studio-viewport-hi) 0%, var(--studio-viewport-lo) 72%)",
                }}
            >
                <StudioEnvironment />
                {/* Three-point rig over the environment map: a key that casts,
                    a cool fill that keeps shadowed faces readable, and a rim
                    that separates the silhouette from the background. */}
                <directionalLight
                    position={CAD_LIGHTS.key.position}
                    intensity={CAD_LIGHTS.key.intensity}
                    castShadow
                    shadow-mapSize={[1024, 1024]}
                    shadow-bias={-0.0004}
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

                {/* WASM parametric preview */}
                {showPreview && <PreviewMesh geometry={previewMesh} />}

                {/* GLB model */}
                {isValidUrl && <Model url={url} onBounds={onBounds} />}

                {/* Ground plane: engineering grid + soft contact shadow */}
                {isValidUrl && bounds && (
                    <group position={[0, groundY, 0]}>
                        <Grid
                            infiniteGrid
                            cellSize={5}
                            sectionSize={25}
                            cellThickness={0.6}
                            sectionThickness={1.1}
                            cellColor={palette.cell}
                            sectionColor={palette.section}
                            fadeDistance={extent * 10}
                            fadeStrength={1.4}
                            followCamera={false}
                        />
                        <ContactShadows
                            position={[bounds.center.x, 0.01, bounds.center.z]}
                            opacity={0.42}
                            blur={2.4}
                            far={extent * 1.5}
                            scale={extent * 4}
                            resolution={512}
                            frames={1}
                        />
                    </group>
                )}

                <OrbitControls
                    makeDefault
                    enableDamping
                    dampingFactor={0.08}
                    minDistance={0.1}
                    maxDistance={2000}
                />

                <ViewManager />
                <ZoomGuard />
                <ViewCube />
            </Canvas>
        </div>
    );
}
