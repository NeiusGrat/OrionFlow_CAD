import React, { useEffect, useRef, useState } from "react";

interface AdamSliderProps {
    label: string;
    value: number;
    min: number;
    max: number;
    step?: number;
    unit?: string;
    onChange: (value: number) => void;
}

export default function AdamSlider({
    label,
    value,
    min,
    max,
    step = 1,
    unit = "",
    onChange,
}: AdamSliderProps) {
    const [internalValue, setInternalValue] = useState(value);
    const trackRef = useRef<HTMLDivElement>(null);
    const isDragging = useRef(false);

    useEffect(() => {
        setInternalValue(value);
    }, [value]);

    const handlePointerDown = (e: React.PointerEvent) => {
        isDragging.current = true;
        updateValue(e.clientX);
        e.currentTarget.setPointerCapture(e.pointerId);
    };

    const handlePointerMove = (e: React.PointerEvent) => {
        if (!isDragging.current) return;
        updateValue(e.clientX);
    };

    const handlePointerUp = (e: React.PointerEvent) => {
        isDragging.current = false;
        e.currentTarget.releasePointerCapture(e.pointerId);
    };

    const updateValue = (clientX: number) => {
        if (!trackRef.current) return;
        const rect = trackRef.current.getBoundingClientRect();
        const percent = Math.min(Math.max((clientX - rect.left) / rect.width, 0), 1);
        const newValue = min + percent * (max - min);

        // Snap to step
        const steppedValue = Math.round(newValue / step) * step;
        const clampedValue = Math.min(Math.max(steppedValue, min), max); // Ensure within bounds

        setInternalValue(clampedValue);
        onChange(clampedValue);
    };

    const percent = ((internalValue - min) / (max - min)) * 100;

    return (
        <div style={{ marginBottom: "16px", userSelect: "none" }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "8px", alignItems: "center" }}>
                <label style={{
                    fontSize: "12px",
                    fontWeight: 600,
                    color: "var(--color-text-secondary)",
                    letterSpacing: "0.5px",
                    textTransform: "capitalize"
                }}>
                    {label}
                </label>
                <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                    <input
                        type="number"
                        value={internalValue}
                        onChange={(e) => onChange(Number(e.target.value))}
                        style={{
                            background: "transparent",
                            border: "none",
                            color: "var(--color-text-primary)",
                            fontSize: "13px",
                            width: "40px",
                            textAlign: "right",
                            padding: 0,
                            fontWeight: 500
                        }}
                    />
                    <span style={{ fontSize: "11px", color: "var(--color-text-muted)" }}>{unit}</span>
                </div>
            </div>

            <div
                ref={trackRef}
                onPointerDown={handlePointerDown}
                onPointerMove={handlePointerMove}
                onPointerUp={handlePointerUp}
                style={{
                    width: "100%",
                    height: "24px",
                    background: "#1ea2e022", // Very subtle opacity of the blue (or just dark bg)
                    backgroundColor: "#27272a", // Dark track
                    borderRadius: "6px",
                    position: "relative",
                    cursor: "ew-resize",
                    overflow: "hidden"
                }}
            >
                {/* Fill */}
                <div
                    style={{
                        position: "absolute",
                        left: 0,
                        top: 0,
                        bottom: 0,
                        width: `${percent}%`,
                        background: "#40a9ff", // Lighter blue for better visibility
                        backgroundColor: "var(--color-accent)",
                        borderRight: "2px solid rgba(255,255,255,0.2)"
                    }}
                />

                {/* Ticks overlay (visual candy) */}
                <div style={{
                    position: "absolute",
                    inset: 0,
                    display: "flex",
                    justifyContent: "space-between",
                    padding: "0 2px",
                    pointerEvents: "none",
                    opacity: 0.1
                }}>
                    {[...Array(10)].map((_, i) => (
                        <div key={i} style={{ width: "1px", height: "100%", background: "white" }} />
                    ))}
                </div>
            </div>
        </div>
    );
}
