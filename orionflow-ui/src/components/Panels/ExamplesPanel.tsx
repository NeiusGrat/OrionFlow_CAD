import { useEffect, useState } from "react";
import { X, Shapes } from "lucide-react";
import {
    fetchExamples,
    loadExampleIntoStudio,
    type ExampleEntry,
} from "../../lib/examples";

export default function ExamplesPanel({
    isOpen,
    onClose,
}: {
    isOpen: boolean;
    onClose: () => void;
}) {
    const [examples, setExamples] = useState<ExampleEntry[]>([]);
    const [error, setError] = useState<string | null>(null);
    const [activeCategory, setActiveCategory] = useState<string>("All");

    useEffect(() => {
        if (!isOpen) return;
        fetchExamples().then(setExamples).catch((e) => setError(e.message));
    }, [isOpen]);

    if (!isOpen) return null;

    const categories = ["All", ...Array.from(new Set(examples.map((e) => e.category)))];
    const visible =
        activeCategory === "All"
            ? examples
            : examples.filter((e) => e.category === activeCategory);

    return (
        <div
            style={{
                position: "fixed",
                top: 0,
                left: "68px",
                height: "100vh",
                width: "340px",
                background: "var(--slate-900)",
                borderRight: "1px solid var(--color-border)",
                zIndex: 100,
                display: "flex",
                flexDirection: "column",
                animation: "slideInLeft 0.3s var(--ease-out-expo)",
            }}
        >
            <div
                style={{
                    height: "64px",
                    padding: "0 20px",
                    borderBottom: "1px solid var(--color-border)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    flexShrink: 0,
                }}
            >
                <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                    <div
                        style={{
                            width: "32px",
                            height: "32px",
                            borderRadius: "var(--radius-md)",
                            background: "linear-gradient(135deg, #8AA5E6 0%, #8AA5E6 100%)",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                        }}
                    >
                        <Shapes size={16} color="white" strokeWidth={2.5} />
                    </div>
                    <span style={{ fontWeight: 600, fontSize: "15px", letterSpacing: "-0.01em" }}>
                        Example Library
                    </span>
                </div>
                <button
                    onClick={onClose}
                    style={{
                        width: "32px",
                        height: "32px",
                        borderRadius: "var(--radius-md)",
                        background: "var(--color-bg-element)",
                        border: "1px solid var(--color-border)",
                        color: "var(--color-text-muted)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        cursor: "pointer",
                    }}
                >
                    <X size={14} />
                </button>
            </div>

            {/* Category filter */}
            <div
                style={{
                    display: "flex",
                    flexWrap: "wrap",
                    gap: "6px",
                    padding: "12px 16px",
                    borderBottom: "1px solid var(--color-border)",
                    flexShrink: 0,
                }}
            >
                {categories.map((cat) => (
                    <button
                        key={cat}
                        onClick={() => setActiveCategory(cat)}
                        style={{
                            fontSize: "11px",
                            fontWeight: 500,
                            padding: "4px 10px",
                            borderRadius: "var(--radius-full)",
                            border: "1px solid",
                            borderColor:
                                activeCategory === cat ? "rgba(138, 165, 230, 0.5)" : "var(--color-border)",
                            background:
                                activeCategory === cat ? "rgba(138, 165, 230, 0.15)" : "transparent",
                            color:
                                activeCategory === cat ? "#A8BDEE" : "var(--color-text-muted)",
                            cursor: "pointer",
                            transition: "all var(--duration-fast) var(--ease-out-quad)",
                        }}
                    >
                        {cat}
                    </button>
                ))}
            </div>

            <div style={{ flex: 1, overflowY: "auto", padding: "12px" }}>
                {error && (
                    <div
                        style={{
                            padding: "12px",
                            fontSize: "13px",
                            color: "#DE8871",
                            textAlign: "center",
                        }}
                    >
                        {error}
                    </div>
                )}
                {!error && examples.length === 0 && (
                    <div
                        style={{
                            padding: "24px 12px",
                            fontSize: "13px",
                            color: "var(--color-text-muted)",
                            textAlign: "center",
                        }}
                    >
                        Loading examples…
                    </div>
                )}
                <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                    {visible.map((ex) => (
                        <div
                            key={ex.id}
                            onClick={() => {
                                loadExampleIntoStudio(ex);
                                onClose();
                            }}
                            style={{
                                padding: "12px 14px",
                                background: "var(--color-bg-element)",
                                borderRadius: "var(--radius-md)",
                                border: "1px solid var(--color-border)",
                                cursor: "pointer",
                                transition: "all var(--duration-fast) var(--ease-out-quad)",
                            }}
                            onMouseEnter={(e) => {
                                e.currentTarget.style.borderColor = "rgba(138, 165, 230, 0.4)";
                                e.currentTarget.style.background = "var(--color-bg-element-hover)";
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.borderColor = "var(--color-border)";
                                e.currentTarget.style.background = "var(--color-bg-element)";
                            }}
                        >
                            <div
                                style={{
                                    display: "flex",
                                    alignItems: "center",
                                    justifyContent: "space-between",
                                    marginBottom: "6px",
                                }}
                            >
                                <span
                                    style={{
                                        fontSize: "13px",
                                        fontWeight: 600,
                                        color: "var(--color-text-primary)",
                                    }}
                                >
                                    {ex.title}
                                </span>
                                <span
                                    style={{
                                        fontSize: "10px",
                                        fontWeight: 500,
                                        padding: "2px 8px",
                                        borderRadius: "var(--radius-full)",
                                        background: "rgba(222, 136, 113, 0.12)",
                                        color: "#A8BDEE",
                                        whiteSpace: "nowrap",
                                    }}
                                >
                                    {ex.category}
                                </span>
                            </div>
                            <p
                                style={{
                                    fontSize: "12px",
                                    color: "var(--color-text-muted)",
                                    lineHeight: 1.5,
                                    margin: 0,
                                    display: "-webkit-box",
                                    WebkitLineClamp: 2,
                                    WebkitBoxOrient: "vertical",
                                    overflow: "hidden",
                                }}
                            >
                                {ex.prompt}
                            </p>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}
