import { useDesignStore } from "../../store/designStore";

export default function ParamPanel() {
    const current = useDesignStore((s) => s.current);

    if (!current || !current.featureGraph) return null;

    const graph = current.featureGraph;

    async function updateFeature(featureIndex: number, key: string, value: number) {
        const updatedGraph = { ...graph };
        updatedGraph.features = [...graph.features];
        updatedGraph.features[featureIndex] = {
            ...graph.features[featureIndex],
            params: {
                ...graph.features[featureIndex].params,
                [key]: value,
            },
        };

        const res = await fetch("http://127.0.0.1:8000/regenerate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ feature_graph: updatedGraph }),
        });

        const data = await res.json();

        // Get fresh state
        const freshCurrent = useDesignStore.getState().current;
        if (!freshCurrent) return;

        useDesignStore.setState({
            current: {
                ...freshCurrent,
                featureGraph: data.feature_graph,
                files: {
                    ...freshCurrent.files,
                    step: "http://127.0.0.1:8000/" + data.files.step,
                    glb: "http://127.0.0.1:8000/" + data.files.glb,
                },
            },
        });
    }

    return (
        <div>
            <h3 style={{ fontSize: 14 }}>Parameters</h3>

            {graph.features.map((f: any, i: number) => (
                <div key={f.id} style={{ marginBottom: 12 }}>
                    <div style={{ fontSize: 12, opacity: 0.7 }}>{f.type}</div>

                    {Object.entries(f.params).map(([key, val]) => (
                        <div key={key}>
                            <label style={{ fontSize: 12 }}>
                                {key}: {Number(val).toFixed(1)}
                            </label>

                            <input
                                type="range"
                                min={1}
                                max={200}
                                value={Number(val)}
                                onChange={(e) =>
                                    updateFeature(i, key, Number(e.target.value))
                                }
                                style={{ width: "100%" }}
                            />
                        </div>
                    ))}
                </div>
            ))}
        </div>
    );
}
