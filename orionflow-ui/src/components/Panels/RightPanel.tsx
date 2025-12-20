import { useDesignStore } from "../../store/designStore";

export default function RightPanel() {
    const current = useDesignStore((state) => state.current);
    const creations = useDesignStore((state) => state.creations);

    if (!current) {
        return (
            <div
                style={{
                    width: "260px",
                    background: "#111",
                    color: "#777",
                    borderLeft: "1px solid #222",
                    padding: "12px",
                    boxSizing: "border-box",
                }}
            >
                <div style={{ fontSize: "12px" }}>No active design</div>
            </div>
        );
    }

    function updateMaterial(key: "roughness" | "metalness", value: number) {
        const updated = {
            ...current,
            material: {
                ...current.material,
                [key]: value,
            },
        };

        const updatedCreations = creations.map((c) =>
            c.id === current.id ? updated : c
        );

        useDesignStore.setState({
            creations: updatedCreations,
            current: updated,
        });
    }

    function setCameraView(position: [number, number, number]) {
        const camera = useDesignStore.getState().camera;
        if (!camera) return;

        camera.position.set(position[0], position[1], position[2]);
        camera.lookAt(0, 0, 0);
    }

    return (
        <div
            style={{
                width: "260px",
                background: "#111",
                color: "#eee",
                borderLeft: "1px solid #222",
                padding: "12px",
                boxSizing: "border-box",
            }}
        >
            {/* APPEARANCE */}
            <h3 style={{ fontSize: "14px", marginBottom: "12px" }}>
                Appearance
            </h3>

            {/* Roughness */}
            <div style={{ marginBottom: "14px" }}>
                <label style={{ fontSize: "12px" }}>
                    Roughness: {current.material.roughness.toFixed(2)}
                </label>
                <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.01}
                    value={current.material.roughness}
                    onChange={(e) =>
                        updateMaterial("roughness", Number(e.target.value))
                    }
                    style={{ width: "100%" }}
                />
            </div>

            {/* Metalness */}
            <div style={{ marginBottom: "20px" }}>
                <label style={{ fontSize: "12px" }}>
                    Metalness: {current.material.metalness.toFixed(2)}
                </label>
                <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.01}
                    value={current.material.metalness}
                    onChange={(e) =>
                        updateMaterial("metalness", Number(e.target.value))
                    }
                    style={{ width: "100%" }}
                />
            </div>

            {/* CAMERA VIEWS */}
            <h3 style={{ fontSize: "14px", marginBottom: "8px" }}>
                Views
            </h3>

            <button
                style={{ width: "100%", marginBottom: "6px" }}
                onClick={() => setCameraView([0, 0, 5])}
            >
                Front
            </button>

            <button
                style={{ width: "100%", marginBottom: "6px" }}
                onClick={() => setCameraView([0, 5, 0])}
            >
                Top
            </button>

            <button
                style={{ width: "100%", marginBottom: "16px" }}
                onClick={() => setCameraView([5, 5, 5])}
            >
                Iso
            </button>

            {/* EXPORT */}
            <h3 style={{ fontSize: "14px", marginBottom: "8px" }}>
                Export
            </h3>

            <a
                href={current.files.step}
                download
                style={{
                    display: "block",
                    fontSize: "12px",
                    color: "#9cdcfe",
                    marginBottom: "6px",
                }}
            >
                Download STEP
            </a>

            <a
                href={current.files.glb}
                download
                style={{
                    display: "block",
                    fontSize: "12px",
                    color: "#9cdcfe",
                }}
            >
                Download GLB
            </a>
        </div>
    );
}

