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
        // Lifted well clear of the viewport, which is #0A0A0B at its darkest
        // and #17181A at its lightest. The cube used to be #1F2126 with a
        // #3B3F47 stroke — one step off the ground behind it, so on the dark
        // theme it was a black cube on a black background and users could not
        // find the control at all.
        //
        // Real CAD nav cubes solve this the same way: the cube is a lit object
        // sitting in front of the scene, not a tint of it. #454B55 is the
        // lightest value that still reads as part of this interface rather
        // than as a white box pasted on top, and the stroke is bright enough
        // to draw the silhouette against both the viewport and the part.
        color: "#454B55",
        hoverColor: "#5E6675",
        textColor: "#F7F5F1",
        strokeColor: "#9AA3B2",
    },
    light: {
        color: "#FBF9F6",
        hoverColor: "#E9E4DC",
        textColor: "#11100E",
        strokeColor: "#8E877C",
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
