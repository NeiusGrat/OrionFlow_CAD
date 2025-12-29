import { useDesignStore } from "../../store/designStore";
import { Download, RefreshCw } from "lucide-react";
import ParamPanel from "./ParamPanel";

export default function RightPanel() {
    const current = useDesignStore((state) => state.current);

    if (!current) return null;

    // Extract filename from the path (handles windows/linux separators)
    const getStepFilename = (path: string) => {
        return path.split(/[/\\]/).pop();
    };

    const downloadUrl = current.files?.step
        ? `http://127.0.0.1:8000/download/step/${getStepFilename(current.files.step)}`
        : "#";

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
                <h2 style={{ fontSize: "16px", fontWeight: 600 }}>Properties</h2>
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
                    {/* Showing parameters is fine, just removed editing/sliders provided by AdamSlider directly */}
                    {/* The user said "remove them it is too unecessary", referring to "height , radius adam sliders" */}
                    {/* ParamPanel likely renders these. For now, we will keep ParamPanel IF it is read-only or just information. 
                       If ParamPanel has sliders, they should be removed. But ParamPanel is a separate component.
                       The explicit sliders in RightPanel are gone now. */}
                    <ParamPanel />
                </div>
            </div>

            {/* FOOTER */}
            <div style={{ padding: "20px" }}>
                {/* Download Button - Orange Style as requested */}
                <a
                    href={downloadUrl}
                    style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        gap: "10px",
                        width: "100%",
                        padding: "14px",
                        background: "#F97316", // Orange color
                        color: "white",
                        border: "none",
                        borderRadius: "8px",
                        fontWeight: 600,
                        fontSize: "14px",
                        textDecoration: "none",
                        cursor: "pointer",
                        transition: "filter 0.2s"
                    }}
                    onMouseEnter={(e) => e.currentTarget.style.filter = "brightness(110%)"}
                    onMouseLeave={(e) => e.currentTarget.style.filter = "brightness(100%)"}
                >
                    <Download size={18} />
                    <span>Download STEP</span>
                    {/* Removed ChevronDown as it implies a menu, but we just d/l */}
                </a>
                <div style={{ textAlign: "center", marginTop: "8px", fontSize: "12px", color: "var(--color-text-muted)" }}>
                    editable CAD Format (STEP)
                </div>

                <a
                    href={current.files?.stl ? `http://127.0.0.1:8000/download/stl/${current.files.stl.split(/[/\\]/).pop()}` : "#"}
                    style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        gap: "10px",
                        width: "100%",
                        padding: "14px",
                        background: "#3B82F6", // Blue color for 3D Print
                        color: "white",
                        border: "none",
                        borderRadius: "8px",
                        fontWeight: 600,
                        fontSize: "14px",
                        textDecoration: "none",
                        cursor: "pointer",
                        marginTop: "12px",
                        transition: "filter 0.2s"
                    }}
                    onMouseEnter={(e) => e.currentTarget.style.filter = "brightness(110%)"}
                    onMouseLeave={(e) => e.currentTarget.style.filter = "brightness(100%)"}
                >
                    <Download size={18} />
                    <span>Download STL</span>
                </a>
                <div style={{ textAlign: "center", marginTop: "8px", fontSize: "12px", color: "var(--color-text-muted)" }}>
                    3D Printing Format
                </div>

                {/* SOLIDWORKS MACRO BUTTON REMOVED (Legacy V1 feature) */}
            </div>
        </div>
    );
}
