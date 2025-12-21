import { useDesignStore } from "../../store/designStore";

export default function ParamPanel() {
    const current = useDesignStore((s) => s.current);

    if (!current || !current.featureGraph) return null;

    const graph = current.featureGraph;

    return (
        <div>
            {graph.features.map((f: any) => (
                <div key={f.id} style={{ marginBottom: 12 }}>
                    <div style={{ fontSize: "12px", fontWeight: 600, color: "var(--color-text-secondary)", marginBottom: "4px", textTransform: "capitalize" }}>
                        {f.type}
                    </div>

                    <div style={{ background: "var(--color-bg-element)", borderRadius: "6px", padding: "8px" }}>
                        {Object.entries(f.params).map(([key, val]) => {
                            const unit = f.units ? f.units[key] : "mm";
                            let displayVal = Number(val);
                            let displayUnit = "mm";

                            if (unit === "cm") {
                                displayVal = displayVal / 10;
                                displayUnit = "cm";
                            } else if (unit === "m") {
                                displayVal = displayVal / 1000;
                                displayUnit = "m";
                            } else if (unit === "in") {
                                displayVal = displayVal / 25.4;
                                displayUnit = "in";
                            }

                            return (
                                <div key={key} style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px", fontSize: "13px" }}>
                                    <span style={{ color: "var(--color-text-muted)", textTransform: "capitalize" }}>{key}</span>
                                    <span style={{ fontFamily: "monospace", color: "var(--color-text-primary)" }}>
                                        {displayVal.toFixed(2)} {displayUnit}
                                    </span>
                                </div>
                            );
                        })}
                    </div>
                </div>
            ))}
        </div>
    );
}
