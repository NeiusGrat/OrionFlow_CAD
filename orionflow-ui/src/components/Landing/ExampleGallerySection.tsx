import { Suspense, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, Center, useGLTF } from "@react-three/drei";
import * as THREE from "three";
import { ArrowRight, FileDown } from "lucide-react";
import { fetchExamples, type ExampleEntry } from "../../lib/examples";
import { getThumbnail } from "../../lib/thumbnailRenderer";

const FEATURED_MATERIAL = new THREE.MeshStandardMaterial({
    color: new THREE.Color("#9db4d4"),
    metalness: 0.35,
    roughness: 0.4,
});

function FeaturedModel({ url }: { url: string }) {
    const { scene } = useGLTF(url);
    useEffect(() => {
        scene.traverse((child) => {
            if ((child as THREE.Mesh).isMesh) {
                (child as THREE.Mesh).material = FEATURED_MATERIAL;
            }
        });
    }, [scene]);
    return (
        <Center>
            <primitive object={scene} />
        </Center>
    );
}

function Thumbnail({ url, title }: { url: string; title: string }) {
    const [src, setSrc] = useState<string | null>(null);
    useEffect(() => {
        let alive = true;
        getThumbnail(url).then((s) => alive && s && setSrc(s));
        return () => {
            alive = false;
        };
    }, [url]);

    return src ? (
        <img
            src={src}
            alt={title}
            style={{ width: "100%", height: "100%", objectFit: "contain" }}
            loading="lazy"
        />
    ) : (
        <div
            style={{
                width: "42px",
                height: "42px",
                borderRadius: "50%",
                border: "2px solid rgba(59, 130, 246, 0.2)",
                borderTopColor: "#3b82f6",
                animation: "spin 0.9s linear infinite",
            }}
        />
    );
}

export default function ExampleGallerySection() {
    const navigate = useNavigate();
    const sectionRef = useRef<HTMLDivElement>(null);
    const [examples, setExamples] = useState<ExampleEntry[]>([]);
    const [selected, setSelected] = useState<ExampleEntry | null>(null);
    const [inView, setInView] = useState(false);

    // Defer loading manifest + WebGL work until the section scrolls into view.
    useEffect(() => {
        const el = sectionRef.current;
        if (!el) return;
        const obs = new IntersectionObserver(
            (entries) => {
                if (entries[0].isIntersecting) {
                    setInView(true);
                    obs.disconnect();
                }
            },
            { rootMargin: "400px" }
        );
        obs.observe(el);
        return () => obs.disconnect();
    }, []);

    useEffect(() => {
        if (!inView) return;
        fetchExamples()
            .then((ex) => {
                setExamples(ex);
                if (ex.length > 0) setSelected(ex[0]);
            })
            .catch(() => {});
    }, [inView]);

    if (!inView && examples.length === 0) {
        return <div ref={sectionRef} id="examples" style={{ minHeight: "1px" }} />;
    }

    return (
        <section
            ref={sectionRef}
            id="examples"
            style={{ padding: "100px 24px", maxWidth: "1200px", margin: "0 auto" }}
        >
            <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>

            {/* Header */}
            <div style={{ textAlign: "center", marginBottom: "56px" }}>
                <div
                    style={{
                        display: "inline-block",
                        fontSize: "12px",
                        fontWeight: 600,
                        letterSpacing: "0.1em",
                        textTransform: "uppercase",
                        color: "#60a5fa",
                        background: "rgba(59, 130, 246, 0.1)",
                        border: "1px solid rgba(59, 130, 246, 0.25)",
                        borderRadius: "999px",
                        padding: "6px 16px",
                        marginBottom: "20px",
                    }}
                >
                    Example Library
                </div>
                <h2
                    style={{
                        fontSize: "clamp(28px, 4vw, 44px)",
                        fontWeight: 700,
                        letterSpacing: "-0.03em",
                        marginBottom: "16px",
                    }}
                >
                    {examples.length || 20} real parts. Zero manual CAD.
                </h2>
                <p
                    style={{
                        color: "#94a3b8",
                        fontSize: "16px",
                        maxWidth: "640px",
                        margin: "0 auto",
                        lineHeight: 1.6,
                    }}
                >
                    Every model below was generated end-to-end by OrionFlow — a text prompt in,
                    validated parametric geometry out. Click any part to inspect it, then open
                    it in the studio and make it yours.
                </p>
            </div>

            {/* Featured viewer */}
            {selected && (
                <div
                    style={{
                        display: "grid",
                        gridTemplateColumns: "minmax(0, 1.4fr) minmax(280px, 1fr)",
                        gap: "24px",
                        background: "rgba(15, 23, 42, 0.6)",
                        border: "1px solid rgba(255, 255, 255, 0.08)",
                        borderRadius: "20px",
                        padding: "24px",
                        marginBottom: "40px",
                        alignItems: "stretch",
                    }}
                    className="of-gallery-featured"
                >
                    <div
                        style={{
                            height: "380px",
                            borderRadius: "14px",
                            background:
                                "radial-gradient(ellipse at 50% 40%, #1e293b 0%, #0b1120 75%)",
                            overflow: "hidden",
                        }}
                    >
                        <Canvas camera={{ position: [80, 60, 80], fov: 32 }} dpr={[1, 1.75]}>
                            <hemisphereLight args={[0xf1f5f9, 0x334155, 1.1]} />
                            <directionalLight position={[4, 6, 5]} intensity={1.6} />
                            <directionalLight position={[-5, -2, -4]} intensity={0.5} color="#93c5fd" />
                            <Suspense fallback={null}>
                                <FeaturedModel url={selected.files.glb} />
                            </Suspense>
                            <OrbitControls
                                autoRotate
                                autoRotateSpeed={1.2}
                                enableZoom={true}
                                makeDefault
                            />
                        </Canvas>
                    </div>

                    <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
                        <span
                            style={{
                                fontSize: "11px",
                                fontWeight: 600,
                                color: "#818cf8",
                                textTransform: "uppercase",
                                letterSpacing: "0.08em",
                                marginBottom: "8px",
                            }}
                        >
                            {selected.category}
                        </span>
                        <h3
                            style={{
                                fontSize: "24px",
                                fontWeight: 700,
                                letterSpacing: "-0.02em",
                                marginBottom: "14px",
                            }}
                        >
                            {selected.title}
                        </h3>
                        <div
                            style={{
                                fontSize: "13px",
                                lineHeight: 1.65,
                                color: "#cbd5e1",
                                background: "rgba(2, 6, 23, 0.55)",
                                border: "1px solid rgba(255, 255, 255, 0.06)",
                                borderLeft: "3px solid #3b82f6",
                                borderRadius: "8px",
                                padding: "12px 14px",
                                marginBottom: "16px",
                            }}
                        >
                            “{selected.prompt}”
                        </div>
                        {selected.stats && (
                            <div
                                style={{
                                    display: "flex",
                                    gap: "8px",
                                    flexWrap: "wrap",
                                    marginBottom: "20px",
                                }}
                            >
                                {[
                                    `${selected.stats.bbox_mm.map((v) => Math.round(v)).join(" × ")} mm`,
                                    `${(selected.stats.volume_mm3 / 1000).toFixed(1)} cm³`,
                                    "STEP · STL · GLB",
                                ].map((chip) => (
                                    <span
                                        key={chip}
                                        style={{
                                            fontSize: "11px",
                                            fontFamily: "monospace",
                                            color: "#94a3b8",
                                            background: "rgba(30, 41, 59, 0.6)",
                                            border: "1px solid rgba(255, 255, 255, 0.06)",
                                            padding: "4px 10px",
                                            borderRadius: "6px",
                                        }}
                                    >
                                        {chip}
                                    </span>
                                ))}
                            </div>
                        )}
                        <div style={{ marginTop: "auto", display: "flex", gap: "10px", flexWrap: "wrap" }}>
                            <button
                                onClick={() => navigate(`/app?example=${selected.id}`)}
                                style={{
                                    display: "inline-flex",
                                    alignItems: "center",
                                    gap: "8px",
                                    background: "#3b82f6",
                                    color: "#fff",
                                    border: "none",
                                    borderRadius: "10px",
                                    padding: "12px 20px",
                                    fontSize: "14px",
                                    fontWeight: 600,
                                    cursor: "pointer",
                                }}
                            >
                                Open in Studio <ArrowRight size={16} />
                            </button>
                            <a
                                href={selected.files.step}
                                download={`${selected.id}.step`}
                                style={{
                                    display: "inline-flex",
                                    alignItems: "center",
                                    gap: "8px",
                                    background: "rgba(30, 41, 59, 0.8)",
                                    color: "#e2e8f0",
                                    border: "1px solid rgba(255, 255, 255, 0.1)",
                                    borderRadius: "10px",
                                    padding: "12px 20px",
                                    fontSize: "14px",
                                    fontWeight: 500,
                                    textDecoration: "none",
                                }}
                            >
                                <FileDown size={16} /> STEP
                            </a>
                        </div>
                    </div>
                </div>
            )}

            {/* Grid */}
            <div
                style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
                    gap: "14px",
                }}
            >
                {examples.map((ex) => {
                    const isActive = selected?.id === ex.id;
                    return (
                        <div
                            key={ex.id}
                            onClick={() => {
                                setSelected(ex);
                                sectionRef.current
                                    ?.querySelector(".of-gallery-featured")
                                    ?.scrollIntoView({ behavior: "smooth", block: "nearest" });
                            }}
                            style={{
                                background: "rgba(15, 23, 42, 0.6)",
                                border: `1px solid ${isActive ? "rgba(59, 130, 246, 0.6)" : "rgba(255, 255, 255, 0.07)"}`,
                                borderRadius: "14px",
                                overflow: "hidden",
                                cursor: "pointer",
                                transition: "border-color 0.15s ease, transform 0.15s ease",
                            }}
                            onMouseEnter={(e) => {
                                e.currentTarget.style.transform = "translateY(-3px)";
                                if (!isActive)
                                    e.currentTarget.style.borderColor = "rgba(59, 130, 246, 0.35)";
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.transform = "translateY(0)";
                                if (!isActive)
                                    e.currentTarget.style.borderColor = "rgba(255, 255, 255, 0.07)";
                            }}
                        >
                            <div
                                style={{
                                    aspectRatio: "4 / 3",
                                    display: "flex",
                                    alignItems: "center",
                                    justifyContent: "center",
                                    background:
                                        "radial-gradient(ellipse at 50% 40%, #172033 0%, #0b1120 80%)",
                                }}
                            >
                                <Thumbnail url={ex.files.glb} title={ex.title} />
                            </div>
                            <div style={{ padding: "12px 14px" }}>
                                <div
                                    style={{
                                        fontSize: "13px",
                                        fontWeight: 600,
                                        color: "#f1f5f9",
                                        whiteSpace: "nowrap",
                                        overflow: "hidden",
                                        textOverflow: "ellipsis",
                                    }}
                                >
                                    {ex.title}
                                </div>
                                <div style={{ fontSize: "11px", color: "#64748b", marginTop: "3px" }}>
                                    {ex.category}
                                </div>
                            </div>
                        </div>
                    );
                })}
            </div>
        </section>
    );
}
