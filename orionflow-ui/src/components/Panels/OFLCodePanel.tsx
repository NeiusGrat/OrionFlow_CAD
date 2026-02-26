import { useState } from 'react';
import { useOFLStore } from '../../store/oflStore';
import { Code, Play, Download } from 'lucide-react';

export default function OFLCodePanel() {
    const {
        oflCode, parameters, error, generationTimeMs,
        setCode, rebuild, updateParameter, stepUrl, stlUrl,
    } = useOFLStore();

    const [isEditing, setIsEditing] = useState(false);
    const [editedCode, setEditedCode] = useState('');

    const handleEdit = () => {
        setIsEditing(true);
        setEditedCode(oflCode);
    };

    const handleRebuild = () => {
        setIsEditing(false);
        setCode(editedCode);
        rebuild(editedCode);
    };

    if (!oflCode) return null;

    return (
        <div style={{
            width: "340px",
            background: "#0a0a0a",
            borderLeft: "1px solid #1f1f1f",
            display: "flex",
            flexDirection: "column",
            height: "100%",
            flexShrink: 0,
            overflow: "hidden",
        }}>
            {/* Header */}
            <div style={{
                padding: "12px 16px",
                borderBottom: "1px solid #1f1f1f",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
            }}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                    <Code size={16} style={{ color: "#3b82f6" }} />
                    <span style={{ fontSize: "13px", fontWeight: 600, color: "#fff" }}>
                        OFL Code
                    </span>
                </div>
                {!isEditing ? (
                    <button
                        onClick={handleEdit}
                        style={{
                            background: "#1f1f1f", border: "1px solid #333",
                            borderRadius: "6px", padding: "4px 10px",
                            color: "#a1a1aa", fontSize: "12px", cursor: "pointer",
                        }}
                    >
                        Edit
                    </button>
                ) : (
                    <button
                        onClick={handleRebuild}
                        style={{
                            background: "#3b82f6", border: "none",
                            borderRadius: "6px", padding: "4px 10px",
                            color: "#fff", fontSize: "12px", cursor: "pointer",
                            display: "flex", alignItems: "center", gap: "4px",
                        }}
                    >
                        <Play size={12} /> Rebuild
                    </button>
                )}
            </div>

            {/* Code */}
            <div style={{ flex: 1, overflow: "auto", padding: "12px" }}>
                {isEditing ? (
                    <textarea
                        value={editedCode}
                        onChange={e => setEditedCode(e.target.value)}
                        style={{
                            width: "100%", minHeight: "200px",
                            background: "#111", color: "#d4d4d4",
                            border: "1px solid #333", borderRadius: "6px",
                            padding: "10px", fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
                            fontSize: "12px", lineHeight: "1.6", resize: "vertical",
                            outline: "none",
                        }}
                        spellCheck={false}
                    />
                ) : (
                    <pre style={{
                        background: "#111", color: "#d4d4d4",
                        padding: "10px", borderRadius: "6px",
                        fontSize: "12px", lineHeight: "1.6",
                        fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
                        overflow: "auto", margin: 0, whiteSpace: "pre-wrap",
                    }}>
                        {oflCode}
                    </pre>
                )}

                {/* Parameters */}
                {parameters.length > 0 && (
                    <div style={{ marginTop: "16px" }}>
                        <span style={{ fontSize: "12px", fontWeight: 600, color: "#a1a1aa", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                            Parameters
                        </span>
                        {parameters.map(p => (
                            <div key={p.name} style={{
                                display: "flex", alignItems: "center", gap: "8px",
                                marginTop: "8px",
                            }}>
                                <label style={{ width: "100px", fontSize: "12px", color: "#a1a1aa", flexShrink: 0 }}>
                                    {p.name}
                                </label>
                                <input
                                    type="range"
                                    min={Math.max(0.5, p.value * 0.2)}
                                    max={p.value * 3}
                                    step={p.value >= 10 ? 1 : 0.5}
                                    value={p.value}
                                    onChange={e => updateParameter(p.name, parseFloat(e.target.value))}
                                    style={{ flex: 1, accentColor: "#3b82f6" }}
                                />
                                <span style={{ width: "50px", fontSize: "12px", color: "#e4e4e7", textAlign: "right" }}>
                                    {p.value}
                                </span>
                            </div>
                        ))}
                    </div>
                )}

                {/* Downloads */}
                {(stepUrl || stlUrl) && (
                    <div style={{ marginTop: "16px", display: "flex", gap: "8px" }}>
                        {stepUrl && (
                            <a href={stepUrl} download style={{
                                display: "flex", alignItems: "center", gap: "4px",
                                background: "#1f1f1f", border: "1px solid #333",
                                borderRadius: "6px", padding: "6px 12px",
                                color: "#a1a1aa", fontSize: "12px",
                                textDecoration: "none",
                            }}>
                                <Download size={12} /> .step
                            </a>
                        )}
                        {stlUrl && (
                            <a href={stlUrl} download style={{
                                display: "flex", alignItems: "center", gap: "4px",
                                background: "#1f1f1f", border: "1px solid #333",
                                borderRadius: "6px", padding: "6px 12px",
                                color: "#a1a1aa", fontSize: "12px",
                                textDecoration: "none",
                            }}>
                                <Download size={12} /> .stl
                            </a>
                        )}
                    </div>
                )}

                {/* Error */}
                {error && (
                    <div style={{
                        marginTop: "12px", padding: "8px 10px",
                        background: "rgba(239, 68, 68, 0.1)",
                        border: "1px solid rgba(239, 68, 68, 0.3)",
                        borderRadius: "6px", fontSize: "12px", color: "#f87171",
                    }}>
                        {error}
                    </div>
                )}

                {/* Timing */}
                {generationTimeMs > 0 && (
                    <div style={{ marginTop: "8px", fontSize: "11px", color: "#52525b" }}>
                        Generated in {(generationTimeMs / 1000).toFixed(1)}s
                    </div>
                )}
            </div>
        </div>
    );
}
