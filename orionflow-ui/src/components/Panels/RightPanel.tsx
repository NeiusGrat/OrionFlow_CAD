import { useDesignStore } from "../../store/designStore";
import { Sliders, Eye, Download, Box, Layers, Settings2 } from "lucide-react";

export default function RightPanel() {
    const current = useDesignStore((state) => state.current);
    const creations = useDesignStore((state) => state.creations);

    if (!current) {
        return (
            <div
                style={{
                    width: "280px",
                    background: "var(--color-bg-panel)",
                    borderLeft: "1px solid var(--color-border)",
                    padding: "20px",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: "var(--color-text-muted)",
                    fontSize: "13px"
                }}
            >
                <div>Select a model to edit</div>
            </div>
        );
    }

    function updateMaterial(key: "roughness" | "metalness", value: number) {
        const currentDesign = useDesignStore.getState().current;
        if (!currentDesign) return;

        const updated = {
            ...currentDesign,
            material: {
                ...currentDesign.material,
                [key]: value,
            },
        };

        const updatedCreations = creations.map((c) =>
            c.id === currentDesign.id ? updated : c
        );

        useDesignStore.setState({
            creations: updatedCreations,
            current: updated,
        });
    }

    function setCameraView(position: [number, number, number]) {
        const camera = useDesignStore.getState().camera;
        if (!camera) return;

        // Smooth transition could be added here later with libraries like gsap or react-spring
        // keeping it instant/simple for now but functional
        camera.position.set(position[0], position[1], position[2]);
        camera.lookAt(0, 0, 0);
    }

    return (
        <div
            style={{
                width: "280px",
                background: "var(--color-bg-panel)",
                borderLeft: "1px solid var(--color-border)",
                display: "flex",
                flexDirection: "column",
                overflowY: "auto"
            }}
        >
            {/* MATERIAL SECTION */}
            <div style={{ padding: "16px", borderBottom: "1px solid var(--color-border)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "16px", color: "var(--color-text-secondary)" }}>
                    <Sliders size={14} />
                    <h3 style={{ fontSize: "12px", fontWeight: 600, textTransform: "uppercase" }}>Appearance</h3>
                </div>

                <div style={{ marginBottom: "16px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "6px" }}>
                        <label style={{ fontSize: "12px", color: "var(--color-text-muted)" }}>Roughness</label>
                        <span style={{ fontSize: "12px", fontFamily: "monospace" }}>{current.material.roughness.toFixed(2)}</span>
                    </div>
                    <input
                        type="range"
                        min={0}
                        max={1}
                        step={0.01}
                        value={current.material.roughness}
                        onChange={(e) => updateMaterial("roughness", Number(e.target.value))}
                        style={{ width: "100%", accentColor: "var(--color-accent)" }}
                    />
                </div>

                <div>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "6px" }}>
                        <label style={{ fontSize: "12px", color: "var(--color-text-muted)" }}>Metalness</label>
                        <span style={{ fontSize: "12px", fontFamily: "monospace" }}>{current.material.metalness.toFixed(2)}</span>
                    </div>
                    <input
                        type="range"
                        min={0}
                        max={1}
                        step={0.01}
                        value={current.material.metalness}
                        onChange={(e) => updateMaterial("metalness", Number(e.target.value))}
                        style={{ width: "100%", accentColor: "var(--color-accent)" }}
                    />
                </div>
            </div>

            {/* VIEWS SECTION */}
            <div style={{ padding: "16px", borderBottom: "1px solid var(--color-border)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "16px", color: "var(--color-text-secondary)" }}>
                    <Eye size={14} />
                    <h3 style={{ fontSize: "12px", fontWeight: 600, textTransform: "uppercase" }}>Views</h3>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "8px" }}>
                    <button onClick={() => setCameraView([0, 0, 5])} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "4px", padding: "8px" }}>
                        <Box size={16} />
                        <span style={{ fontSize: "10px" }}>Front</span>
                    </button>
                    <button onClick={() => setCameraView([0, 5, 0])} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "4px", padding: "8px" }}>
                        <Layers size={16} />
                        <span style={{ fontSize: "10px" }}>Top</span>
                    </button>
                    <button onClick={() => setCameraView([5, 5, 5])} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "4px", padding: "8px" }}>
                        <Settings2 size={16} />
                        <span style={{ fontSize: "10px" }}>Iso</span>
                    </button>
                </div>
            </div>

            {/* EXPORT SECTION */}
            <div style={{ padding: "16px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "16px", color: "var(--color-text-secondary)" }}>
                    <Download size={14} />
                    <h3 style={{ fontSize: "12px", fontWeight: 600, textTransform: "uppercase" }}>Export</h3>
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                    <a
                        href={current.files.step}
                        download
                        style={{
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            gap: "8px",
                            padding: "8px",
                            background: "var(--color-bg-element)",
                            border: "1px solid var(--color-border)",
                            borderRadius: "var(--radius-md)",
                            color: "var(--color-text-primary)",
                            textDecoration: "none",
                            fontSize: "13px",
                            fontWeight: 500,
                            transition: "background 0.2s"
                        }}
                    >
                        <span>Download STEP</span>
                    </a>

                    <a
                        href={current.files.glb}
                        download
                        style={{
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            gap: "8px",
                            padding: "8px",
                            background: "var(--color-bg-element)",
                            border: "1px solid var(--color-border)",
                            borderRadius: "var(--radius-md)",
                            color: "var(--color-text-primary)",
                            textDecoration: "none",
                            fontSize: "13px",
                            fontWeight: 500
                        }}
                    >
                        <span>Download GLB</span>
                    </a>
                </div>
            </div>
        </div>
    );
}
