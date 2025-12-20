import { useState } from "react";
import LeftPanel from "./components/Panels/LeftPanel";
import Viewer from "./components/Viewer/Viewer";
import { useDesignStore } from "./store/designStore";

export default function App() {
  const current = useDesignStore((state) => state.current);
  const addCreation = useDesignStore((state) => state.addCreation);

  const [prompt, setPrompt] = useState("");
  const [loading, setLoading] = useState(false);

  async function generateModel() {
    if (!prompt.trim()) return;

    setLoading(true);

    try {
      const response = await fetch("http://127.0.0.1:8000/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt }),
      });

      const data = await response.json();

      addCreation({
        id: crypto.randomUUID(),
        prompt,
        parameters: data.parameters || {},
        material: {
          roughness: 0.4,
          metalness: 0.6,
        },
        files: {
          glb: "http://127.0.0.1:8000/" + data.files.glb,
          step: "http://127.0.0.1:8000/" + data.files.step,
        },
      });

      setPrompt("");
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      style={{
        display: "flex",
        height: "100vh",
        width: "100vw",
        overflow: "hidden",
        background: "#0d0d0d",
        color: "#eee",
      }}
    >
      {/* LEFT PANEL */}
      <LeftPanel />

      {/* CENTER PANEL */}
      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          position: "relative",
        }}
      >
        {/* TOP INPUT BAR */}
        <div
          style={{
            padding: "12px",
            borderBottom: "1px solid #222",
            background: "#111",
          }}
        >
          <h2 style={{ margin: "0 0 8px 0", fontSize: "16px" }}>
            OrionFlow – AI CAD
          </h2>

          <textarea
            placeholder="Describe your part..."
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={2}
            style={{
              width: "100%",
              padding: "8px",
              background: "#0d0d0d",
              color: "#eee",
              border: "1px solid #333",
              resize: "none",
            }}
          />

          <button
            onClick={generateModel}
            disabled={loading}
            style={{
              marginTop: "8px",
              padding: "8px 16px",
              cursor: loading ? "not-allowed" : "pointer",
              background: "#1a1a1a",
              color: "#eee",
              border: "1px solid #333",
            }}
          >
            {loading ? "Generating..." : "Generate"}
          </button>
        </div>

        {/* 3D VIEWER */}
        <div style={{ flex: 1, position: "relative" }}>
          {current && <Viewer url={current.files.glb} />}
        </div>

        {/* FOOTER ACTIONS */}
        {current && (
          <div
            style={{
              padding: "10px",
              borderTop: "1px solid #222",
              background: "#111",
            }}
          >
            <a
              href={current.files.step}
              download
              style={{ color: "#9cdcfe", fontSize: "13px" }}
            >
              Download STEP
            </a>
          </div>
        )}
      </div>
    </div>
  );
}


