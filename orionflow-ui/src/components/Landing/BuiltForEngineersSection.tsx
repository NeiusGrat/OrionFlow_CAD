import { Cog, Box, Layers, Sparkles } from 'lucide-react';

const useCases = [
    {
        icon: Cog,
        title: 'Mechanical Parts',
        description: 'Design precision mechanical components with proper tolerancing and constraints.',
    },
    {
        icon: Box,
        title: 'Rapid Prototyping & 3D Printing',
        description: 'Generate print-ready STL files with parametric control over every dimension.',
    },
    {
        icon: Layers,
        title: 'Assemblies',
        description: 'Multi-part assemblies with constraint relationships.',
        badge: 'Coming Soon',
    },
    {
        icon: Sparkles,
        title: 'Live Simulation',
        description: 'Real-time stress analysis and motion simulation.',
        badge: 'Coming Soon',
    },
];

export default function BuiltForEngineersSection() {
    return (
        <section style={{
            padding: '120px 48px',
            position: 'relative',
        }}>
            <div style={{ maxWidth: '1280px', margin: '0 auto' }}>
                {/* Section header */}
                <div style={{ textAlign: 'center', marginBottom: '64px' }}>
                    <h2 style={{
                        fontSize: '44px',
                        fontWeight: 700,
                        letterSpacing: '-0.02em',
                        marginBottom: '16px',
                    }}>
                        Built for engineers who care about{' '}
                        <span style={{
                            background: 'linear-gradient(135deg, #60a5fa 0%, #3b82f6 100%)',
                            WebkitBackgroundClip: 'text',
                            WebkitTextFillColor: 'transparent',
                            backgroundClip: 'text',
                        }}>precision</span>.
                    </h2>
                    <p style={{
                        fontSize: '18px',
                        color: '#94a3b8',
                        maxWidth: '600px',
                        margin: '0 auto',
                    }}>
                        From concept to production-ready CAD, OrionFlow supports the full engineering workflow.
                    </p>
                </div>

                {/* Use cases grid */}
                <div style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(4, 1fr)',
                    gap: '20px',
                }}>
                    {useCases.map((item, index) => (
                        <div
                            key={index}
                            style={{
                                background: 'rgba(15, 23, 42, 0.6)',
                                border: '1px solid rgba(255, 255, 255, 0.06)',
                                borderRadius: '16px',
                                padding: '28px 24px',
                                textAlign: 'center',
                                transition: 'all 0.3s ease',
                                position: 'relative',
                            }}
                            onMouseEnter={(e) => {
                                e.currentTarget.style.borderColor = 'rgba(59, 130, 246, 0.2)';
                                e.currentTarget.style.background = 'rgba(15, 23, 42, 0.8)';
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.06)';
                                e.currentTarget.style.background = 'rgba(15, 23, 42, 0.6)';
                            }}
                        >
                            {/* Badge */}
                            {item.badge && (
                                <span style={{
                                    position: 'absolute',
                                    top: '12px',
                                    right: '12px',
                                    background: 'rgba(99, 102, 241, 0.15)',
                                    color: '#a5b4fc',
                                    padding: '4px 10px',
                                    borderRadius: '100px',
                                    fontSize: '10px',
                                    fontWeight: 600,
                                    textTransform: 'uppercase',
                                    letterSpacing: '0.05em',
                                }}>
                                    {item.badge}
                                </span>
                            )}

                            {/* Icon */}
                            <div style={{
                                width: '52px',
                                height: '52px',
                                borderRadius: '14px',
                                background: 'rgba(59, 130, 246, 0.1)',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                margin: '0 auto 16px',
                            }}>
                                <item.icon size={24} color="#60a5fa" />
                            </div>

                            {/* Title */}
                            <h3 style={{
                                fontSize: '16px',
                                fontWeight: 600,
                                marginBottom: '8px',
                                color: '#f1f5f9',
                            }}>
                                {item.title}
                            </h3>

                            {/* Description */}
                            <p style={{
                                fontSize: '13px',
                                color: '#94a3b8',
                                lineHeight: 1.5,
                            }}>
                                {item.description}
                            </p>
                        </div>
                    ))}
                </div>
            </div>
        </section>
    );
}
