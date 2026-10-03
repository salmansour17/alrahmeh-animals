// The homepage. Its counters are the audit's first fix made visible: every
// number comes from the live API at the moment the page loads. Nothing is
// typed in, and while a number is loading or unavailable the page shows a dash,
// never a guess.
import { Link } from "react-router-dom";
import { api, useApi } from "../api.js";
import { BowlIcon, Cloud, HeartIcon, HomeIcon, PawPrint, Pill, Portrait } from "../art.jsx";
import { ORG, WaysToHelp } from "./about.jsx";
import { AnimalCard } from "./animals.jsx";

const FEATURED = 3;

export function Home() {
  const stats = useApi(() => api.placementStats(), []);
  const impact = useApi(() => api.impact(), []);
  const animals = useApi(() => api.listAnimals("available"), []);
  const available = animals.status === "ok" ? animals.data.animals : [];
  // The hero shows a real animal looking for a home, preferably one with a photo.
  const star = available.find((a) => a.photo_url) ?? available[0];

  return (
    <>
      <section className="hero-fluffy">
        <Cloud className="cloud-1" />
        <Cloud className="cloud-2" />
        <Cloud className="cloud-3" />
        <PawPrint size={46} className="paw-1" />
        <PawPrint size={40} className="paw-2" />
        <p className="eyebrow">
          <HeartIcon size={16} /> Do you care? Get involved!
        </p>
        <h1>Where every paw finds a home</h1>
        <p className="lead">
          We rescue dogs and cats in Jordan, nurse them back to health, and help them find families
          who will love them for life.
        </p>
        <div className="hero-photo">
          {star?.photo_url ? (
            <img src={star.photo_url} alt={`${star.name}, waiting for a home`} />
          ) : (
            <Portrait species={star?.species ?? "dog"} name={star?.name ?? "our friends"} />
          )}
        </div>
        <Link to="/animals?species=dog" className="blob-tag blob-dogs">
          Dogs
        </Link>
        <Link to="/animals?species=cat" className="blob-tag blob-cats">
          Cats
        </Link>
        <Pill to="/animals" tone="mustard">
          Meet the animals
        </Pill>
      </section>

      <section aria-labelledby="impact-heading">
        <h2 id="impact-heading" className="section-title">
          What your kindness has done
        </h2>
        <ul className="counters">
          <Counter
            icon={<HomeIcon size={24} />}
            value={stats.status === "ok" ? stats.data.homes_found : null}
            label="animals have found their forever homes"
          />
          <Counter
            icon={<HeartIcon size={24} />}
            value={impact.status === "ok" ? `${impact.data.total_raised.amount_jod} JOD` : null}
            label="raised for their food and care"
          />
          <Counter
            icon={<BowlIcon size={24} />}
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
        <WaysToHelp />
      </section>

      <section aria-labelledby="featured-heading">
        <h2 id="featured-heading" className="section-title">
          Waiting to meet you
        </h2>
        {available.length > 0 ? (
          <ul className="cards">
            {available.slice(0, FEATURED).map((animal) => (
              <AnimalCard key={animal.id} animal={animal} />
            ))}
          </ul>
        ) : (
          <p className="gentle">
            {animals.status === "loading" ? "Fetching wagging tails…" : "New friends arrive every week."}
          </p>
        )}
      </section>

      <section className="panel panel-warm center">
        <h2 style={{ justifyContent: "center" }}>
          <HeartIcon /> Save a life
        </h2>
        <p>Follow our rescues day by day, share their stories, and help the right family find them.</p>
        <Pill href={ORG.instagram} target="_blank" rel="noopener noreferrer">
          See our animals on Instagram
        </Pill>
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
