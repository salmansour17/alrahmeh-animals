// The homepage. Its counters are the audit's first fix made visible: every
// number comes from the live API at the moment the page loads. Nothing is
// typed in, and while a number is loading or unavailable the page shows a dash,
// never a guess.
import { Link } from "react-router-dom";
import { api, useApi } from "../api.js";
import { BowlIcon, HeartIcon, HomeIcon, PawIcon } from "../art.jsx";
import { ORG, WaysToHelp } from "./about.jsx";
import { AnimalCard } from "./animals.jsx";

const FEATURED = 3;

export function Home() {
  const stats = useApi(() => api.placementStats(), []);
  const impact = useApi(() => api.impact(), []);
  const animals = useApi(() => api.listAnimals("available"), []);

  return (
    <>
      <section className="hero hero-home">
        <div className="hero-text">
          <p className="eyebrow">
            <PawIcon size={18} /> Do you care? Get involved!
          </p>
          <h1>Every paw deserves a home</h1>
          <p className="lead">
            We rescue dogs and cats, nurse them back to health, and help them find families who
            will love them for life. You can be part of their story.
          </p>
          <div className="actions">
            <Link className="button" to="/animals">
              Meet the animals
            </Link>
            <Link className="button button-soft" to="/donate">
              <HeartIcon size={18} /> Donate
            </Link>
          </div>
        </div>
      </section>

      <section aria-labelledby="impact-heading">
        <h2 id="impact-heading" className="section-title">
          What your kindness has done
        </h2>
        <ul className="counters">
          <Counter
            icon={<HomeIcon size={28} />}
            value={stats.status === "ok" ? stats.data.homes_found : null}
            label="animals have found their forever homes"
          />
          <Counter
            icon={<HeartIcon size={28} />}
            value={impact.status === "ok" ? `${impact.data.total_raised.amount_jod} JOD` : null}
            label="raised for their food and care"
          />
          <Counter
            icon={<BowlIcon size={28} />}
            value={impact.status === "ok" ? impact.data.animals_helped : null}
            label="animals helped by gifts given just for them"
          />
        </ul>
        <p className="muted small">These numbers are counted live from our records.</p>
      </section>

      <section aria-labelledby="help-heading">
        <h2 id="help-heading" className="section-title">
          Don't let them suffer
        </h2>
        <p className="lead">
          So many animals in Jordan are still waiting for a home. Here's how you can change one
          life today.
        </p>
        <WaysToHelp />
      </section>

      <section aria-labelledby="featured-heading">
        <h2 id="featured-heading" className="section-title">
          Waiting to meet you
        </h2>
        {animals.status === "ok" && animals.data.animals.length > 0 ? (
          <ul className="cards">
            {animals.data.animals.slice(0, FEATURED).map((animal) => (
              <AnimalCard key={animal.id} animal={animal} />
            ))}
          </ul>
        ) : (
          <p className="gentle">
            {animals.status === "loading" ? "Fetching wagging tails…" : "New friends arrive every week."}
          </p>
        )}
        <p className="center">
          <Link to="/animals">See everyone looking for a home →</Link>
        </p>
      </section>

      <section className="panel panel-warm save-a-life">
        <h2>
          <HeartIcon /> Save a life
        </h2>
        <p>
          Follow our rescues day by day, share their stories, and help the right family find
          them.
        </p>
        <a className="button" href={ORG.instagram} target="_blank" rel="noopener noreferrer">
          See our animals on Instagram
        </a>
      </section>
    </>
  );
}

function Counter({ icon, value, label }) {
  const known = value !== null && value !== undefined;
  return (
    <li className="counter">
      <span className="counter-icon">{icon}</span>
      <strong aria-label={known ? undefined : "not available right now"}>{known ? value : "—"}</strong>
      <span>{label}</span>
    </li>
  );
}
