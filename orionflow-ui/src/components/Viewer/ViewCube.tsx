import { GizmoHelper, GizmoViewcube } from "@react-three/drei";

export default function ViewCube() {
    return (
        <GizmoHelper
            alignment="bottom-right"
            margin={[80, 80]}
            onUpdate={() => { }} // fixes a known type issue in some versions
        >
            <GizmoViewcube
                font="16px Inter"
                opacity={1}
                color="white"
                hoverColor="#d1d5db"
                textColor="black"
                strokeColor="#a1a1aa"
            />
        </GizmoHelper>
    );
}

