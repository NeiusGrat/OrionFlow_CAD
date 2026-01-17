import Navbar from '../components/Landing/Navbar';
import HeroSection from '../components/Landing/HeroSection';
import DemoVideoSection from '../components/Landing/DemoVideoSection';
import AIDirectorSection from '../components/Landing/AIDirectorSection';
import CapabilitiesSection from '../components/Landing/CapabilitiesSection';
import BuiltForEngineersSection from '../components/Landing/BuiltForEngineersSection';
import PricingSection from '../components/Landing/PricingSection';
import FooterCTASection from '../components/Landing/FooterCTASection';

export default function LandingPage() {
    return (
        <div style={{
            minHeight: '100vh',
            background: '#030712',
            color: '#f8fafc',
            overflowX: 'hidden',
        }}>
            <Navbar />
            <HeroSection />
            <DemoVideoSection />
            <AIDirectorSection />
            <CapabilitiesSection />
            <BuiltForEngineersSection />
            <PricingSection />
            <FooterCTASection />
        </div>
    );
}
