import { useDesignStore } from "../../store/designStore";

export default function LeftPanel() {
    const creations = useDesignStore((state) => state.creations);
    const current = useDesignStore((state) => state.current);
    const setCurrent = useDesignStore((state) => state.setCurrent);

    return (
        <div
            style={{
                width: "260px",
                background: "#111",
                color: "#eee",
                borderRight: "1px solid #222",
                padding: "12px",
                boxSizing: "border-box",
            }}
        >
            <h3 style={{ marginBottom: "12px", fontSize: "14px" }}>
                Creations
            </h3>

            {creations.length === 0 && (
                <div style={{ fontSize: "12px", color: "#777" }}>
                    No designs yet
                </div>
            )}

            {creations.map((c) => (
                <div
                    key={c.id}
                    onClick={() => setCurrent(c.id)}
                    style={{
                        padding: "8px",
                        marginBottom: "6px",
                        cursor: "pointer",
                        borderRadius: "4px",
                        background:
                            current?.id === c.id ? "#222" : "transparent",
                        border:
                            current?.id === c.id
                                ? "1px solid #333"
                                : "1px solid transparent",
                    }}
                >
                    <div style={{ fontSize: "12px", fontWeight: 500 }}>
                        {c.prompt}
                    </div>
                </div>
            ))}
        </div>
    );
}
