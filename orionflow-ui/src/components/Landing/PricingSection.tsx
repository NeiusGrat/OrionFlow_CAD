import { Link } from 'react-router-dom';
import { Check } from 'lucide-react';

const plans = [
    {
        name: 'Free',
        badge: 'Beta',
        price: '$0',
        period: '/month',
        description: 'Perfect for exploring OrionFlow',
        features: [
            'Limited tokens per month',
            'STEP export',
            'Single-part projects',
            'Community support',
        ],
        cta: 'Start Free',
        highlighted: false,
    },
    {
        name: 'Pro',
        badge: null,
        price: '$20',
        period: '/month',
        description: 'For serious engineering work',
        features: [
            'Higher token limits',
            'Priority solving',
            'Unlimited projects',
            'All export formats',
            'Email support',
        ],
        cta: 'Upgrade to Pro',
        highlighted: true,
    },
    {
        name: 'Enterprise',
        badge: null,
        price: 'Custom',
        period: '',
        description: 'For teams and organizations',
        features: [
            'Team collaboration',
            'Custom-trained models',
            'Private deployments',
            'API access',
            'Dedicated support',
        ],
        cta: 'Contact Sales',
        highlighted: false,
    },
];

export default function PricingSection() {
    return (
        <section style={{
            padding: '120px 48px',
            position: 'relative',
            background: 'linear-gradient(180deg, transparent 0%, rgba(59, 130, 246, 0.02) 50%, transparent 100%)',
        }}>
            <div style={{ maxWidth: '1100px', margin: '0 auto' }}>
                {/* Section header */}
                <div style={{ textAlign: 'center', marginBottom: '64px' }}>
                    <h2 style={{
                        fontSize: '40px',
                        fontWeight: 700,
                        letterSpacing: '-0.02em',
                        marginBottom: '16px',
                    }}>
                        Simple, Transparent Pricing
                    </h2>
                    <p style={{
                        fontSize: '18px',
                        color: '#94a3b8',
                    }}>
                        Start free. Scale as you grow.
                    </p>
                </div>

                {/* Pricing cards */}
                <div style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(3, 1fr)',
                    gap: '24px',
                }}>
                    {plans.map((plan, index) => (
                        <div
                            key={index}
                            style={{
                                background: plan.highlighted
                                    ? 'linear-gradient(145deg, rgba(37, 99, 235, 0.15) 0%, rgba(15, 23, 42, 0.95) 100%)'
                                    : 'rgba(15, 23, 42, 0.6)',
                                border: plan.highlighted
                                    ? '1px solid rgba(59, 130, 246, 0.4)'
                                    : '1px solid rgba(255, 255, 255, 0.06)',
                                borderRadius: '20px',
                                padding: '36px 32px',
                                position: 'relative',
                                transition: 'all 0.3s ease',
                            }}
                            onMouseEnter={(e) => {
                                if (!plan.highlighted) {
                                    e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.12)';
                                }
                            }}
                            onMouseLeave={(e) => {
                                if (!plan.highlighted) {
                                    e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.06)';
                                }
                            }}
                        >
                            {/* Plan name + badge */}
                            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '20px' }}>
                                <h3 style={{
                                    fontSize: '20px',
                                    fontWeight: 600,
                                    color: '#f1f5f9',
                                }}>
                                    {plan.name}
                                </h3>
                                {plan.badge && (
                                    <span style={{
                                        background: 'rgba(34, 197, 94, 0.15)',
                                        color: '#86efac',
                                        padding: '4px 10px',
                                        borderRadius: '100px',
                                        fontSize: '11px',
                                        fontWeight: 600,
                                        textTransform: 'uppercase',
                                    }}>
                                        {plan.badge}
                                    </span>
                                )}
                            </div>

                            {/* Price */}
                            <div style={{ marginBottom: '8px' }}>
                                <span style={{
                                    fontSize: '44px',
                                    fontWeight: 700,
                                    color: '#f8fafc',
                                    letterSpacing: '-0.02em',
                                }}>
                                    {plan.price}
                                </span>
                                {plan.period && (
                                    <span style={{ fontSize: '16px', color: '#64748b' }}>{plan.period}</span>
                                )}
                            </div>

                            {/* Description */}
                            <p style={{
                                fontSize: '14px',
                                color: '#94a3b8',
                                marginBottom: '28px',
                            }}>
                                {plan.description}
                            </p>

                            {/* Features */}
                            <ul style={{
                                listStyle: 'none',
                                marginBottom: '32px',
                            }}>
                                {plan.features.map((feature, i) => (
                                    <li key={i} style={{
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '12px',
                                        marginBottom: '12px',
                                        fontSize: '14px',
                                        color: '#cbd5e1',
                                    }}>
                                        <Check size={16} color={plan.highlighted ? '#60a5fa' : '#64748b'} />
                                        {feature}
                                    </li>
                                ))}
                            </ul>

                            {/* CTA */}
                            <Link to="/auth" style={{ textDecoration: 'none' }}>
                                <button style={{
                                    width: '100%',
                                    padding: '14px 24px',
                                    borderRadius: '12px',
                                    fontWeight: 600,
                                    fontSize: '15px',
                                    border: 'none',
                                    cursor: 'pointer',
                                    transition: 'all 0.25s ease',
                                    background: plan.highlighted
                                        ? 'linear-gradient(135deg, #2563eb 0%, #3b82f6 100%)'
                                        : 'rgba(30, 41, 59, 0.8)',
                                    color: plan.highlighted ? 'white' : '#cbd5e1',
                                    boxShadow: plan.highlighted ? '0 4px 20px rgba(59, 130, 246, 0.4)' : 'none',
                                }}
                                    onMouseEnter={(e) => {
                                        if (plan.highlighted) {
                                            e.currentTarget.style.transform = 'translateY(-2px)';
                                            e.currentTarget.style.boxShadow = '0 8px 30px rgba(59, 130, 246, 0.5)';
                                        } else {
                                            e.currentTarget.style.background = 'rgba(51, 65, 85, 0.8)';
                                        }
                                    }}
                                    onMouseLeave={(e) => {
                                        if (plan.highlighted) {
                                            e.currentTarget.style.transform = 'translateY(0)';
                                            e.currentTarget.style.boxShadow = '0 4px 20px rgba(59, 130, 246, 0.4)';
                                        } else {
                                            e.currentTarget.style.background = 'rgba(30, 41, 59, 0.8)';
                                        }
                                    }}
                                >
                                    {plan.cta}
                                </button>
                            </Link>
                        </div>
                    ))}
                </div>
            </div>
        </section>
    );
}
