import { useState } from "react";
import LeftPanel from "./components/Panels/LeftPanel";
import RightPanel from "./components/Panels/RightPanel";
import Viewer from "./components/Viewer/Viewer";
import { useDesignStore } from "./store/designStore";
import { Loader2, Box, LayoutGrid, RotateCcw } from "lucide-react";

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

  // --- HOME VIEW ---
  if (!current && !loading) {
    return (
      <div style={{
        height: "100vh", width: "100vw",
        background: "var(--color-bg-app)",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontFamily: "'Inter', sans-serif"
      }}>
        <div style={{ width: "100%", maxWidth: "700px", padding: "20px", textAlign: "center" }}>
          {/* LOGO */}
          <div style={{ marginBottom: "40px", display: "inline-flex", alignItems: "center", gap: "12px" }}>
            <div style={{
              width: "48px", height: "48px",
              background: "linear-gradient(135deg, var(--color-accent) 0%, #60a5fa 100%)",
              borderRadius: "14px", display: "flex", alignItems: "center", justifyContent: "center",
              color: "white", boxShadow: "0 10px 30px rgba(59, 130, 246, 0.3)"
            }}>
              <Box size={28} strokeWidth={3} />
            </div>
            <h1 style={{ fontSize: "32px", fontWeight: 700, letterSpacing: "-1px" }}>OrionFlow</h1>
          </div>

          {/* BIG PROMPT INPUT */}
          <div style={{
            background: "var(--color-bg-panel)",
            border: "1px solid var(--color-border)",
            borderRadius: "16px",
            padding: "8px",
            display: "flex",
            alignItems: "center",
            boxShadow: "0 20px 40px rgba(0,0,0,0.4)"
          }}>
            <input
              type="text"
              placeholder="Describe what you want to make (e.g. 'A futuristic drone chassis')..."
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && generateModel()}
              autoFocus
              style={{
                flex: 1,
                background: "transparent",
                border: "none",
                fontSize: "18px",
                padding: "16px",
                outline: "none",
                color: "var(--color-text-primary)"
              }}
            />
            <button
              onClick={generateModel}
              disabled={!prompt.trim()}
              style={{
                height: "50px",
                padding: "0 30px",
                borderRadius: "12px",
                background: "var(--color-accent)",
                color: "white",
                border: "none",
                fontSize: "16px",
                fontWeight: 600,
                cursor: "pointer",
                opacity: !prompt.trim() ? 0.5 : 1
              }}
            >
              Generate
            </button>
          </div>

          <div style={{ marginTop: "30px", color: "var(--color-text-muted)", fontSize: "14px" }}>
            Try: <span style={{ color: "var(--color-accent)", cursor: "pointer" }}>Planetary Gearbox</span>, <span style={{ color: "var(--color-accent)", cursor: "pointer" }}>Laptop Stand</span>
          </div>
        </div>
      </div>
    );
  }

  // --- EDITOR VIEW ---
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
      {/* LEFT PANEL (Includes Chat/Prompt in Editor Mode) */}
      <LeftPanel />

      {/* CENTER WORKSPACE */}
      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          position: "relative",
          background: "#f8f9fa", // White/Light grey CAD background
        }}
      >
        {/* LOADING OVERLAY */}
        {loading && (
          <div style={{
            position: "absolute", zIndex: 50, inset: 0,
            background: "rgba(0,0,0,0.7)", backdropFilter: "blur(10px)",
            display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
            color: "white"
          }}>
            <Loader2 size={48} className="animate-spin" color="var(--color-accent)" />
            <p style={{ marginTop: "20px", fontSize: "18px", fontWeight: 500 }}>Generating 3D Model...</p>
            <p style={{ marginTop: "8px", fontSize: "14px", opacity: 0.7 }}>This might take a few moments</p>
          </div>
        )}

        {/* 3D VIEWER */}
        <div style={{ flex: 1, position: "relative" }}>
          <Viewer url={current ? current.files.glb : ""} />
        </div>

        {/* BOTTOM VIEW CONTROLS (Ortho/Iso/Reset) */}
        {!loading && (
          <div style={{
            position: "absolute",
            bottom: "24px",
            left: "50%",
            transform: "translateX(-50%)",
            background: "#ffffff",
            border: "1px solid #e5e7eb",
            borderRadius: "99px",
            padding: "8px 20px",
            display: "flex",
            gap: "20px",
            alignItems: "center",
            boxShadow: "0 10px 30px rgba(0,0,0,0.1)",
            color: "#374151"
          }}>
            <div
              style={{ display: "flex", alignItems: "center", gap: "8px", cursor: "pointer", fontSize: "13px", fontWeight: 600 }}
              onClick={() => {
                const camera = useDesignStore.getState().camera
                if (camera) {
                  camera.position.set(0, 10, 0);
                  camera.lookAt(0, 0, 0);
                  camera.updateProjectionMatrix();
                }
              }}
            >
              <LayoutGrid size={16} />
              <span>Orthographic</span>
            </div>
            <div style={{ width: "1px", height: "16px", background: "#e5e7eb" }} />
            <div
              style={{ display: "flex", alignItems: "center", gap: "8px", cursor: "pointer", fontSize: "13px", fontWeight: 600 }}
              onClick={() => {
                const camera = useDesignStore.getState().camera
                if (camera) {
                  camera.position.set(5, 5, 5);
                  camera.lookAt(0, 0, 0);
                  camera.updateProjectionMatrix();
                }
              }}
            >
              <Box size={16} />
              <span>Isometric</span>
            </div>
            <div style={{ width: "1px", height: "16px", background: "#e5e7eb" }} />
            <div
              style={{ display: "flex", alignItems: "center", gap: "8px", cursor: "pointer", fontSize: "13px", fontWeight: 600 }}
              onClick={() => {
                const camera = useDesignStore.getState().camera
                if (camera) {
                  camera.position.set(5, 5, 5);
                  camera.lookAt(0, 0, 0);
                  camera.updateProjectionMatrix();
                }
              }}
            >
              <RotateCcw size={16} />
              <span>Reset</span>
            </div>
          </div>
        )}
      </div>

      {/* RIGHT PANEL */}
      <RightPanel />
    </div>
  );
}
