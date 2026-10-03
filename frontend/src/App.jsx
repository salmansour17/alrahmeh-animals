import { useEffect } from "react";
import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { HeartIcon, Logo, PawIcon } from "./art.jsx";
import { About, Contact, ORG } from "./pages/about.jsx";
import { AnimalDetail, AnimalList } from "./pages/animals.jsx";
import { Donate, Thanks } from "./pages/donate.jsx";
import { Home } from "./pages/home.jsx";
import { Shop } from "./pages/shop.jsx";
import { StaffPortal } from "./pages/staff.jsx";

// The association's name in Arabic, exactly as the rescue writes it.
const ARABIC_NAME = "جمعية الرحمة للرفق بالحيوان";

export default function App() {
  const location = useLocation();

  // A new page starts at the top, like a normal website, instead of keeping
  // the previous page's scroll position. Links to a section (#ask) still jump.
  useEffect(() => {
    if (!location.hash && !location.state?.keepScroll) window.scrollTo({ top: 0, behavior: "instant" });
  }, [location.pathname, location.hash]);

  // Moving from one animal's profile to another is not a new page: only the
  // profile itself animates, so the container keeps the same key.
  const pageKey = location.pathname.startsWith("/animals/") ? "animal-profile" : location.pathname;

  return (
    <>
      <header className="site-header">
        <Link to="/" className="brand" aria-label="Al-Rahmeh Association for Animals, home">
          <Logo />
          <span className="brand-text">
            <span className="brand-name">Al-Rahmeh</span>
            <span className="brand-sub">Association for Animals</span>
            <span className="arabic" lang="ar" dir="rtl">
              {ARABIC_NAME}
            </span>
          </span>
        </Link>
        <nav>
          <NavLink to="/animals">Meet the animals</NavLink>
          <NavLink to="/about">About us</NavLink>
          <NavLink to="/shop">Gift shop</NavLink>
          <NavLink to="/contact">Contact</NavLink>
          <NavLink to="/donate" className="nav-donate">
            <HeartIcon size={16} /> Donate
          </NavLink>
        </nav>
      </header>
      {/* Keyed by the path, so each page fades in as it arrives. */}
      <main key={pageKey} className="page">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/animals" element={<AnimalList />} />
          <Route path="/animals/:id" element={<AnimalDetail />} />
          <Route path="/donate" element={<Donate />} />
          <Route path="/donate/thanks" element={<Thanks />} />
          <Route path="/about" element={<About />} />
          <Route path="/shop" element={<Shop />} />
          <Route path="/contact" element={<Contact />} />
          <Route path="/staff" element={<StaffPortal />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      <footer className="site-footer">
        <nav className="footer-links" aria-label="More">
          <Link to="/about">About us</Link>
          <Link to="/contact?topic=volunteer">Volunteer</Link>
          <Link to="/shop">Gift shop</Link>
          <Link to="/contact">Contact</Link>
          <a href={`mailto:${ORG.email}`}>{ORG.email}</a>
          <a href={ORG.facebook} target="_blank" rel="noopener noreferrer">
            Facebook
          </a>
          <a href={ORG.instagram} target="_blank" rel="noopener noreferrer">
            Instagram
          </a>
        </nav>
        <p>
          Made with <HeartIcon size={16} label="love" /> for the animals of Jordan
        </p>
        <p lang="ar" dir="rtl" className="arabic">
          {ARABIC_NAME}
        </p>
        <p className="small">
          © 2026 Al Rahmeh for Animals · <Link to="/staff">Staff sign-in</Link>
        </p>
      </footer>
    </>
  );
}

function NotFound() {
  return (
    <section className="gentle-page">
      <PawIcon size={48} />
      <h1>Oops, this path leads nowhere</h1>
      <p>
        But plenty of friends are waiting for you. <Link to="/animals">Come and meet them</Link>
      </p>
    </section>
  );
}
