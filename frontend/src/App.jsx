import { Link, Navigate, NavLink, Route, Routes } from "react-router-dom";
import { HeartIcon, PawIcon } from "./art.jsx";
import { AnimalDetail, AnimalList } from "./pages/animals.jsx";

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
          </span>
        </Link>
        <nav>
          <NavLink to="/animals">Meet the animals</NavLink>
        </nav>
      </header>
      <main>
        <Routes>
          {/* The homepage with live impact counters arrives with the donate page. */}
          <Route path="/" element={<Navigate to="/animals" replace />} />
          <Route path="/animals" element={<AnimalList />} />
          <Route path="/animals/:id" element={<AnimalDetail />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      <footer className="site-footer">
        <p>
          Made with <HeartIcon size={16} label="love" /> for the animals of Jordan
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
