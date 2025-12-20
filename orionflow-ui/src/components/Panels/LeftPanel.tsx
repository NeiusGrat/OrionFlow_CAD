import { useDesignStore } from "../../store/designStore";
import { Box, Plus } from "lucide-react";

export default function LeftPanel() {
    const creations = useDesignStore((state) => state.creations);
    const current = useDesignStore((state) => state.current);
    const setCurrent = useDesignStore((state) => state.setCurrent);

    const handleNewCreation = () => {
        // Here we could clear the current selection or focus the input
        // For now, we'll just ensure no specific item is "active" if desired, 
        // but typically "New" focuses the prompt bar.
        // Since prompt is in App.tsx, we can just treat this as a UI placeholder for the "Start Fresh" action
        // or deselect current.
        useDesignStore.setState({ current: null });
        const input = document.querySelector('input[type="text"]') as HTMLInputElement;
        if (input) input.focus();
    };

    return (
        <div
            style={{
                width: "260px",
                background: "var(--color-bg-panel)",
                borderRight: "1px solid var(--color-border)",
                display: "flex",
                flexDirection: "column",
                height: "100%",
            }}
        >
            {/* BRAND HEADER */}
            <div style={{
                padding: "16px",
                borderBottom: "1px solid var(--color-border)",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between"
            }}>
                <div>
                    <h1 style={{ fontSize: "16px", fontWeight: "700", letterSpacing: "-0.5px" }}>OrionFlow</h1>
                    <span style={{ fontSize: "10px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "1px" }}>AI CAD</span>
                </div>
                <div style={{
                    width: "8px",
                    height: "8px",
                    background: "var(--color-accent)",
                    borderRadius: "50%",
                    boxShadow: "0 0 8px var(--color-accent)"
                }} />
            </div>

            {/* NEW CREATION BUTTON */}
            <div style={{ padding: "12px" }}>
                <button
                    onClick={handleNewCreation}
                    style={{
                        width: "100%",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        gap: "8px",
                        background: "var(--color-bg-element)",
                        border: "1px solid var(--color-border)",
                        padding: "10px",
                        color: "var(--color-text-primary)"
                    }}
                >
                    <Plus size={16} />
                    <span>New Creation</span>
                </button>
            </div>

            {/* LIST */}
            <div style={{ flex: 1, overflowY: "auto", padding: "0 12px 12px 12px" }}>
                <div style={{
                    fontSize: "11px",
                    fontWeight: 600,
                    color: "var(--color-text-muted)",
                    marginBottom: "8px",
                    textTransform: "uppercase"
                }}>
                    History
                </div>

                {creations.length === 0 && (
                    <div style={{ fontSize: "13px", color: "var(--color-text-muted)", textAlign: "center", padding: "20px 0" }}>
                        No designs yet
                    </div>
                )}

                {creations.map((c) => {
                    const isActive = current?.id === c.id;
                    return (
                        <div
                            key={c.id}
                            onClick={() => setCurrent(c.id)}
                            style={{
                                display: "flex",
                                alignItems: "center",
                                gap: "10px",
                                padding: "10px",
                                marginBottom: "4px",
                                cursor: "pointer",
                                borderRadius: "var(--radius-md)",
                                background: isActive ? "var(--color-bg-element-active)" : "transparent",
                                border: isActive ? "1px solid var(--color-border-hover)" : "1px solid transparent",
                                transition: "all 0.1s ease"
                            }}
                            onMouseEnter={(e) => {
                                if (!isActive) e.currentTarget.style.background = "var(--color-bg-element-hover)";
                            }}
                            onMouseLeave={(e) => {
                                if (!isActive) e.currentTarget.style.background = "transparent";
                            }}
                        >
                            <div style={{
                                color: isActive ? "var(--color-accent)" : "var(--color-text-muted)",
                                display: "flex", alignItems: "center"
                            }}>
                                <Box size={16} />
                            </div>
                            <div style={{
                                fontSize: "13px",
                                fontWeight: 500,
                                whiteSpace: "nowrap",
                                overflow: "hidden",
                                textOverflow: "ellipsis"
                            }}>
                                {c.prompt}
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}
