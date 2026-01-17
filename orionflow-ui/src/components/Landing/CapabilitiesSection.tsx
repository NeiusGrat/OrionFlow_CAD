import { Cpu, Sliders, FileOutput, GitBranch } from 'lucide-react';

const capabilities = [
    {
        icon: Cpu,
        title: 'Zero Setup',
        description: 'Runs entirely in your browser. No installs. No plugins. Full geometry kernel.',
    },
    {
        icon: Sliders,
        title: 'Parametric — Live Tweak',
        description: 'Modify dimensions with real-time constraint solving.',
        chips: ['Bore Dia → 12mm', 'Flange → 5.5mm', 'Teeth → 24'],
    },
    {
        icon: FileOutput,
        title: 'Industry Standard Export',
        description: 'Native support for real CAD formats.',
        formats: ['.STEP', '.IGES', '.STL', '.GLB'],
    },
    {
        icon: GitBranch,
        title: 'History-Based Modeling',
        description: 'Non-destructive feature tree editing.',
        features: ['OP-01 Sketch_Plane_XY', 'OP-02 Extrude_Boss', 'OP-03 Boolean_Cut', 'OP-04 Fillet_Edge_Loop', 'OP-05 Pattern_Circular'],
    },
];

export default function CapabilitiesSection() {
    return (
        <section style={{
            padding: '120px 48px',
            position: 'relative',
        }}>
            <div style={{ maxWidth: '1280px', margin: '0 auto' }}>
                {/* Section header */}
                <div style={{ textAlign: 'center', marginBottom: '64px' }}>
                    <h2 style={{
                        fontSize: '40px',
                        fontWeight: 700,
                        letterSpacing: '-0.02em',
                        marginBottom: '16px',
                    }}>
                        Core Capabilities
                    </h2>
                    <p style={{
                        fontSize: '18px',
                        color: '#94a3b8',
                        maxWidth: '600px',
                        margin: '0 auto',
                    }}>
                        Everything you need to design precision mechanical parts.
                    </p>
                </div>

                {/* Cards grid */}
                <div style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(2, 1fr)',
                    gap: '24px',
                }}>
                    {capabilities.map((cap, index) => (
                        <div
                            key={index}
                            style={{
                                background: 'linear-gradient(145deg, rgba(15, 23, 42, 0.8) 0%, rgba(3, 7, 18, 0.9) 100%)',
                                border: '1px solid rgba(255, 255, 255, 0.06)',
                                borderRadius: '20px',
                                padding: '32px',
                                transition: 'all 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
                                cursor: 'default',
                            }}
                            onMouseEnter={(e) => {
                                e.currentTarget.style.borderColor = 'rgba(59, 130, 246, 0.3)';
                                e.currentTarget.style.transform = 'translateY(-4px)';
                                e.currentTarget.style.boxShadow = '0 16px 48px rgba(0, 0, 0, 0.4)';
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.06)';
                                e.currentTarget.style.transform = 'translateY(0)';
                                e.currentTarget.style.boxShadow = 'none';
                            }}
                        >
                            {/* Icon */}
                            <div style={{
                                width: '48px',
                                height: '48px',
                                borderRadius: '12px',
                                background: 'rgba(59, 130, 246, 0.15)',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                marginBottom: '20px',
                            }}>
                                <cap.icon size={24} color="#60a5fa" />
                            </div>

                            {/* Title */}
                            <h3 style={{
                                fontSize: '20px',
                                fontWeight: 600,
                                marginBottom: '12px',
                                color: '#f1f5f9',
                            }}>
                                {cap.title}
                            </h3>

                            {/* Description */}
                            <p style={{
                                fontSize: '15px',
                                color: '#94a3b8',
                                lineHeight: 1.6,
                                marginBottom: cap.chips || cap.formats || cap.features ? '20px' : '0',
                            }}>
                                {cap.description}
                            </p>

                            {/* Parameter chips */}
                            {cap.chips && (
                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                                    {cap.chips.map((chip, i) => (
                                        <span key={i} style={{
                                            background: 'rgba(59, 130, 246, 0.12)',
                                            color: '#93c5fd',
                                            padding: '6px 12px',
                                            borderRadius: '8px',
                                            fontSize: '12px',
                                            fontFamily: 'var(--font-mono)',
                                            border: '1px solid rgba(59, 130, 246, 0.2)',
                                        }}>
                                            {chip}
                                        </span>
                                    ))}
                                </div>
                            )}

                            {/* Format buttons */}
                            {cap.formats && (
                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                                    {cap.formats.map((fmt, i) => (
                                        <span key={i} style={{
                                            background: 'rgba(30, 41, 59, 0.8)',
                                            color: '#cbd5e1',
                                            padding: '8px 14px',
                                            borderRadius: '8px',
                                            fontSize: '13px',
                                            fontWeight: 600,
                                            fontFamily: 'var(--font-mono)',
                                            border: '1px solid rgba(255, 255, 255, 0.08)',
                                        }}>
                                            {fmt}
                                        </span>
                                    ))}
                                </div>
                            )}

                            {/* Feature list */}
                            {cap.features && (
                                <div style={{
                                    background: 'rgba(3, 7, 18, 0.6)',
                                    borderRadius: '10px',
                                    padding: '12px',
                                    border: '1px solid rgba(255, 255, 255, 0.04)',
                                }}>
                                    {cap.features.map((feat, i) => (
                                        <div key={i} style={{
                                            padding: '6px 8px',
                                            fontSize: '12px',
                                            color: '#94a3b8',
                                            fontFamily: 'var(--font-mono)',
                                            borderLeft: '2px solid',
                                            borderLeftColor: i === 2 ? '#3b82f6' : 'rgba(255, 255, 255, 0.1)',
                                            marginBottom: i < cap.features!.length - 1 ? '4px' : '0',
                                            background: i === 2 ? 'rgba(59, 130, 246, 0.08)' : 'transparent',
                                            borderRadius: '4px',
                                        }}>
                                            {feat}
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            </div>
        </section>
    );
}
