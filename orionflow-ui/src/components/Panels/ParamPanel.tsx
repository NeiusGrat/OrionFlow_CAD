import { useDesignStore } from "../../store/designStore";

/**
 * Parameter Panel - Displays resolved feature parameters from the FeatureGraph.
 * 
 * Handles parameter resolution for values like "$depth" -> actual value from parameters dict.
 * Also handles the V3 parameter format where parameters are objects with {type, value, min, max}.
 */
export default function ParamPanel() {
    const current = useDesignStore((s) => s.current);

    if (!current || !current.featureGraph) return null;

    const graph = current.featureGraph;

    // Get resolved parameters from the design state or featureGraph
    // Handle both V1 format (flat values) and V3 format (nested objects with .value)
    const rawParams = current.parameters || graph.parameters || {};

    // Normalize parameters to flat key-value pairs
    const resolvedParams: Record<string, number> = {};
    for (const [key, val] of Object.entries(rawParams)) {
        if (val === null || val === undefined) continue;

        // V3 format: parameter is an object with { type, value, min, max }
        if (typeof val === 'object' && 'value' in (val as any)) {
            resolvedParams[key] = Number((val as any).value);
        }
        // V1 format: parameter is directly a number
        else if (typeof val === 'number') {
            resolvedParams[key] = val;
        }
        // String number
        else if (typeof val === 'string' && !val.startsWith('$')) {
            const parsed = Number(val);
            if (!isNaN(parsed)) {
                resolvedParams[key] = parsed;
            }
        }
    }

    /**
     * Resolve a parameter value.
     * Handles:
     * - Direct numeric values: 20 -> 20
     * - String numbers: "20" -> 20
     * - Parameter references: "$depth" -> resolved from parameters dict
     */
    function resolveValue(val: any): number | null {
        if (val === null || val === undefined) {
            return null;
        }

        // Already a number
        if (typeof val === 'number') {
            return val;
        }

        // String that references a parameter (e.g., "$depth" or "$size")
        if (typeof val === 'string' && val.startsWith('$')) {
            const paramName = val.substring(1);
            const resolved = resolvedParams[paramName];
            if (resolved !== undefined && resolved !== null) {
                return resolved;
            }
            // If parameter not found, return null (will show as N/A)
            return null;
        }

        // Try to parse as number
        const parsed = Number(val);
        return isNaN(parsed) ? null : parsed;
    }

    // Get features - handle both graph.features and graph.features being undefined
    const features = graph.features || [];

    return (
        <div>
            {/* Feature Parameters */}
            {features.map((f: any) => (
                <div key={f.id} style={{ marginBottom: 12 }}>
                    <div style={{ fontSize: "12px", fontWeight: 600, color: "var(--color-text-secondary)", marginBottom: "4px", textTransform: "capitalize" }}>
                        {f.type}
                    </div>

                    <div style={{ background: "var(--color-bg-element)", borderRadius: "6px", padding: "8px" }}>
                        {f.params && Object.entries(f.params).map(([key, val]) => {
                            const unit = f.units ? f.units[key] : "mm";
                            const resolvedVal = resolveValue(val);

                            // Handle null/undefined values
                            if (resolvedVal === null) {
                                return (
                                    <div key={key} style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px", fontSize: "13px" }}>
                                        <span style={{ color: "var(--color-text-muted)", textTransform: "capitalize" }}>{key}</span>
                                        <span style={{ fontFamily: "monospace", color: "var(--color-text-muted)" }}>
                                            N/A
                                        </span>
                                    </div>
                                );
                            }

                            let displayVal = resolvedVal;
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

            {/* Top-level Parameters (showing all resolved values) */}
            {Object.keys(resolvedParams).length > 0 && (
                <div style={{ marginTop: 16 }}>
                    <div style={{ fontSize: "12px", fontWeight: 600, color: "var(--color-text-secondary)", marginBottom: "4px" }}>
                        Parameters
                    </div>
                    <div style={{ background: "var(--color-bg-element)", borderRadius: "6px", padding: "8px" }}>
                        {Object.entries(resolvedParams).map(([key, numVal]) => {
                            if (isNaN(numVal)) return null;

                            return (
                                <div key={key} style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px", fontSize: "13px" }}>
                                    <span style={{ color: "var(--color-text-muted)", textTransform: "capitalize" }}>{key}</span>
                                    <span style={{ fontFamily: "monospace", color: "var(--color-text-primary)" }}>
                                        {numVal.toFixed(2)} mm
                                    </span>
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}
        </div>
    );
}
