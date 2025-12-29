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
                    editable CAD Format
                </div>

                {/* SOLIDWORKS MACRO BUTTON */}
                <button
                    onClick={async () => {
                        if (!current?.prompt) return;
                        try {
                            const response = await fetch("http://localhost:8000/api/v2/export/solidworks", {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({ prompt: current.prompt }),
                            });

                            if (!response.ok) throw new Error("Export failed");

                            const blob = await response.blob();
                            const url = window.URL.createObjectURL(blob);
                            const a = document.createElement("a");
                            a.href = url;
                            a.download = "orion_macro.vba";
                            document.body.appendChild(a);
                            a.click();
                            document.body.removeChild(a);
                        } catch (error) {
                            console.error("Failed to download macro:", error);
                            alert("Could not generate SolidWorks macro.");
                        }
                    }}
                    style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        gap: "10px",
                        width: "100%",
                        padding: "14px",
                        marginTop: "10px",
                        background: "#2563EB", // Blue color
                        color: "white",
                        border: "none",
                        borderRadius: "8px",
                        fontWeight: 600,
                        fontSize: "14px",
                        cursor: "pointer",
                        transition: "filter 0.2s"
                    }}
                    onMouseEnter={(e) => e.currentTarget.style.filter = "brightness(110%)"}
                    onMouseLeave={(e) => e.currentTarget.style.filter = "brightness(100%)"}
                >
                    {/* SVG Icon */}
                    <svg width="18" height="18" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                    </svg>
                    <span>Download SW Macro</span>
                </button>
            </div>
        </div>
    );
}
