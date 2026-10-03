import { Link, NavLink, Route, Routes } from "react-router-dom";
import { HeartIcon, PawIcon } from "./art.jsx";
import { About, Contact, ORG } from "./pages/about.jsx";
import { AnimalDetail, AnimalList } from "./pages/animals.jsx";
import { Donate, Thanks } from "./pages/donate.jsx";
import { Home } from "./pages/home.jsx";
import { Shop } from "./pages/shop.jsx";
import { StaffPortal } from "./pages/staff.jsx";

// The association's name in Arabic, exactly as the rescue writes it.
const ARABIC_NAME = "جمعية الرحمة للرفق بالحيوان";

export default function App() {
  return (
    <>
      <header className="site-header">
        <Link to="/" className="brand">
          <span className="brand-mark">
            <PawIcon size={22} />
          </span>
          <span>
            Al-Rahmeh
            <small>Association for Animals</small>
            <small className="arabic" lang="ar" dir="rtl">
              {ARABIC_NAME}
            </small>
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
      <main>
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
