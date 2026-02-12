import { Link } from 'react-router-dom';
import { ArrowRight, Play, Cpu, Zap, Box } from 'lucide-react';
import GearboxBackground from './GearboxBackground';

export default function HeroSection() {
    return (
        <section style={{
            minHeight: '100vh',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '140px 48px 100px',
            position: 'relative',
            overflow: 'hidden',
        }}>
            {/* 3D Gearbox Background */}
            <GearboxBackground />

            {/* Gradient overlays */}
            <div style={{
                position: 'absolute',
                inset: 0,
                background: 'radial-gradient(ellipse 80% 50% at 50% -20%, rgba(59, 130, 246, 0.15) 0%, transparent 50%)',
                pointerEvents: 'none',
            }} />
            <div style={{
                position: 'absolute',
                bottom: 0,
                left: 0,
                right: 0,
                height: '300px',
                background: 'linear-gradient(to top, #030712 0%, transparent 100%)',
                pointerEvents: 'none',
                zIndex: 1,
            }} />

            {/* Main content */}
            <div style={{
                maxWidth: '1280px',
                width: '100%',
                position: 'relative',
                zIndex: 2,
            }}>
                <div style={{
                    maxWidth: '800px',
                    margin: '0 auto',
                    textAlign: 'center',
                }}>
                    {/* Badge */}
                    <div style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '8px',
                        background: 'rgba(59, 130, 246, 0.1)',
                        backdropFilter: 'blur(10px)',
                        padding: '8px 16px',
                        borderRadius: '100px',
                        marginBottom: '32px',
                        border: '1px solid rgba(59, 130, 246, 0.2)',
                    }}>
                        <div style={{
                            width: '6px',
                            height: '6px',
                            borderRadius: '50%',
                            background: '#22c55e',
                            animation: 'pulse 2s ease-in-out infinite',
                        }} />
                        <span style={{ color: '#93c5fd', fontSize: '13px', fontWeight: 500 }}>
                            Now in Public Beta
                        </span>
                    </div>

                    {/* Main headline */}
                    <h1 style={{
                        fontSize: '72px',
                        fontWeight: 800,
                        lineHeight: 1.05,
                        letterSpacing: '-0.03em',
                        marginBottom: '24px',
                    }}>
                        <span style={{ color: '#f8fafc' }}>Text to </span>
                        <span style={{
                            background: 'linear-gradient(135deg, #3b82f6 0%, #60a5fa 50%, #93c5fd 100%)',
                            WebkitBackgroundClip: 'text',
                            WebkitTextFillColor: 'transparent',
                            backgroundClip: 'text',
                        }}>Parametric CAD</span>
                    </h1>

                    {/* Subheadline */}
                    <p style={{
                        fontSize: '22px',
                        color: '#94a3b8',
                        lineHeight: 1.6,
                        marginBottom: '20px',
                        maxWidth: '600px',
                        margin: '0 auto 20px',
                    }}>
                        Transform natural language into production-ready B-REP geometry. Design mechanical parts with AI that understands engineering.
                    </p>

                    {/* Feature highlights */}
                    <div style={{
                        display: 'flex',
                        justifyContent: 'center',
                        gap: '24px',
                        marginBottom: '48px',
                        flexWrap: 'wrap',
                    }}>
                        {[
                            { icon: Cpu, text: 'Real Geometry Kernel' },
                            { icon: Zap, text: 'Instant STEP Export' },
                            { icon: Box, text: 'Parametric History' },
                        ].map((item, i) => (
                            <div key={i} style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '8px',
                                color: '#64748b',
                                fontSize: '14px',
                            }}>
                                <item.icon size={16} color="#3b82f6" />
                                <span>{item.text}</span>
                            </div>
                        ))}
                    </div>

                    {/* CTAs */}
                    <div style={{
                        display: 'flex',
                        gap: '16px',
                        alignItems: 'center',
                        justifyContent: 'center',
                        marginBottom: '64px',
                    }}>
                        <Link to="/auth" style={{ textDecoration: 'none' }}>
                            <button style={{
                                background: 'linear-gradient(135deg, #2563eb 0%, #3b82f6 100%)',
                                color: 'white',
                                padding: '18px 36px',
                                borderRadius: '14px',
                                fontWeight: 600,
                                fontSize: '17px',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '10px',
                                border: 'none',
                                cursor: 'pointer',
                                boxShadow: '0 8px 32px rgba(59, 130, 246, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.1)',
                                transition: 'all 0.25s cubic-bezier(0.16, 1, 0.3, 1)',
                            }}
                                onMouseEnter={(e) => {
                                    e.currentTarget.style.transform = 'translateY(-3px)';
                                    e.currentTarget.style.boxShadow = '0 12px 40px rgba(59, 130, 246, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.1)';
                                }}
                                onMouseLeave={(e) => {
                                    e.currentTarget.style.transform = 'translateY(0)';
                                    e.currentTarget.style.boxShadow = '0 8px 32px rgba(59, 130, 246, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.1)';
                                }}
                            >
                                Start Building Free
                                <ArrowRight size={18} />
                            </button>
                        </Link>

                        <button style={{
                            background: 'rgba(15, 23, 42, 0.8)',
                            backdropFilter: 'blur(10px)',
                            color: '#cbd5e1',
                            padding: '18px 28px',
                            borderRadius: '14px',
                            fontWeight: 500,
                            fontSize: '16px',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '10px',
                            border: '1px solid rgba(255, 255, 255, 0.1)',
                            cursor: 'pointer',
                            transition: 'all 0.2s ease',
                        }}
                            onMouseEnter={(e) => {
                                e.currentTarget.style.background = 'rgba(30, 41, 59, 0.9)';
                                e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.15)';
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.background = 'rgba(15, 23, 42, 0.8)';
                                e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.1)';
                            }}
                        >
                            <Play size={16} />
                            Watch Demo
                        </button>
                    </div>

                    {/* Product Preview */}
                    <div style={{
                        position: 'relative',
                        borderRadius: '20px',
                        overflow: 'hidden',
                        background: 'linear-gradient(145deg, rgba(15, 23, 42, 0.95) 0%, rgba(3, 7, 18, 0.98) 100%)',
                        border: '1px solid rgba(255, 255, 255, 0.08)',
                        boxShadow: '0 32px 80px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(255, 255, 255, 0.05) inset',
                    }}>
                        {/* Browser chrome */}
                        <div style={{
                            padding: '12px 16px',
                            borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '8px',
                            background: 'rgba(15, 23, 42, 0.5)',
                        }}>
                            <div style={{ display: 'flex', gap: '6px' }}>
                                <div style={{ width: '12px', height: '12px', borderRadius: '50%', background: '#ef4444' }} />
                                <div style={{ width: '12px', height: '12px', borderRadius: '50%', background: '#f59e0b' }} />
                                <div style={{ width: '12px', height: '12px', borderRadius: '50%', background: '#22c55e' }} />
                            </div>
                            <div style={{
                                flex: 1,
                                display: 'flex',
                                justifyContent: 'center',
                            }}>
                                <div style={{
                                    background: 'rgba(3, 7, 18, 0.6)',
                                    padding: '6px 16px',
                                    borderRadius: '6px',
                                    fontSize: '12px',
                                    color: '#64748b',
                                    fontFamily: 'var(--font-mono)',
                                }}>
                                    orionflow.app
                                </div>
                            </div>
                        </div>

                        {/* Main interface mock */}
                        <div style={{
                            display: 'grid',
                            gridTemplateColumns: '200px 1fr 280px',
                            minHeight: '400px',
                        }}>
                            {/* Left sidebar - Feature tree */}
                            <div style={{
                                borderRight: '1px solid rgba(255, 255, 255, 0.06)',
                                padding: '16px',
                                background: 'rgba(15, 23, 42, 0.3)',
                            }}>
                                <div style={{
                                    color: '#64748b',
                                    fontSize: '10px',
                                    fontWeight: 600,
                                    textTransform: 'uppercase',
                                    letterSpacing: '0.1em',
                                    marginBottom: '12px',
                                }}>
                                    Feature Tree
                                </div>
                                {[
                                    { name: 'Base_Sketch', active: false },
                                    { name: 'Extrude_Body', active: false },
                                    { name: 'Bore_Cut', active: true },
                                    { name: 'Fillet_R2', active: false },
                                    { name: 'Pattern_x6', active: false },
                                ].map((item, i) => (
                                    <div key={i} style={{
                                        padding: '8px 10px',
                                        fontSize: '12px',
                                        color: item.active ? '#60a5fa' : '#94a3b8',
                                        background: item.active ? 'rgba(59, 130, 246, 0.15)' : 'transparent',
                                        borderRadius: '6px',
                                        fontFamily: 'var(--font-mono)',
                                        marginBottom: '4px',
                                        borderLeft: `2px solid ${item.active ? '#3b82f6' : 'transparent'}`,
                                        transition: 'all 0.2s ease',
                                    }}>
                                        {item.name}
                                    </div>
                                ))}
                            </div>

                            {/* Center - 3D viewport */}
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
                                    width: '180px',
                                    height: '140px',
                                    background: 'linear-gradient(145deg, #1e293b 0%, #0f172a 100%)',
                                    borderRadius: '16px',
                                    border: '1px solid rgba(59, 130, 246, 0.3)',
                                    boxShadow: '0 20px 50px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.05)',
                                    transform: 'perspective(600px) rotateX(15deg) rotateY(-20deg)',
                                    position: 'relative',
                                }}>
                                    {/* Hole detail */}
                                    <div style={{
                                        position: 'absolute',
                                        top: '50%',
                                        left: '50%',
                                        transform: 'translate(-50%, -50%)',
                                        width: '30px',
                                        height: '30px',
                                        borderRadius: '50%',
                                        background: 'radial-gradient(circle, #030712 0%, #0f172a 100%)',
                                        border: '2px solid rgba(59, 130, 246, 0.4)',
                                        boxShadow: 'inset 0 2px 8px rgba(0, 0, 0, 0.5)',
                                    }} />
                                </div>

                                {/* Dimension annotation */}
                                <div style={{
                                    position: 'absolute',
                                    top: '30%',
                                    right: '20%',
                                    background: 'rgba(59, 130, 246, 0.9)',
                                    padding: '4px 8px',
                                    borderRadius: '4px',
                                    fontSize: '11px',
                                    fontFamily: 'var(--font-mono)',
                                    color: 'white',
                                    fontWeight: 600,
                                }}>
                                    12mm
                                </div>

                                {/* View cube */}
                                <div style={{
                                    position: 'absolute',
                                    bottom: '16px',
                                    right: '16px',
                                    width: '48px',
                                    height: '48px',
                                    background: 'rgba(15, 23, 42, 0.9)',
                                    border: '1px solid rgba(255, 255, 255, 0.1)',
                                    borderRadius: '8px',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    fontSize: '10px',
                                    color: '#64748b',
                                    fontFamily: 'var(--font-mono)',
                                }}>
                                    ISO
                                </div>
                            </div>

                            {/* Right sidebar - Chat */}
                            <div style={{
                                borderLeft: '1px solid rgba(255, 255, 255, 0.06)',
                                padding: '16px',
                                background: 'rgba(15, 23, 42, 0.3)',
                                display: 'flex',
                                flexDirection: 'column',
                            }}>
                                <div style={{
                                    color: '#64748b',
                                    fontSize: '10px',
                                    fontWeight: 600,
                                    textTransform: 'uppercase',
                                    letterSpacing: '0.1em',
                                    marginBottom: '12px',
                                }}>
                                    AI Chat
                                </div>

                                {/* Chat messages */}
                                <div style={{ flex: 1 }}>
                                    <div style={{
                                        background: 'rgba(59, 130, 246, 0.1)',
                                        border: '1px solid rgba(59, 130, 246, 0.2)',
                                        borderRadius: '10px',
                                        padding: '10px 12px',
                                        marginBottom: '12px',
                                    }}>
                                        <div style={{ color: '#60a5fa', fontSize: '10px', fontWeight: 600, marginBottom: '4px' }}>You</div>
                                        <div style={{ color: '#e2e8f0', fontSize: '12px', lineHeight: 1.4 }}>
                                            Make the bore 12mm and add 6 mounting holes
                                        </div>
                                    </div>

                                    <div style={{
                                        background: 'rgba(3, 7, 18, 0.5)',
                                        border: '1px solid rgba(255, 255, 255, 0.06)',
                                        borderRadius: '10px',
                                        padding: '10px 12px',
                                    }}>
                                        <div style={{
                                            color: '#22c55e',
                                            fontSize: '10px',
                                            fontWeight: 600,
                                            marginBottom: '6px',
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '4px',
                                        }}>
                                            <div style={{
                                                width: '5px',
                                                height: '5px',
                                                borderRadius: '50%',
                                                background: '#22c55e',
                                            }} />
                                            OrionFlow
                                        </div>
                                        <div style={{ color: '#94a3b8', fontSize: '11px', lineHeight: 1.4, fontFamily: 'var(--font-mono)' }}>
                                            Updated bore_dia to 12mm
                                        </div>
                                        <div style={{ color: '#94a3b8', fontSize: '11px', lineHeight: 1.4, fontFamily: 'var(--font-mono)' }}>
                                            Added Pattern_Circular...
                                        </div>
                                    </div>
                                </div>

                                {/* Input */}
                                <div style={{
                                    marginTop: '12px',
                                    background: 'rgba(3, 7, 18, 0.6)',
                                    border: '1px solid rgba(255, 255, 255, 0.08)',
                                    borderRadius: '8px',
                                    padding: '10px 12px',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '8px',
                                }}>
                                    <span style={{ color: '#64748b', fontSize: '12px' }}>Describe changes...</span>
                                    <ArrowRight size={14} color="#64748b" style={{ marginLeft: 'auto' }} />
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </section>
    );
}
