import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import OrionFlowLogo from '../OrionFlowLogo';

export default function FooterCTASection() {
    return (
        <section style={{
            padding: '120px 48px',
            position: 'relative',
            overflow: 'hidden',
        }}>
            {/* Background effects */}
            <div style={{
                position: 'absolute',
                inset: 0,
                background: 'radial-gradient(ellipse 80% 50% at 50% 100%, rgba(59, 130, 246, 0.1) 0%, transparent 60%)',
                pointerEvents: 'none',
            }} />

            <div style={{
                maxWidth: '900px',
                margin: '0 auto',
                textAlign: 'center',
                position: 'relative',
                zIndex: 1,
            }}>
                {/* Logo */}
                <div style={{
                    display: 'flex',
                    justifyContent: 'center',
                    marginBottom: '32px',
                }}>
                    <div style={{
                        width: '80px',
                        height: '80px',
                        borderRadius: '24px',
                        background: 'linear-gradient(145deg, rgba(59, 130, 246, 0.2) 0%, rgba(59, 130, 246, 0.05) 100%)',
                        border: '1px solid rgba(59, 130, 246, 0.2)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        boxShadow: '0 20px 40px rgba(59, 130, 246, 0.15)',
                    }}>
                        <OrionFlowLogo size={48} />
                    </div>
                </div>

                {/* Headline */}
                <h2 style={{
                    fontSize: '52px',
                    fontWeight: 800,
                    letterSpacing: '-0.03em',
                    marginBottom: '20px',
                    lineHeight: 1.1,
                }}>
                    <span style={{ color: '#f8fafc' }}>Ready to build </span>
                    <span style={{
                        background: 'linear-gradient(135deg, #3b82f6 0%, #60a5fa 100%)',
                        WebkitBackgroundClip: 'text',
                        WebkitTextFillColor: 'transparent',
                        backgroundClip: 'text',
                    }}>real parts</span>
                    <span style={{ color: '#f8fafc' }}>?</span>
                </h2>

                <p style={{
                    fontSize: '18px',
                    color: '#94a3b8',
                    marginBottom: '40px',
                    maxWidth: '550px',
                    margin: '0 auto 40px',
                    lineHeight: 1.6,
                }}>
                    Join thousands of engineers using OrionFlow to transform ideas into production-ready CAD models. Start designing for free.
                </p>

                {/* CTAs */}
                <div style={{
                    display: 'flex',
                    gap: '16px',
                    justifyContent: 'center',
                    alignItems: 'center',
                }}>
                    <Link to="/auth" style={{ textDecoration: 'none' }}>
                        <button style={{
                            background: 'linear-gradient(135deg, #2563eb 0%, #3b82f6 100%)',
                            color: 'white',
                            padding: '18px 40px',
                            borderRadius: '14px',
                            fontWeight: 600,
                            fontSize: '17px',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '12px',
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
                            <ArrowRight size={20} />
                        </button>
                    </Link>

                    <Link to="/about" style={{ textDecoration: 'none' }}>
                        <button style={{
                            background: 'rgba(15, 23, 42, 0.8)',
                            color: '#cbd5e1',
                            padding: '18px 28px',
                            borderRadius: '14px',
                            fontWeight: 500,
                            fontSize: '16px',
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
                            Learn More
                        </button>
                    </Link>
                </div>

                {/* Trust indicators */}
                <div style={{
                    marginTop: '48px',
                    display: 'flex',
                    justifyContent: 'center',
                    gap: '32px',
                    flexWrap: 'wrap',
                }}>
                    {[
                        'No credit card required',
                        'Free tier available',
                        'STEP export included',
                    ].map((item, i) => (
                        <div key={i} style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '8px',
                            color: '#64748b',
                            fontSize: '14px',
                        }}>
                            <div style={{
                                width: '6px',
                                height: '6px',
                                borderRadius: '50%',
                                background: '#22c55e',
                            }} />
                            {item}
                        </div>
                    ))}
                </div>
            </div>
        </section>
    );
}
