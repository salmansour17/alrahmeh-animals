// The public animal pages. They show only what the public API returns: no
// staff notes and no medical record except vaccinations. Every value is
// rendered as text by React, which escapes it.
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, useApi } from "../api.js";
import { CalendarIcon, HeartIcon, HomeIcon, PawIcon, Portrait, ShieldIcon } from "../art.jsx";

// One place for how each placement status is described to visitors.
const STATUS = {
  available: {
    chip: "Looking for a home",
    badge: "Looking for a home",
    sentence: (name) => `${name} is looking for a loving home.`,
  },
  fostering: {
    chip: "In a foster home",
    badge: "With a foster family",
    sentence: (name) => `${name} is staying with a kind foster family for now.`,
  },
  pending: {
    chip: "Adoption on the way",
    badge: "Adoption on the way",
    sentence: (name) => `Someone has already fallen for ${name}. An adoption is on the way!`,
  },
  adopted: {
    chip: "Home at last",
    badge: "Found a forever home",
    sentence: (name) => `${name} has found a forever home. Thank you to everyone who helped.`,
  },
};

const FACEBOOK = "https://facebook.com/Rahmehforanimals";

export function AnimalList() {
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const state = useApi(() => api.listAnimals(status), [status]);

  return (
    <>
      <section className="hero">
        <div className="hero-text">
          <p className="eyebrow">
            <PawIcon size={18} /> Al-Rahmeh Association for Animals
          </p>
          <h1>Every paw deserves a home</h1>
          <p className="lead">
            Meet the dogs and cats being cared for at Al-Rahmeh. Each one has a story, and a heart
            ready for someone like you.
          </p>
        </div>
        <div className="hero-art" aria-hidden="true">
          <Portrait species="dog" name="our friends" />
        </div>
      </section>

      <div className="chips" role="group" aria-label="Show animals">
        <Chip active={!status} onClick={() => setParams({})}>
          Everyone
        </Chip>
        {Object.entries(STATUS).map(([value, text]) => (
          <Chip key={value} active={status === value} onClick={() => setParams({ status: value })}>
            {text.chip}
          </Chip>
        ))}
      </div>

      <Loaded state={state}>
        {(data) =>
          data.animals.length === 0 ? (
            <p className="gentle">
              No friends here just now. Please check back soon, new animals arrive every week.
            </p>
          ) : (
            <ul className="cards">
              {data.animals.map((animal) => (
                <li key={animal.id}>
                  <Link to={`/animals/${animal.id}`} className="card">
                    <AnimalPhoto animal={animal} />
                    <div className="card-body">
                      <StatusBadge status={animal.status} />
                      <h2>{animal.name}</h2>
                      <p className="muted">
                        {animal.species}
                        {animal.breed && ` · ${animal.breed}`}
                      </p>
                      <span className="card-cta">
                        Meet {animal.name} <HeartIcon size={16} />
                      </span>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )
        }
      </Loaded>
    </>
  );
}

export function AnimalDetail() {
  const { id } = useParams();
  const state = useApi(() => api.getAnimal(id), [id]);

  return (
    <>
      <p>
        <Link to="/animals" className="back">
          ← Back to all our animals
        </Link>
      </p>
      <Loaded state={state} notFound="We couldn't find this friend. They may have a new page, or a new home!">
        {(animal) => (
          <article className="profile">
            <div className="profile-photo">
              <AnimalPhoto animal={animal} />
            </div>
            <div className="profile-text">
              <StatusBadge status={animal.status} />
              <h1>Hi, I'm {animal.name}!</h1>
              <p className="lead">{STATUS[animal.status]?.sentence(animal.name)}</p>

              <ul className="facts">
                <li>
                  <PawIcon /> {animal.species}
                  {animal.breed ? `, ${animal.breed}` : ""}
                </li>
                <li>
                  <CalendarIcon /> At Al-Rahmeh since {friendlyDate(animal.intake_date)}
                </li>
              </ul>

              <section className="panel">
                <h2>
                  <ShieldIcon /> Health &amp; vaccinations
                </h2>
                {animal.vaccinations.length === 0 ? (
                  <p className="muted">No vaccinations recorded yet. Our vets are on it.</p>
                ) : (
                  <ul className="checklist">
                    {animal.vaccinations.map((v, index) => (
                      <li key={index}>
                        {v.description} <span className="muted">· {friendlyDate(v.occurred_on)}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {animal.status !== "adopted" && (
                <section className="panel panel-warm">
                  <h2>
                    <HomeIcon /> Could {animal.name} be part of your family?
                  </h2>
                  <p>
                    Send us a message and we'll tell you all about {animal.name}, adopting and
                    fostering.
                  </p>
                  <a className="button" href={FACEBOOK} target="_blank" rel="noopener noreferrer">
                    Message us about {animal.name}
                  </a>
                </section>
              )}
            </div>
          </article>
        )}
      </Loaded>
    </>
  );
}

// The real photo when the API has one; a drawing of the species until then.
function AnimalPhoto({ animal }) {
  return (
    <div className="photo">
      {animal.photo_url ? (
        <img src={animal.photo_url} alt={`Photo of ${animal.name}`} loading="lazy" />
      ) : (
        <Portrait species={animal.species} name={animal.name} />
      )}
    </div>
  );
}

function Loaded({ state, notFound = "We couldn't find that.", children }) {
  if (state.status === "loading") {
    return (
      <p className="gentle">
        <PawIcon /> Fetching wagging tails…
      </p>
    );
  }
  if (state.status === "error") {
    const message = state.error.status === 404 ? notFound : state.error.message;
    return <p className="gentle error">{message}</p>;
  }
  return children(state.data);
}

function StatusBadge({ status }) {
  return <span className={`badge badge-${status}`}>{STATUS[status]?.badge ?? status}</span>;
}

function Chip({ active, onClick, children }) {
  return (
    <button type="button" className={active ? "chip active" : "chip"} aria-pressed={active} onClick={onClick}>
      {children}
    </button>
  );
}

// "2026-09-01" -> "1 September 2026". Parsed as a plain date, never through a
// time zone, so it cannot shift by a day.
function friendlyDate(iso) {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}
