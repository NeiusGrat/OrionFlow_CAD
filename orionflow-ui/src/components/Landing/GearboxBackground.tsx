import { useRef, useMemo } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import * as THREE from 'three';

// Individual gear component
function Gear({
    position,
    rotation,
    teeth,
    innerRadius,
    outerRadius,
    thickness,
    rotationSpeed,
    color
}: {
    position: [number, number, number];
    rotation: [number, number, number];
    teeth: number;
    innerRadius: number;
    outerRadius: number;
    thickness: number;
    rotationSpeed: number;
    color: string;
}) {
    const meshRef = useRef<THREE.Mesh>(null);

    const geometry = useMemo(() => {
        const shape = new THREE.Shape();
        const toothDepth = (outerRadius - innerRadius) * 0.4;
        const toothWidth = (2 * Math.PI) / teeth / 2;

        // Create gear profile
        for (let i = 0; i < teeth; i++) {
            const angle = (i / teeth) * Math.PI * 2;
            const nextAngle = ((i + 1) / teeth) * Math.PI * 2;
            const midAngle = angle + toothWidth;

            const innerX1 = Math.cos(angle) * innerRadius;
            const innerY1 = Math.sin(angle) * innerRadius;
            const outerX1 = Math.cos(angle + toothWidth * 0.2) * outerRadius;
            const outerY1 = Math.sin(angle + toothWidth * 0.2) * outerRadius;
            const outerX2 = Math.cos(midAngle - toothWidth * 0.2) * outerRadius;
            const outerY2 = Math.sin(midAngle - toothWidth * 0.2) * outerRadius;
            const innerX2 = Math.cos(midAngle) * (innerRadius + toothDepth * 0.1);
            const innerY2 = Math.sin(midAngle) * (innerRadius + toothDepth * 0.1);

            if (i === 0) {
                shape.moveTo(innerX1, innerY1);
            }
            shape.lineTo(outerX1, outerY1);
            shape.lineTo(outerX2, outerY2);
            shape.lineTo(innerX2, innerY2);
        }
        shape.closePath();

        // Add center hole
        const hole = new THREE.Path();
        const holeRadius = innerRadius * 0.4;
        hole.absarc(0, 0, holeRadius, 0, Math.PI * 2, true);
        shape.holes.push(hole);

        const extrudeSettings = {
            steps: 1,
            depth: thickness,
            bevelEnabled: true,
            bevelThickness: 0.02,
            bevelSize: 0.02,
            bevelSegments: 2,
        };

        return new THREE.ExtrudeGeometry(shape, extrudeSettings);
    }, [teeth, innerRadius, outerRadius, thickness]);

    useFrame((state) => {
        if (meshRef.current) {
            meshRef.current.rotation.z += rotationSpeed;
        }
    });

    return (
        <mesh ref={meshRef} position={position} rotation={rotation} geometry={geometry}>
            <meshStandardMaterial
                color={color}
                metalness={0.9}
                roughness={0.3}
                transparent
                opacity={0.15}
            />
        </mesh>
    );
}

// Wire frame gear for extra detail
function WireGear({
    position,
    rotation,
    radius,
    rotationSpeed,
}: {
    position: [number, number, number];
    rotation: [number, number, number];
    radius: number;
    rotationSpeed: number;
}) {
    const meshRef = useRef<THREE.Mesh>(null);

    useFrame(() => {
        if (meshRef.current) {
            meshRef.current.rotation.z += rotationSpeed;
        }
    });

    return (
        <mesh ref={meshRef} position={position} rotation={rotation}>
            <torusGeometry args={[radius, 0.02, 8, 64]} />
            <meshBasicMaterial color="#3b82f6" transparent opacity={0.2} />
        </mesh>
    );
}

// Technical grid lines
function TechGrid() {
    const points = useMemo(() => {
        const pts: THREE.Vector3[] = [];
        const size = 20;
        const divisions = 20;
        const step = size / divisions;

        for (let i = -divisions / 2; i <= divisions / 2; i++) {
            pts.push(new THREE.Vector3(i * step, -size / 2, 0));
            pts.push(new THREE.Vector3(i * step, size / 2, 0));
            pts.push(new THREE.Vector3(-size / 2, i * step, 0));
            pts.push(new THREE.Vector3(size / 2, i * step, 0));
        }
        return pts;
    }, []);

    return (
        <lineSegments position={[0, 0, -5]}>
            <bufferGeometry>
                <bufferAttribute
                    attach="attributes-position"
                    count={points.length}
                    array={new Float32Array(points.flatMap(p => [p.x, p.y, p.z]))}
                    itemSize={3}
                />
            </bufferGeometry>
            <lineBasicMaterial color="#1e3a5f" transparent opacity={0.15} />
        </lineSegments>
    );
}

// Floating particles
function Particles() {
    const particlesRef = useRef<THREE.Points>(null);

    const [positions, velocities] = useMemo(() => {
        const count = 50;
        const pos = new Float32Array(count * 3);
        const vel = new Float32Array(count * 3);

        for (let i = 0; i < count; i++) {
            pos[i * 3] = (Math.random() - 0.5) * 15;
            pos[i * 3 + 1] = (Math.random() - 0.5) * 15;
            pos[i * 3 + 2] = (Math.random() - 0.5) * 5;

            vel[i * 3] = (Math.random() - 0.5) * 0.01;
            vel[i * 3 + 1] = (Math.random() - 0.5) * 0.01;
            vel[i * 3 + 2] = 0;
        }

        return [pos, vel];
    }, []);

    useFrame(() => {
        if (particlesRef.current) {
            const posAttr = particlesRef.current.geometry.attributes.position;
            for (let i = 0; i < posAttr.count; i++) {
                posAttr.array[i * 3] += velocities[i * 3];
                posAttr.array[i * 3 + 1] += velocities[i * 3 + 1];

                // Wrap around
                if (Math.abs(posAttr.array[i * 3]) > 7.5) velocities[i * 3] *= -1;
                if (Math.abs(posAttr.array[i * 3 + 1]) > 7.5) velocities[i * 3 + 1] *= -1;
            }
            posAttr.needsUpdate = true;
        }
    });

    return (
        <points ref={particlesRef}>
            <bufferGeometry>
                <bufferAttribute
                    attach="attributes-position"
                    count={positions.length / 3}
                    array={positions}
                    itemSize={3}
                />
            </bufferGeometry>
            <pointsMaterial
                size={0.05}
                color="#60a5fa"
                transparent
                opacity={0.4}
                sizeAttenuation
            />
        </points>
    );
}

// Scene composition
function Scene() {
    const groupRef = useRef<THREE.Group>(null);

    useFrame((state) => {
        if (groupRef.current) {
            groupRef.current.rotation.x = Math.sin(state.clock.elapsedTime * 0.1) * 0.05;
            groupRef.current.rotation.y = Math.sin(state.clock.elapsedTime * 0.15) * 0.05;
        }
    });

    return (
        <group ref={groupRef}>
            {/* Main large gear */}
            <Gear
                position={[3, -1, -2]}
                rotation={[0.3, 0.2, 0]}
                teeth={24}
                innerRadius={1.5}
                outerRadius={2.2}
                thickness={0.3}
                rotationSpeed={0.002}
                color="#3b82f6"
            />

            {/* Secondary gear - meshed with main */}
            <Gear
                position={[0.5, 1.5, -1.5]}
                rotation={[0.2, -0.1, 0]}
                teeth={16}
                innerRadius={0.8}
                outerRadius={1.3}
                thickness={0.25}
                rotationSpeed={-0.003}
                color="#60a5fa"
            />

            {/* Small accent gear */}
            <Gear
                position={[-3, -2, -1]}
                rotation={[-0.2, 0.3, 0]}
                teeth={12}
                innerRadius={0.5}
                outerRadius={0.9}
                thickness={0.2}
                rotationSpeed={0.004}
                color="#2563eb"
            />

            {/* Another accent gear top-left */}
            <Gear
                position={[-4, 2.5, -2.5]}
                rotation={[0.4, -0.2, 0]}
                teeth={20}
                innerRadius={1}
                outerRadius={1.6}
                thickness={0.2}
                rotationSpeed={-0.0025}
                color="#1d4ed8"
            />

            {/* Wire frame accents */}
            <WireGear position={[4.5, 2, -3]} rotation={[0.5, 0, 0]} radius={1} rotationSpeed={0.003} />
            <WireGear position={[-2, -3, -2]} rotation={[-0.3, 0.2, 0]} radius={0.7} rotationSpeed={-0.004} />

            {/* Technical grid */}
            <TechGrid />

            {/* Floating particles */}
            <Particles />
        </group>
    );
}

export default function GearboxBackground() {
    return (
        <div style={{
            position: 'absolute',
            inset: 0,
            zIndex: 0,
            pointerEvents: 'none',
        }}>
            <Canvas
                camera={{ position: [0, 0, 8], fov: 50 }}
                gl={{ antialias: true, alpha: true }}
                style={{ background: 'transparent' }}
            >
                <ambientLight intensity={0.3} />
                <directionalLight position={[5, 5, 5]} intensity={0.5} color="#60a5fa" />
                <directionalLight position={[-5, -5, 5]} intensity={0.3} color="#3b82f6" />
                <Scene />
            </Canvas>

            {/* Gradient overlays for depth */}
            <div style={{
                position: 'absolute',
                inset: 0,
                background: 'radial-gradient(ellipse at 30% 20%, rgba(59, 130, 246, 0.08) 0%, transparent 50%)',
                pointerEvents: 'none',
            }} />
            <div style={{
                position: 'absolute',
                inset: 0,
                background: 'radial-gradient(ellipse at 70% 80%, rgba(37, 99, 235, 0.06) 0%, transparent 50%)',
                pointerEvents: 'none',
            }} />
        </div>
    );
}
