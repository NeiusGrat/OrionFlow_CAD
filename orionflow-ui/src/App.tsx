import { useState } from "react";
import ModelViewer from "./ModelViewer";

export default function App() {
  const [prompt, setPrompt] = useState("");
  const [glbUrl, setGlbUrl] = useState<string | null>(null);
  const [stepUrl, setStepUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function generateModel() {
    setLoading(true);
    setGlbUrl(null);
    setStepUrl(null);

    const response = await fetch("http://127.0.0.1:8000/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });

    const data = await response.json();

    setGlbUrl("http://127.0.0.1:8000/" + data.files.glb);
    setStepUrl("http://127.0.0.1:8000/" + data.files.step);

    setLoading(false);
  }

  return (
    <div style={{ padding: 20 }}>
      <h1>OrionFlow – AI CAD</h1>

      <textarea
        placeholder="Describe your part..."
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        rows={3}
        style={{ width: "100%", marginBottom: 10 }}
      />

      <button onClick={generateModel} disabled={loading}>
        {loading ? "Generating..." : "Generate"}
      </button>

      {glbUrl && <ModelViewer url={glbUrl} />}

      {stepUrl && (
        <a href={stepUrl} download style={{ display: "block", marginTop: 10 }}>
          Download STEP
        </a>
      )}
    </div>
  );
}
