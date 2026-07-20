import { useCallback, useEffect, useRef, useState } from "react";
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
import { useDesignStore } from "../../store/designStore";
import { useManifoldPreview } from "../../hooks/useManifoldPreview";
import * as THREE from "three";
import { Box as BoxIcon } from "lucide-react";

/** Machined-aluminum PBR set — the "real CAD" read. */
const MAT_BASE = new THREE.MeshStandardMaterial({
    color: new THREE.Color("#b9bec6"),
    metalness: 0.85,
    roughness: 0.34,
    envMapIntensity: 1.0,
});
const MAT_HOVER = new THREE.MeshStandardMaterial({
    color: new THREE.Color("#c9ced6"),
    metalness: 0.85,
    roughness: 0.28,
    envMapIntensity: 1.1,
});
const MAT_SELECTED = new THREE.MeshStandardMaterial({
    color: new THREE.Color("#A8BDEE"),
    metalness: 0.65,
    roughness: 0.3,
    emissive: new THREE.Color("#24468F"),
    emissiveIntensity: 0.12,
    envMapIntensity: 1.1,
});

const EDGE_MAT = new THREE.LineBasicMaterial({
    color: new THREE.Color("#191b1e"),
    transparent: true,
    opacity: 0.55,
});
const EDGE_MAT_SELECTED = new THREE.LineBasicMaterial({
    color: new THREE.Color("#5B7FD4"),
    transparent: true,
    opacity: 0.95,
});

export type SceneBounds = { minY: number; radius: number; center: THREE.Vector3 };

/** Attach crisp CAD edge lines to a mesh exactly once. */
function ensureEdges(mesh: THREE.Mesh) {
    if (mesh.userData.__edgesAdded) return;
    const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(mesh.geometry, 28),
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
 */
function Model({ url, onBounds }: { url: string; onBounds: (b: SceneBounds) => void }) {
    const { scene } = useGLTF(url);
    const { camera, controls } = useThree();
    const hasFramed = useRef(false);
    const [selectedMesh, setSelectedMesh] = useState<string | null>(null);
    const [hoveredMesh, setHoveredMesh] = useState<string | null>(null);

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

    useEffect(() => {
        if (!scene) return;
        scene.traverse((child) => {
            if ((child as THREE.Mesh).isMesh) {
                const mesh = child as THREE.Mesh;
                ensureEdges(mesh);
                const state =
                    mesh.uuid === selectedMesh
                        ? "selected"
                        : mesh.uuid === hoveredMesh
                          ? "hover"
                          : "base";
                styleMesh(mesh, state);
            }
        });
    }, [scene, selectedMesh, hoveredMesh]);

    const pickMesh = (e: any): THREE.Object3D => {
        let obj = e.object;
        while (obj && !(obj as THREE.Mesh).isMesh) obj = obj.parent;
        return obj || e.object;
    };

    const handlePointerOver = (e: any) => {
        e.stopPropagation();
        setHoveredMesh(pickMesh(e).uuid);
        document.body.style.cursor = "pointer";
    };

    const handlePointerOut = () => {
        setHoveredMesh(null);
        document.body.style.cursor = "auto";
    };

    const handleClick = (e: any) => {
        e.stopPropagation();
        setSelectedMesh(pickMesh(e).uuid);
    };

    const handleMiss = () => {
        setSelectedMesh(null);
    };

    return (
        <group
            onPointerOver={handlePointerOver}
            onPointerOut={handlePointerOut}
            onClick={handleClick}
            onPointerMissed={handleMiss}
        >
            <primitive object={scene} />
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

    const featureGraph = current?.featureGraph;
    const { mesh: previewMesh, isLoading: isPreviewLoading } = useManifoldPreview(featureGraph);

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
                        background: "rgba(19, 20, 23, 0.72)",
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
                camera={{ position: [70, 52, 70], fov: 40, near: 0.1, far: 10000 }}
                dpr={[1, 2]}
                gl={{ antialias: true }}
                style={{
                    background:
                        "radial-gradient(120% 90% at 50% 32%, var(--studio-viewport-hi) 0%, var(--studio-viewport-lo) 72%)",
                }}
            >
                <StudioEnvironment />
                <directionalLight position={[8, 14, 8]} intensity={0.55} />
                <directionalLight position={[-10, 6, -6]} intensity={0.2} color="#c9d6ea" />

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
                            cellColor="#2c3037"
                            sectionColor="#3a3f47"
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
