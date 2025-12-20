import { useState } from "react";
import LeftPanel from "./components/Panels/LeftPanel";
import RightPanel from "./components/Panels/RightPanel";
import Viewer from "./components/Viewer/Viewer";
import { useDesignStore } from "./store/designStore";
import { Loader2, Sparkles } from "lucide-react";

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
        background: "var(--color-bg-app)",
        color: "var(--color-text-primary)",
      }}
    >
      {/* LEFT PANEL */}
      <LeftPanel />

      {/* CENTER WORKSPACE */}
      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          position: "relative",
          background: "radial-gradient(circle at center, #1a1a1a 0%, #0b0b0b 100%)",
        }}
      >
        {/* FLOATING PROMPT BAR */}
        <div
          style={{
            position: "absolute",
            top: "20px",
            left: "50%",
            transform: "translateX(-50%)",
            width: "600px",
            maxWidth: "90%",
            zIndex: 10,
            display: "flex",
            flexDirection: "column",
            gap: "8px",
          }}
        >
          <div
            style={{
              background: "rgba(17, 17, 17, 0.8)",
              backdropFilter: "blur(12px)",
              border: "1px solid var(--color-border)",
              borderRadius: "12px",
              padding: "4px",
              display: "flex",
              alignItems: "center",
              boxShadow: "0 4px 20px rgba(0,0,0,0.3)",
            }}
          >
            <div style={{ padding: "0 12px", color: "var(--color-text-muted)" }}>
              <Sparkles size={16} />
            </div>
            <input
              type="text"
              placeholder="Describe your part to generate..."
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && generateModel()}
              style={{
                flex: 1,
                border: "none",
                background: "transparent",
                padding: "12px 0",
                fontSize: "14px",
                color: "var(--color-text-primary)",
                outline: "none",
              }}
            />
            <button
              onClick={generateModel}
              disabled={loading || !prompt.trim()}
              style={{
                background: "var(--color-accent)",
                border: "none",
                color: "white",
                padding: "6px 16px",
                borderRadius: "8px",
                display: "flex",
                alignItems: "center",
                gap: "8px",
                fontSize: "13px",
                fontWeight: 600,
                opacity: (loading || !prompt.trim()) ? 0.7 : 1,
              }}
            >
              {loading ? <Loader2 size={14} className="animate-spin" /> : null}
              {loading ? "Generating" : "Generate"}
            </button>
          </div>
        </div>

        {/* 3D VIEWER */}
        <div style={{ flex: 1, position: "relative" }}>
          <Viewer url={current ? current.files.glb : ""} />

          {/* EMPTY STATE IF NO MODEL */}
          {!current && !loading && (
            <div style={{
              position: "absolute",
              top: "50%",
              left: "50%",
              transform: "translate(-50%, -50%)",
              textAlign: "center",
              color: "var(--color-text-muted)",
              pointerEvents: "none"
            }}>
              <p>Type a prompt to get started</p>
            </div>
          )}
        </div>

        {/* BOTTOM TOOLBAR OVERLAY */}
        <div style={{
          position: "absolute",
          bottom: "20px",
          left: "50%",
          transform: "translateX(-50%)",
          background: "rgba(17, 17, 17, 0.8)",
          backdropFilter: "blur(8px)",
          border: "1px solid var(--color-border)",
          borderRadius: "full",
          padding: "6px 12px",
          display: "flex",
          gap: "12px",
          alignItems: "center"
        }}>
          {[...Array(3)].map((_, i) => (
            <div key={i} style={{
              width: "24px",
              height: "24px",
              borderRadius: "50%",
              background: i === 0 ? "var(--color-accent)" : "#333",
              cursor: "pointer",
              border: "1px solid rgba(255,255,255,0.1)"
            }} />
          ))}
          <div style={{ width: "1px", height: "16px", background: "#333" }} />
          <div style={{ fontSize: "12px", color: "var(--color-text-muted)" }}>Auto-Rotation</div>
        </div>
      </div>

      {/* RIGHT PANEL */}
      <RightPanel />
    </div>
  );
}
