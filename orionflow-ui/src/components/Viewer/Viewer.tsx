import { useEffect, useRef, useState } from "react";
import ViewCube from "./ViewCube";
import PreviewMesh from "./PreviewMesh";
import { Canvas, useThree, useFrame } from "@react-three/fiber";
import { OrbitControls, useGLTF } from "@react-three/drei";
import { useDesignStore } from "../../store/designStore";
import { useManifoldPreview } from "../../hooks/useManifoldPreview";
import * as THREE from "three";

import { Box as BoxIcon, Download, Zap, RotateCcw, Maximize2 } from "lucide-react";

/**
 * Model component - loads GLB and applies professional CAD styling
 */
function Model({ url }: { url: string }) {
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

            if ((camera as THREE.PerspectiveCamera).isPerspectiveCamera) {
                const pCam = camera as THREE.PerspectiveCamera;
                const fov = pCam.fov * (Math.PI / 180);
                const fitDistance = radius / Math.tan(fov / 2);
                const distance = fitDistance * 1.5;
                const dir = new THREE.Vector3(1, 1, 1).normalize();
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
    }, [scene, url, camera, controls]);

    useEffect(() => {
        hasFramed.current = false;
        setSelectedMesh(null);
    }, [url]);

    useEffect(() => {
        if (!scene) return;
        scene.traverse((child) => {
            if ((child as THREE.Mesh).isMesh) {
                const mesh = child as THREE.Mesh;
                const isSelected = mesh.uuid === selectedMesh;
                const isHovered = mesh.uuid === hoveredMesh;

                if (isSelected) {
                    mesh.material = new THREE.MeshStandardMaterial({
                        color: "#F59E0B",
                        emissive: "#D97706",
                        emissiveIntensity: 0.2,
                        roughness: 0.3,
                        metalness: 0.1,
                    });
                } else if (isHovered) {
                    mesh.material = new THREE.MeshStandardMaterial({
                        color: "#E5E7EB",
                        roughness: 0.4,
                        metalness: 0.2,
                    });
                } else {
                    mesh.material = new THREE.MeshStandardMaterial({
                        color: "#CBD5E1",
                        roughness: 0.4,
                        metalness: 0.2,
                        flatShading: false,
                    });
                }
            }
        });
    }, [scene, selectedMesh, hoveredMesh]);

    const handlePointerOver = (e: any) => {
        e.stopPropagation();
        setHoveredMesh(e.object.uuid);
        document.body.style.cursor = 'pointer';
    };

    const handlePointerOut = () => {
        setHoveredMesh(null);
        document.body.style.cursor = 'auto';
    };

    const handleClick = (e: any) => {
        e.stopPropagation();
        setSelectedMesh(e.object.uuid);
    };

    const handleMiss = () => {
        setSelectedMesh(null);
    }

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

        if (viewAction.type === 'reset' || viewAction.type === 'iso') {
            const dir = new THREE.Vector3(1, 1, 1).normalize();
            camera.position.copy(center).add(dir.multiplyScalar(dist));
        } else if (viewAction.type === 'ortho') {
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
        scene.traverse(c => { if ((c as any).isMesh) hasMesh = true; });
        if (!hasMesh) return;

        const cameraDist = camera.position.length();
        if (cameraDist > 5000) {
            const box = new THREE.Box3().setFromObject(scene);
            const center = box.getCenter(new THREE.Vector3());
            const radius = box.getBoundingSphere(new THREE.Sphere()).radius;
            const dist = (radius / Math.sin((camera as any).fov * Math.PI / 360)) * 1.5;

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

// Floating Action Button Component
function FloatingButton({
    icon: Icon,
    label,
    onClick,
    href,
    primary = false,
}: {
    icon: any;
    label: string;
    onClick?: () => void;
    href?: string;
    primary?: boolean;
}) {
    const content = (
        <>
            <Icon size={16} strokeWidth={2} />
            <span style={{
                fontSize: "13px",
                fontWeight: 600,
            }}>
                {label}
            </span>
        </>
    );

    const baseStyle: React.CSSProperties = {
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: "8px",
        padding: "12px 18px",
        background: primary
            ? "linear-gradient(135deg, var(--copper-500) 0%, var(--copper-400) 100%)"
            : "var(--glass-bg)",
        backdropFilter: primary ? "none" : "var(--glass-blur)",
        WebkitBackdropFilter: primary ? "none" : "var(--glass-blur)",
        border: primary ? "none" : "1px solid var(--glass-border)",
        borderRadius: "var(--radius-md)",
        color: primary ? "var(--slate-950)" : "var(--color-text-primary)",
        textDecoration: "none",
        cursor: "pointer",
        boxShadow: primary ? "var(--shadow-glow-accent)" : "var(--shadow-md)",
        transition: "all var(--duration-fast) var(--ease-out-quad)",
    };

    if (href) {
        return (
            <a
                href={href}
                download
                style={baseStyle}
                onMouseEnter={(e) => {
                    if (!primary) {
                        e.currentTarget.style.background = "var(--glass-bg-light)";
                        e.currentTarget.style.borderColor = "var(--color-border-hover)";
                    }
                }}
                onMouseLeave={(e) => {
                    if (!primary) {
                        e.currentTarget.style.background = "var(--glass-bg)";
                        e.currentTarget.style.borderColor = "var(--glass-border)";
                    }
                }}
            >
                {content}
            </a>
        );
    }

    return (
        <button
            onClick={onClick}
            style={baseStyle}
            onMouseEnter={(e) => {
                if (!primary) {
                    e.currentTarget.style.background = "var(--glass-bg-light)";
                    e.currentTarget.style.borderColor = "var(--color-border-hover)";
                }
            }}
            onMouseLeave={(e) => {
                if (!primary) {
                    e.currentTarget.style.background = "var(--glass-bg)";
                    e.currentTarget.style.borderColor = "var(--glass-border)";
                }
            }}
        >
            {content}
        </button>
    );
}

export default function Viewer({ url }: { url: string }) {
    const isGenerating = useDesignStore((state) => state.isGenerating);
    const current = useDesignStore((state) => state.current);
    const triggerViewAction = useDesignStore((state) => state.triggerViewAction);

    const featureGraph = current?.featureGraph;
    const { mesh: previewMesh, isLoading: isPreviewLoading } = useManifoldPreview(featureGraph);

    const isValidUrl = url && url.startsWith('http') && url.endsWith('.glb');
    const showPreview = !isValidUrl && previewMesh && !isPreviewLoading;

    const getDownloadUrl = (format: 'step' | 'stl') => {
        if (!current?.files?.[format]) return null;
        const file = current.files[format];
        if (!file || file === "") return null;
        const filename = file.split(/[/\\]/).pop();
        return `http://127.0.0.1:8000/download/${format}/${filename}`;
    };

    const stepUrl = getDownloadUrl('step');
    const stlUrl = getDownloadUrl('stl');
    const hasValidFiles = stepUrl || stlUrl;

    return (
        <div style={{ height: "100%", width: "100%", position: "relative" }}>
            {/* Export & View Controls - Floating Top Left */}
            {hasValidFiles && !isGenerating && (
                <div style={{
                    position: "absolute",
                    top: "20px",
                    left: "20px",
                    zIndex: 50,
                    display: "flex",
                    gap: "10px",
                    animation: "slideInLeft 0.3s var(--ease-out-expo)",
                }}>
                    {stepUrl && (
                        <FloatingButton
                            icon={Download}
                            label=".step"
                            href={stepUrl}
                        />
                    )}
                    {stlUrl && (
                        <FloatingButton
                            icon={Download}
                            label=".stl"
                            href={stlUrl}
                        />
                    )}
                </div>
            )}

            {/* View Controls - Floating Top Right */}
            {isValidUrl && !isGenerating && (
                <div style={{
                    position: "absolute",
                    top: "20px",
                    right: "20px",
                    zIndex: 50,
                    display: "flex",
                    gap: "8px",
                    animation: "slideInRight 0.3s var(--ease-out-expo)",
                }}>
                    <button
                        onClick={() => triggerViewAction('reset')}
                        style={{
                            width: "40px",
                            height: "40px",
                            borderRadius: "var(--radius-md)",
                            background: "var(--glass-bg)",
                            backdropFilter: "var(--glass-blur)",
                            WebkitBackdropFilter: "var(--glass-blur)",
                            border: "1px solid var(--glass-border)",
                            color: "var(--color-text-secondary)",
                            cursor: "pointer",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            transition: "all var(--duration-fast) var(--ease-out-quad)",
                        }}
                        title="Reset View"
                        onMouseEnter={(e) => {
                            e.currentTarget.style.background = "var(--glass-bg-light)";
                            e.currentTarget.style.color = "var(--color-text-primary)";
                        }}
                        onMouseLeave={(e) => {
                            e.currentTarget.style.background = "var(--glass-bg)";
                            e.currentTarget.style.color = "var(--color-text-secondary)";
                        }}
                    >
                        <RotateCcw size={16} />
                    </button>
                    <button
                        onClick={() => triggerViewAction('iso')}
                        style={{
                            width: "40px",
                            height: "40px",
                            borderRadius: "var(--radius-md)",
                            background: "var(--glass-bg)",
                            backdropFilter: "var(--glass-blur)",
                            WebkitBackdropFilter: "var(--glass-blur)",
                            border: "1px solid var(--glass-border)",
                            color: "var(--color-text-secondary)",
                            cursor: "pointer",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            transition: "all var(--duration-fast) var(--ease-out-quad)",
                        }}
                        title="Fit to View"
                        onMouseEnter={(e) => {
                            e.currentTarget.style.background = "var(--glass-bg-light)";
                            e.currentTarget.style.color = "var(--color-text-primary)";
                        }}
                        onMouseLeave={(e) => {
                            e.currentTarget.style.background = "var(--glass-bg)";
                            e.currentTarget.style.color = "var(--color-text-secondary)";
                        }}
                    >
                        <Maximize2 size={16} />
                    </button>
                </div>
            )}

            {/* Loading Overlay */}
            {isGenerating && (
                <div style={{
                    position: "absolute",
                    zIndex: 100,
                    inset: 0,
                    background: "linear-gradient(135deg, var(--slate-100) 0%, var(--slate-200) 100%)",
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    justifyContent: "center",
                    color: "var(--slate-700)",
                }}>
                    <style>
                        {`
                        @keyframes spinGlow {
                            from { transform: rotate(0deg); }
                            to { transform: rotate(360deg); }
                        }
                        `}
                    </style>
                    <div style={{
                        width: "80px",
                        height: "80px",
                        borderRadius: "var(--radius-xl)",
                        background: "linear-gradient(135deg, var(--copper-500) 0%, var(--copper-400) 100%)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        boxShadow: "0 0 40px var(--copper-glow)",
                        animation: "spinGlow 2s linear infinite",
                    }}>
                        <BoxIcon size={36} color="var(--slate-950)" />
                    </div>
                    <p style={{
                        marginTop: "24px",
                        fontSize: "18px",
                        fontWeight: 600,
                        color: "var(--slate-800)",
                    }}>
                        Generating geometry...
                    </p>
                    <p style={{
                        marginTop: "8px",
                        fontSize: "14px",
                        color: "var(--slate-500)",
                    }}>
                        Building your parametric model
                    </p>
                </div>
            )}

            {/* Preview Mode Indicator */}
            {showPreview && (
                <div style={{
                    position: "absolute",
                    top: "20px",
                    left: "20px",
                    zIndex: 50,
                    background: "linear-gradient(135deg, var(--copper-500) 0%, var(--copper-400) 100%)",
                    padding: "10px 16px",
                    borderRadius: "var(--radius-md)",
                    display: "flex",
                    alignItems: "center",
                    gap: "8px",
                    boxShadow: "var(--shadow-glow-accent)",
                    animation: "slideInLeft 0.3s var(--ease-out-expo)",
                }}>
                    <Zap size={16} color="var(--slate-950)" />
                    <span style={{
                        fontSize: "13px",
                        fontWeight: 600,
                        color: "var(--slate-950)",
                    }}>
                        Fast Preview (WASM)
                    </span>
                </div>
            )}

            {/* 3D Canvas */}
            <Canvas
                camera={{ position: [50, 50, 50], fov: 45, near: 0.1, far: 10000 }}
                style={{
                    background: "linear-gradient(180deg, #e2e8f0 0%, #f1f5f9 100%)",
                }}
            >
                {/* Studio Lighting */}
                <ambientLight intensity={0.8} />
                <directionalLight position={[10, 20, 10]} intensity={1.0} />
                <directionalLight position={[-10, 10, -5]} intensity={0.5} />
                <spotLight position={[0, 40, 0]} intensity={0.5} />

                {/* WASM Preview */}
                {showPreview && <PreviewMesh geometry={previewMesh} />}

                {/* GLB Model */}
                {isValidUrl && <Model url={url} />}

                <OrbitControls
                    makeDefault
                    enableDamping
                    dampingFactor={0.1}
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
