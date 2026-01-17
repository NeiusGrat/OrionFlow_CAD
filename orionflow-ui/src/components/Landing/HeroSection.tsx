import { Link } from 'react-router-dom';
import { ArrowRight, Play } from 'lucide-react';

export default function HeroSection() {
    return (
        <section style={{
            minHeight: '100vh',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '120px 48px 80px',
            position: 'relative',
            overflow: 'hidden',
        }}>
            {/* Background orbs */}
            <div style={{
                position: 'absolute',
                width: '600px',
                height: '600px',
                borderRadius: '50%',
                background: 'radial-gradient(circle, rgba(59, 130, 246, 0.12) 0%, transparent 70%)',
                filter: 'blur(80px)',
                top: '-200px',
                right: '-100px',
                pointerEvents: 'none',
            }} />
            <div style={{
                position: 'absolute',
                width: '500px',
                height: '500px',
                borderRadius: '50%',
                background: 'radial-gradient(circle, rgba(99, 102, 241, 0.1) 0%, transparent 70%)',
                filter: 'blur(80px)',
                bottom: '-150px',
                left: '-100px',
                pointerEvents: 'none',
            }} />

            <div style={{
                maxWidth: '1280px',
                width: '100%',
                display: 'grid',
                gridTemplateColumns: '1fr 1fr',
                gap: '80px',
                alignItems: 'center',
                position: 'relative',
                zIndex: 1,
            }}>
                {/* Left Column - Text */}
                <div>
                    <h1 style={{
                        fontSize: '56px',
                        fontWeight: 700,
                        lineHeight: 1.1,
                        letterSpacing: '-0.03em',
                        marginBottom: '24px',
                    }}>
                        <span style={{ color: '#f8fafc' }}>Agentic CAD for </span>
                        <span style={{
                            background: 'linear-gradient(135deg, #60a5fa 0%, #3b82f6 50%, #2563eb 100%)',
                            WebkitBackgroundClip: 'text',
                            WebkitTextFillColor: 'transparent',
                            backgroundClip: 'text',
                        }}>Real Engineering</span>
                    </h1>

                    <p style={{
                        fontSize: '20px',
                        color: '#94a3b8',
                        lineHeight: 1.6,
                        marginBottom: '16px',
                        maxWidth: '520px',
                    }}>
                        Turn text prompts into parametric B-REP models — directly in your browser.
                    </p>

                    <p style={{
                        fontSize: '16px',
                        color: '#64748b',
                        lineHeight: 1.6,
                        marginBottom: '40px',
                        maxWidth: '480px',
                    }}>
                        OrionFlow is an AI CAD co-pilot for mechanical engineers. Design parts, edit features, and export STEP files with precision.
                    </p>

                    {/* CTAs */}
                    <div style={{ display: 'flex', gap: '16px', alignItems: 'center' }}>
                        <Link to="/auth" style={{ textDecoration: 'none' }}>
                            <button style={{
                                background: 'linear-gradient(135deg, #2563eb 0%, #3b82f6 100%)',
                                color: 'white',
                                padding: '16px 32px',
                                borderRadius: '12px',
                                fontWeight: 600,
                                fontSize: '16px',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '10px',
                                border: 'none',
                                cursor: 'pointer',
                                boxShadow: '0 4px 24px rgba(59, 130, 246, 0.4)',
                                transition: 'all 0.25s cubic-bezier(0.16, 1, 0.3, 1)',
                            }}
                                onMouseEnter={(e) => {
                                    e.currentTarget.style.transform = 'translateY(-3px)';
                                    e.currentTarget.style.boxShadow = '0 8px 32px rgba(59, 130, 246, 0.5)';
                                }}
                                onMouseLeave={(e) => {
                                    e.currentTarget.style.transform = 'translateY(0)';
                                    e.currentTarget.style.boxShadow = '0 4px 24px rgba(59, 130, 246, 0.4)';
                                }}
                            >
                                Start Designing Free
                                <ArrowRight size={18} />
                            </button>
                        </Link>

                        <button style={{
                            background: 'rgba(30, 41, 59, 0.8)',
                            color: '#cbd5e1',
                            padding: '16px 24px',
                            borderRadius: '12px',
                            fontWeight: 500,
                            fontSize: '15px',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '10px',
                            border: '1px solid rgba(255, 255, 255, 0.08)',
                            cursor: 'pointer',
                            transition: 'all 0.2s ease',
                        }}
                            onMouseEnter={(e) => {
                                e.currentTarget.style.background = 'rgba(51, 65, 85, 0.8)';
                                e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.12)';
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.background = 'rgba(30, 41, 59, 0.8)';
                                e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.08)';
                            }}
                        >
                            <Play size={16} />
                            Watch Demo
                        </button>
                    </div>
                </div>

                {/* Right Column - CAD Viewport Mock */}
                <div style={{
                    background: 'linear-gradient(145deg, rgba(15, 23, 42, 0.9) 0%, rgba(3, 7, 18, 0.95) 100%)',
                    border: '1px solid rgba(255, 255, 255, 0.08)',
                    borderRadius: '20px',
                    overflow: 'hidden',
                    boxShadow: '0 24px 80px rgba(0, 0, 0, 0.6)',
                }}>
                    {/* Viewport header */}
                    <div style={{
                        padding: '12px 16px',
                        borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                    }}>
                        <div style={{ width: '12px', height: '12px', borderRadius: '50%', background: '#ef4444' }} />
                        <div style={{ width: '12px', height: '12px', borderRadius: '50%', background: '#f59e0b' }} />
                        <div style={{ width: '12px', height: '12px', borderRadius: '50%', background: '#22c55e' }} />
                        <span style={{ marginLeft: '12px', color: '#64748b', fontSize: '13px', fontFamily: 'var(--font-mono)' }}>
                            motor_mount_v4.step
                        </span>
                    </div>

                    {/* Main viewport area */}
                    <div style={{
                        display: 'grid',
                        gridTemplateColumns: '180px 1fr',
                        minHeight: '360px',
                    }}>
                        {/* Feature tree */}
                        <div style={{
                            borderRight: '1px solid rgba(255, 255, 255, 0.06)',
                            padding: '16px',
                            background: 'rgba(15, 23, 42, 0.5)',
                        }}>
                            <div style={{ color: '#64748b', fontSize: '11px', fontWeight: 600, marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                                Feature Tree
                            </div>
                            {['OP-01 Sketch_XY', 'OP-02 Extrude_Boss', 'OP-03 Boolean_Cut', 'OP-04 Fillet_Edges', 'OP-05 Pattern_Circ'].map((op, i) => (
                                <div key={i} style={{
                                    padding: '8px 10px',
                                    fontSize: '12px',
                                    color: i === 2 ? '#60a5fa' : '#94a3b8',
                                    background: i === 2 ? 'rgba(59, 130, 246, 0.15)' : 'transparent',
                                    borderRadius: '6px',
                                    fontFamily: 'var(--font-mono)',
                                    marginBottom: '4px',
                                    borderLeft: i === 2 ? '2px solid #3b82f6' : '2px solid transparent',
                                }}>
                                    {op}
                                </div>
                            ))}
                        </div>

                        {/* 3D viewport placeholder */}
                        <div style={{
                            position: 'relative',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            background: `
                linear-gradient(rgba(59, 130, 246, 0.02) 1px, transparent 1px),
                linear-gradient(90deg, rgba(59, 130, 246, 0.02) 1px, transparent 1px)
              `,
                            backgroundSize: '40px 40px',
                        }}>
                            {/* CAD model representation */}
                            <div style={{
                                width: '160px',
                                height: '120px',
                                background: 'linear-gradient(145deg, #1e293b 0%, #0f172a 100%)',
                                borderRadius: '12px',
                                border: '1px solid rgba(59, 130, 246, 0.3)',
                                boxShadow: '0 20px 40px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.05)',
                                transform: 'perspective(500px) rotateX(10deg) rotateY(-15deg)',
                            }} />

                            {/* Chat bubble overlay */}
                            <div style={{
                                position: 'absolute',
                                bottom: '24px',
                                right: '24px',
                                background: 'rgba(15, 23, 42, 0.95)',
                                border: '1px solid rgba(59, 130, 246, 0.3)',
                                borderRadius: '12px',
                                padding: '12px 16px',
                                maxWidth: '240px',
                                boxShadow: '0 8px 24px rgba(0, 0, 0, 0.4)',
                            }}>
                                <div style={{ color: '#60a5fa', fontSize: '11px', fontWeight: 600, marginBottom: '6px' }}>
                                    AI Director
                                </div>
                                <div style={{ color: '#e2e8f0', fontSize: '13px', lineHeight: 1.4 }}>
                                    "Increase bore diameter to 12mm and add circular pattern."
                                </div>
                                <div style={{
                                    marginTop: '8px',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '6px',
                                    color: '#64748b',
                                    fontSize: '11px',
                                }}>
                                    <div style={{
                                        width: '6px',
                                        height: '6px',
                                        borderRadius: '50%',
                                        background: '#22c55e',
                                        animation: 'pulse 2s ease-in-out infinite',
                                    }} />
                                    Thinking...
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </section>
    );
}
