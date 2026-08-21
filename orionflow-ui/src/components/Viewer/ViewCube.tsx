import { GizmoHelper, GizmoViewcube } from "@react-three/drei";
import { useUIStore } from "../../store/uiStore";

/**
 * The orientation cube.
 *
 * Its colours are read from the theme rather than fixed. They used to be a
 * hard-coded white cube with black text, which was legible on the dark
 * viewport and invisible on the light one — a white cube on pale vellum is a
 * control the user cannot see, which is worse than not shipping it.
 *
 * The values are literals rather than CSS custom properties because this is
 * painted by three.js, which cannot resolve `var(--st-ink)`. They are the
 * viewport's own greys, one step lifted from the ground behind them so the cube
 * reads as an object sitting in the scene.
 */

const FACES = {
    dark: {
        color: "#1F2126",
        hoverColor: "#2C2F36",
        textColor: "#F5F2ED",
        strokeColor: "#3B3F47",
    },
    light: {
        color: "#FBF9F6",
        hoverColor: "#E9E4DC",
        textColor: "#11100E",
        strokeColor: "#B4ADA3",
    },
} as const;

export default function ViewCube() {
    const theme = useUIStore((s) => s.theme);
    const face = FACES[theme === "light" ? "light" : "dark"];

    return (
        <GizmoHelper
            alignment="bottom-right"
            margin={[80, 80]}
            onUpdate={() => {}} // fixes a known type issue in some versions
        >
            <GizmoViewcube
                // The interface face, so the cube's labels are set in the same
                // type as everything else on screen.
                font="600 15px 'Instrument Sans', sans-serif"
                opacity={1}
                {...face}
            />
        </GizmoHelper>
    );
}
