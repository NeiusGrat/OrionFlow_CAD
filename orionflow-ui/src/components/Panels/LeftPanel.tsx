import { useDesignStore } from "../../store/designStore";
import { Box, Plus, Send, Image as ImageIcon } from "lucide-react";
import { useState } from "react";

export default function LeftPanel() {
    const current = useDesignStore((state) => state.current);
    const [inputValue, setInputValue] = useState("");

    const handleNewCreation = () => {
        useDesignStore.setState({ current: null });
    };

    return (
        <div
            style={{
                width: "400px", // Wider for chat like Adam
                background: "var(--color-bg-panel)",
                borderRight: "1px solid var(--color-border)",
                display: "flex",
                flexDirection: "column",
                height: "100%",
                flexShrink: 0,
                zIndex: 20,
            }}
        >
            {/* BRAND HEADER */}
            <div style={{
                height: "64px",
                padding: "0 24px",
                borderBottom: "1px solid var(--color-border)",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between"
            }}>
                <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                    <img src="/logo.png" alt="OrionFlow" style={{
                        width: "32px",
                        height: "32px",
                        objectFit: "contain",
                        borderRadius: "4px" // Optional, depending on if the logo needs it
                    }} />
                    <div style={{ display: "flex", flexDirection: "column", gap: "0px", lineHeight: "1.1" }}>
                        <span style={{ fontSize: "16px", fontWeight: "700", letterSpacing: "-0.5px" }}>OrionFlow</span>
                        <span style={{ fontSize: "10px", fontWeight: "500", opacity: 0.6 }}>Text to CAD</span>
                    </div>
                </div>

                <button
                    onClick={handleNewCreation}
                    style={{
                        background: "var(--color-bg-element)", border: "1px solid var(--color-border)",
                        borderRadius: "8px", padding: "8px 12px", display: "flex", alignItems: "center", gap: "6px",
                        fontSize: "12px", fontWeight: 600, color: "var(--color-text-primary)", cursor: "pointer"
                    }}
                >
                    <Plus size={14} />
                    New
                </button>
            </div>

            {/* CHAT AREA */}
            <div style={{ flex: 1, overflowY: "auto", padding: "24px" }}>
                {/* Simulated Conversation for Current Item */}
                <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>

                    {/* User Prompt */}
                    <div style={{ display: "flex", gap: "16px" }}>
                        <div style={{
                            width: "32px", height: "32px", borderRadius: "50%",
                            background: "linear-gradient(to bottom right, #4ade80, #22c55e)",
                            flexShrink: 0
                        }} />
                        <div>
                            <p style={{ margin: 0, fontSize: "14px", lineHeight: "1.5", fontWeight: 500 }}>
                                {current?.prompt || "Start by creating a design..."}
                            </p>
                        </div>
                    </div>

                    {/* System Response (Mocked) */}
                    {current && (
                        <div style={{ display: "flex", gap: "16px" }}>
                            <div style={{
                                width: "32px", height: "32px", borderRadius: "50%",
                                background: "#27272a", border: "1px solid #3f3f46",
                                display: "flex", alignItems: "center", justifyContent: "center",
                                flexShrink: 0, color: "var(--color-accent)"
                            }}>
                                <Box size={16} />
                            </div>
                            <div style={{ flex: 1 }}>
                                <p style={{ margin: "0 0 12px 0", fontSize: "14px", lineHeight: "1.5", color: "var(--color-text-secondary)" }}>
                                    I've generated the {current.prompt} based on your requirements.
                                </p>

                                <div style={{
                                    background: "var(--color-bg-element)",
                                    border: "1px solid var(--color-border)",
                                    borderRadius: "12px",
                                    padding: "4px",
                                    width: "100%"
                                }}>
                                    <div style={{
                                        height: "180px", background: "#000", borderRadius: "8px",
                                        display: "flex", alignItems: "center", justifyContent: "center",
                                        marginBottom: "8px", position: "relative", overflow: "hidden"
                                    }}>
                                        {/* Mock Preview Image - ideally would be a capture of the canvas */}
                                        <Box size={48} color="#333" />
                                        <div style={{ position: "absolute", bottom: "10px", left: "10px", right: "10px" }}>
                                            <div style={{
                                                background: "rgba(0,0,0,0.8)", backdropFilter: "blur(4px)", borderRadius: "6px",
                                                padding: "8px 12px", display: "flex", alignItems: "center", justifyContent: "space-between"
                                            }}>
                                                <span style={{ fontSize: "12px", fontWeight: 600 }}>3D Object</span>
                                            </div>
                                        </div>
                                    </div>
                                    <div style={{ padding: "0 8px 4px 8px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                                        {/* Blank space where version info was if needed, or remove completely */}
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {/* INPUT AREA */}
            <div style={{ padding: "24px", paddingTop: "0" }}>
                <div style={{
                    background: "var(--color-bg-element)",
                    border: "1px solid var(--color-border)",
                    borderRadius: "16px",
                    padding: "12px",
                    display: "flex",
                    flexDirection: "column",
                    gap: "12px"
                }}>
                    <input
                        type="text"
                        placeholder="Make a rough 3D asset..."
                        value={inputValue}
                        onChange={(e) => setInputValue(e.target.value)}
                        style={{
                            background: "transparent", border: "none", outline: "none",
                            color: "var(--color-text-primary)", fontSize: "14px",
                            padding: 0
                        }}
                    />
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <div style={{ display: "flex", gap: "8px" }}>
                            <button style={{ padding: "6px", borderRadius: "6px", background: "transparent", border: "1px solid var(--color-border)", color: "var(--color-text-muted)", cursor: "pointer" }}>
                                <ImageIcon size={14} />
                            </button>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                            <button style={{
                                width: "24px", height: "24px", borderRadius: "50%",
                                background: inputValue ? "var(--color-text-primary)" : "var(--color-bg-element-active)",
                                color: "var(--color-bg-app)",
                                border: "none", display: "flex", alignItems: "center", justifyContent: "center",
                                cursor: "pointer"
                            }}>
                                <Send size={12} />
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
