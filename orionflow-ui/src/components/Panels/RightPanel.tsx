import { useDesignStore } from "../../store/designStore";
import { Download, RefreshCw, ChevronDown } from "lucide-react";
import AdamSlider from "../Controls/AdamSlider";
import { useState } from "react";

export default function RightPanel() {
    const current = useDesignStore((state) => state.current);

    // Local state for the color picker mock
    const [color] = useState("#00A6FF");

    if (!current) return null;

    return (
        <div
            style={{
                width: "320px",
                background: "var(--color-bg-panel)",
                borderLeft: "1px solid var(--color-border)",
                display: "flex",
                flexDirection: "column",
                zIndex: 20
            }}
        >
            {/* HEADER */}
            <div style={{
                height: "64px",
                padding: "0 24px",
                borderBottom: "1px solid var(--color-border)",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between"
            }}>
                <h2 style={{ fontSize: "16px", fontWeight: 600 }}>Parameters</h2>
                <button style={{
                    background: "transparent", border: "none", padding: "8px",
                    color: "var(--color-text-muted)", cursor: "pointer"
                }}>
                    <RefreshCw size={14} />
                </button>
            </div>

            {/* PARAMETERS LIST */}
            <div style={{ flex: 1, overflowY: "auto", padding: "24px" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                    {/* Mocking the Adam CAD specific sliders for the visual requirements */}
                    <AdamSlider label="Cylinder Radius" value={15} min={1} max={50} unit="mm" onChange={() => { }} />
                    <AdamSlider label="Cylinder Height" value={50} min={1} max={100} unit="mm" onChange={() => { }} />
                    <AdamSlider label="Resolution" value={60} min={10} max={100} step={1} onChange={() => { }} />

                    {/* Divider */}
                    <div style={{ height: "1px", background: "var(--color-border)", margin: "16px 0" }} />

                    <AdamSlider
                        label="Roughness"
                        value={current.material.roughness}
                        min={0} max={1} step={0.01}
                        onChange={(v) => {
                            const state = useDesignStore.getState();
                            if (state.current) {
                                state.current.material.roughness = v;
                                useDesignStore.setState({ current: { ...state.current } });
                            }
                        }}
                    />
                    <AdamSlider
                        label="Metalness"
                        value={current.material.metalness}
                        min={0} max={1} step={0.01}
                        onChange={(v) => {
                            const state = useDesignStore.getState();
                            if (state.current) {
                                state.current.material.metalness = v;
                                useDesignStore.setState({ current: { ...state.current } });
                            }
                        }}
                    />
                </div>
            </div>

            {/* COLOR & EXPORT FOOTER */}
            <div style={{ padding: "20px" }}>
                {/* Color Picker Mock */}
                <div style={{
                    marginBottom: "16px",
                    background: "var(--color-bg-element)",
                    borderRadius: "12px",
                    padding: "4px",
                    border: "1px solid var(--color-border)"
                }}>
                    <div style={{
                        height: "40px",
                        background: "linear-gradient(to right, #000, #00A6FF, #fff)",
                        borderRadius: "8px",
                        position: "relative",
                        marginBottom: "8px",
                        cursor: "crosshair"
                    }}>
                        <div style={{
                            position: "absolute", right: "20px", top: "50%", transform: "translateY(-50%)",
                            width: "20px", height: "20px", borderRadius: "50%",
                            border: "2px solid white", background: "#00A6FF",
                            boxShadow: "0 2px 4px rgba(0,0,0,0.3)"
                        }} />
                    </div>

                    <div style={{
                        display: "flex", alignItems: "center", justifyContent: "space-between",
                        padding: "8px 12px", cursor: "pointer"
                    }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                            <div style={{ width: "20px", height: "20px", borderRadius: "50%", background: color }} />
                            <span style={{ fontSize: "12px", fontFamily: "monospace", color: "var(--color-text-secondary)" }}>{color}</span>
                        </div>
                        <ChevronDown size={14} color="var(--color-text-muted)" />
                    </div>
                </div>

                {/* Primary Export Button */}
                <a
                    href={current.files.step} // using step as example
                    download
                    style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        gap: "10px",
                        width: "100%",
                        padding: "14px",
                        background: "#e5e7eb", // Light button like in screenshot (closest to white/grey)
                        color: "black",
                        border: "none",
                        borderRadius: "8px",
                        fontWeight: 600,
                        fontSize: "14px",
                        textDecoration: "none",
                        cursor: "pointer",
                        transition: "transform 0.1s"
                    }}
                    onMouseEnter={(e) => e.currentTarget.style.transform = "translateY(-1px)"}
                    onMouseLeave={(e) => e.currentTarget.style.transform = "translateY(0)"}
                >
                    <Download size={18} />
                    <span>Download STL</span>
                    <div style={{
                        width: "24px", height: "24px", marginLeft: "auto",
                        borderLeft: "1px solid rgba(0,0,0,0.1)", display: "flex", alignItems: "center", justifyContent: "center"
                    }}>
                        <ChevronDown size={14} />
                    </div>
                </a>
            </div>
        </div>
    );
}
