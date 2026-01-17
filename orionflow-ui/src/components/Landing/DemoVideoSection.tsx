import { Play } from 'lucide-react';

export default function DemoVideoSection() {
    return (
        <section style={{
            padding: '80px 48px',
            position: 'relative',
        }}>
            <div style={{
                maxWidth: '1000px',
                margin: '0 auto',
            }}>
                {/* Section header */}
                <div style={{ textAlign: 'center', marginBottom: '40px' }}>
                    <h2 style={{
                        fontSize: '36px',
                        fontWeight: 700,
                        letterSpacing: '-0.02em',
                        marginBottom: '12px',
                    }}>
                        See It In Action
                    </h2>
                    <p style={{
                        fontSize: '16px',
                        color: '#94a3b8',
                    }}>
                        Watch how OrionFlow transforms text prompts into parametric CAD models.
                    </p>
                </div>

                {/* Video placeholder */}
                <div style={{
                    position: 'relative',
                    aspectRatio: '16/9',
                    background: 'linear-gradient(145deg, rgba(15, 23, 42, 0.9) 0%, rgba(3, 7, 18, 0.95) 100%)',
                    border: '1px solid rgba(255, 255, 255, 0.08)',
                    borderRadius: '20px',
                    overflow: 'hidden',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    cursor: 'pointer',
                    transition: 'all 0.3s ease',
                }}
                    onMouseEnter={(e) => {
                        e.currentTarget.style.borderColor = 'rgba(59, 130, 246, 0.3)';
                        e.currentTarget.style.boxShadow = '0 24px 60px rgba(0, 0, 0, 0.4)';
                    }}
                    onMouseLeave={(e) => {
                        e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.08)';
                        e.currentTarget.style.boxShadow = 'none';
                    }}
                >
                    {/* Grid background */}
                    <div style={{
                        position: 'absolute',
                        inset: 0,
                        background: `
              linear-gradient(rgba(59, 130, 246, 0.03) 1px, transparent 1px),
              linear-gradient(90deg, rgba(59, 130, 246, 0.03) 1px, transparent 1px)
            `,
                        backgroundSize: '60px 60px',
                    }} />

                    {/* Play button */}
                    <div style={{
                        position: 'relative',
                        width: '80px',
                        height: '80px',
                        borderRadius: '50%',
                        background: 'linear-gradient(135deg, #2563eb 0%, #3b82f6 100%)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        boxShadow: '0 12px 40px rgba(59, 130, 246, 0.4)',
                        transition: 'all 0.3s ease',
                    }}>
                        <Play size={32} color="white" fill="white" style={{ marginLeft: '4px' }} />
                    </div>

                    {/* Coming soon label */}
                    <div style={{
                        position: 'absolute',
                        bottom: '24px',
                        left: '50%',
                        transform: 'translateX(-50%)',
                        background: 'rgba(15, 23, 42, 0.9)',
                        border: '1px solid rgba(255, 255, 255, 0.1)',
                        borderRadius: '100px',
                        padding: '8px 20px',
                    }}>
                        <span style={{ color: '#94a3b8', fontSize: '13px' }}>Demo video coming soon</span>
                    </div>
                </div>
            </div>
        </section>
    );
}
