// The public animal pages. They show only what the public API returns: no
// staff notes and no medical record except vaccinations. Every value is
// rendered as text by React, which escapes it.
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, useApi, useSubmit } from "../api.js";
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

// Which requests the form offers, by status. The server applies the same rule
// and has the final say; this only avoids offering what it would refuse.
const REQUEST_KINDS = {
  available: ["adoption", "foster"],
  fostering: ["adoption"],
  pending: ["adoption"],
  adopted: [],
};
const KIND_LABELS = { adoption: "Adopt", foster: "Foster" };

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
                <AnimalCard key={animal.id} animal={animal} />
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

              {REQUEST_KINDS[animal.status]?.length > 0 && <RequestForm animal={animal} />}

              <section className="panel">
                <h2>
                  <HeartIcon /> Help with {animal.name}'s care
                </h2>
                <p>A gift towards {animal.name}'s food, vaccinations and vet visits goes to {animal.name} alone.</p>
                <Link className="button button-soft" to={`/donate?animal=${animal.id}`}>
                  Give to {animal.name}
                </Link>
              </section>
            </div>
          </article>
        )}
      </Loaded>
    </>
  );
}

export function AnimalCard({ animal }) {
  return (
    <li>
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
  );
}

// The real photo when the API has one; a drawing of the species until then,
// or if the photo cannot be loaded.
function AnimalPhoto({ animal }) {
  const [failed, setFailed] = useState(false);
  return (
    <div className="photo">
      {animal.photo_url && !failed ? (
        <img
          src={animal.photo_url}
          alt={`Photo of ${animal.name}`}
          loading="lazy"
          onError={() => setFailed(true)}
        />
      ) : (
        <Portrait species={animal.species} name={animal.name} />
      )}
    </div>
  );
}

// The adoption and foster form: the real workflow that replaces the old
// Google Forms. Asking never changes the animal; staff decide every request.
function RequestForm({ animal }) {
  const kinds = REQUEST_KINDS[animal.status];
  const [kind, setKind] = useState(kinds[0]);
  const { status, error, sending, submit } = useSubmit((form) =>
    api.askToAdoptOrFoster(animal.id, form),
  );

  if (status === "done") {
    return (
      <section className="panel panel-warm" aria-live="polite">
        <h2>
          <HomeIcon /> Thank you!
        </h2>
        <p>
          We've received your request about {animal.name}. Our team reads every one and will
          reply by email, usually within a few days.
        </p>
      </section>
    );
  }

  function onSubmit(event) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    submit({
      kind,
      name: fields.get("name"),
      email: fields.get("email"),
      message: fields.get("message"),
      website: fields.get("website"),
    });
  }

  return (
    <section className="panel panel-warm">
      <h2>
        <HomeIcon /> Could {animal.name} be part of your family?
      </h2>
      <form className="form" onSubmit={onSubmit}>
        {kinds.length > 1 && (
          <div className="chips" role="radiogroup" aria-label="I would like to">
            {kinds.map((value) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={kind === value}
                className={kind === value ? "chip active" : "chip"}
                onClick={() => setKind(value)}
              >
                {KIND_LABELS[value]} {animal.name}
              </button>
            ))}
          </div>
        )}
        <label>
          Your name
          <input name="name" required maxLength={120} autoComplete="name" />
        </label>
        <label>
          Your email
          <input name="email" type="email" required maxLength={254} autoComplete="email" />
        </label>
        <label>
          <span>
            Tell us a little about your home <span className="muted">(optional)</span>
          </span>
          <textarea name="message" rows={4} maxLength={2000} />
        </label>
        {/* A trap for bots: invisible, unreachable by keyboard, and hidden from
            screen readers, so only an automated form-filler ever fills it in. */}
        <div className="trap" aria-hidden="true">
          <label>
            Website
            <input name="website" tabIndex={-1} autoComplete="off" />
          </label>
        </div>
        {status === "error" && <p className="error">{error.message}</p>}
        <button className="button" type="submit" disabled={sending}>
          {sending ? "Sending…" : `Send my request about ${animal.name}`}
        </button>
        <p className="muted small">
          Only our team sees your details, and only to reply to you.
        </p>
      </form>
    </section>
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
