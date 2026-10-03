// The public animal pages. They show only what the public API returns: no
// staff notes and no medical record except vaccinations. Every value is
// rendered as text by React, which escapes it.
import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, useApi, useSubmit } from "../api.js";
import {
  HeartIcon,
  HomeIcon,
  Orb,
  PawIcon,
  PawPrint,
  Pill,
  Portrait,
  ShieldIcon,
} from "../art.jsx";

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

// The species filter from the homepage's Dogs and Cats tags. Species is free
// text typed by staff, so it is matched loosely, in the browser.
const SPECIES = {
  dog: { label: "Dogs", matches: /dog|pupp/i },
  cat: { label: "Cats", matches: /cat|kitt/i },
};

// Where each photo sits in the paw hero: the four toes of the paw.
const TOES = [
  { cx: 92, cy: 214, rx: 62, ry: 78 },
  { cx: 214, cy: 96, rx: 68, ry: 90 },
  { cx: 386, cy: 96, rx: 68, ry: 90 },
  { cx: 508, cy: 214, rx: 62, ry: 78 },
];

export function AnimalList() {
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const species = SPECIES[params.get("species")] ? params.get("species") : "";
  const state = useApi(() => api.listAnimals(status), [status]);
  const everyone = useApi(() => api.listAnimals("available"), []);
  // Animals with a photo first, so the paw shows faces whenever it can.
  const faces =
    everyone.status === "ok"
      ? [...everyone.data.animals].sort((a, b) => Boolean(b.photo_url) - Boolean(a.photo_url)).slice(0, 4)
      : [];

  function choose(next) {
    const merged = { status, species, ...next };
    setParams(Object.fromEntries(Object.entries(merged).filter(([, v]) => v)));
  }

  return (
    <>
      <PawHero faces={faces} />
      <section id="animals">
        <div className="chips" role="group" aria-label="Show animals">
          <Chip active={!status} onClick={() => choose({ status: "" })}>
            Everyone
          </Chip>
          {Object.entries(STATUS).map(([value, text]) => (
            <Chip key={value} active={status === value} onClick={() => choose({ status: value })}>
              {text.chip}
            </Chip>
          ))}
          <span aria-hidden="true" className="muted">
            ·
          </span>
          {Object.entries(SPECIES).map(([value, s]) => (
            <Chip key={value} active={species === value} onClick={() => choose({ species: species === value ? "" : value })}>
              {s.label}
            </Chip>
          ))}
        </div>
        <Loaded state={state}>
          {(data) => {
            const shown = species ? data.animals.filter((a) => SPECIES[species].matches.test(a.species)) : data.animals;
            return shown.length === 0 ? (
              <p className="gentle">No friends here just now. Please check back soon, new animals arrive every week.</p>
            ) : (
              <ul className="cards">
                {shown.map((animal) => (
                  <AnimalCard key={animal.id} animal={animal} />
                ))}
              </ul>
            );
          }}
        </Loaded>
      </section>
    </>
  );
}

// Design 1: a big paw whose toes are windows onto real animals. Each toe is a
// link to that animal's profile; a toe with no animal behind it is decoration.
function PawHero({ faces }) {
  const navigate = useNavigate();
  const open = (animal) => navigate(`/animals/${animal.id}`);
  return (
    <section className="paw-hero">
      <svg viewBox="0 0 600 540" role="img" aria-label="A paw print with photos of animals looking for homes">
        <defs>
          {TOES.map((toe, i) => (
            <clipPath key={i} id={`toe-${i}`}>
              <ellipse cx={toe.cx} cy={toe.cy} rx={toe.rx} ry={toe.ry} />
            </clipPath>
          ))}
        </defs>
        {TOES.map((toe, i) => (
          <g
            key={i}
            className={faces[i] ? "toe toe-link" : "toe"}
            {...(faces[i] && {
              role: "link",
              tabIndex: 0,
              "aria-label": `Meet ${faces[i].name}`,
              onClick: () => open(faces[i]),
              onKeyDown: (event) => (event.key === "Enter" || event.key === " ") && open(faces[i]),
            })}
          >
            {faces[i] && <title>{`Meet ${faces[i].name}`}</title>}
            <ellipse className="toe-shape" cx={toe.cx} cy={toe.cy} rx={toe.rx} ry={toe.ry} />
            {faces[i]?.photo_url ? (
              <image
                href={faces[i].photo_url}
                x={toe.cx - toe.rx}
                y={toe.cy - toe.ry}
                width={toe.rx * 2}
                height={toe.ry * 2}
                preserveAspectRatio="xMidYMid slice"
                clipPath={`url(#toe-${i})`}
              />
            ) : (
              <g transform={`translate(${toe.cx - 22} ${toe.cy - 22}) scale(1.85)`} fill="#d8c7bc">
                <ellipse cx="12" cy="16" rx="4.5" ry="3.7" />
                <ellipse cx="5.8" cy="10.6" rx="1.9" ry="2.4" />
                <ellipse cx="9.5" cy="6.5" rx="1.9" ry="2.5" />
                <ellipse cx="14.5" cy="6.5" rx="1.9" ry="2.5" />
                <ellipse cx="18.2" cy="10.6" rx="1.9" ry="2.4" />
              </g>
            )}
          </g>
        ))}
        <path
          className="pad-shape"
          d="M300 230c130 0 226 98 230 190 4 72-62 104-136 96-46-5-62-26-94-26s-48 21-94 26c-74 8-140-24-136-96 4-92 100-190 230-190z"
        />
      </svg>
      <div className="paw-hero-text">
        <h1>Find your furry friend</h1>
        <p>Begin your adoption journey today!</p>
      </div>
      <div className="paw-hero-cta">
        <Pill href="#animals">Meet the animals</Pill>
      </div>
    </section>
  );
}

export function AnimalCard({ animal }) {
  return (
    <li>
      <Link to={`/animals/${animal.id}`} className="fcard">
        <div className="fcard-top">
          <AnimalPhoto animal={animal} />
        </div>
        <div className="fcard-panel">
          <StatusBadge status={animal.status} />
          <h2>{animal.name}</h2>
          <p>
            {animal.species}
            {animal.breed && ` · ${animal.breed}`}
          </p>
          <span className="fcard-link">
            Meet {animal.name} <HeartIcon size={16} />
          </span>
        </div>
      </Link>
    </li>
  );
}

export function AnimalDetail() {
  const { id } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const stage = useRef(null);
  // Keep the current animal on screen until the next one has arrived.
  const state = useApi(() => api.getAnimal(id), [id], { keepPrevious: true });
  const all = useApi(() => api.listAnimals(), []);
  const list = all.status === "ok" ? all.data.animals : [];
  const at = list.findIndex((a) => String(a.id) === String(id));
  const prev = at > 0 ? list[at - 1] : null;
  const next = at >= 0 && at < list.length - 1 ? list[at + 1] : null;
  const direction = location.state?.direction ?? "none";

  function go(target, dir) {
    if (target) navigate(`/animals/${target.id}`, { state: { direction: dir, keepScroll: true } });
  }

  // Fetch the neighbours' photos in the background, so PREV and NEXT are instant.
  useEffect(() => {
    [prev, next].forEach((animal) => {
      if (animal?.photo_url) new Image().src = animal.photo_url;
    });
  }, [prev, next]);

  // The arrow keys move between animals, except while someone is typing.
  useEffect(() => {
    function onKey(event) {
      if (event.target.closest("input, textarea, select, [contenteditable]")) return;
      if (event.key === "ArrowLeft") go(prev, "prev");
      if (event.key === "ArrowRight") go(next, "next");
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // Moving to a neighbour keeps the scroll position, but brings the arch back
  // into view, smoothly, if the visitor had scrolled away from it.
  useEffect(() => {
    if (!location.state?.keepScroll || !stage.current) return;
    const top = stage.current.getBoundingClientRect().top;
    if (top < 0 || top > window.innerHeight * 0.6) stage.current.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [state.data?.id]);

  return (
    <Loaded state={state} notFound="We couldn't find this friend. They may have a new page, or a new home!">
      {(animal) => {
        const profile = animal.profile ?? {};
        const canAsk = REQUEST_KINDS[animal.status]?.length > 0;
        return (
          <>
            <div className="profile-top">
              <Link to="/animals" className="back">
                ← All our animals
              </Link>
              <StatusBadge status={animal.status} />
            </div>

            <article
              ref={stage}
              className={state.refreshing ? "profile-stage is-refreshing" : "profile-stage"}
            >
              <div className="facts-col facts-fade" key={`left-${animal.id}`}>
                <Fact label="Name" value={animal.name} />
                <Fact label={animal.breed ? "Breed" : "Species"} value={animal.breed ?? animal.species} />
                <Fact label="Age" value={profile.age} />
              </div>

              <div className={`arch slide-${direction}`} key={`arch-${animal.id}`}>
                <h1>{animal.name}</h1>
                <Orb className="orb-heart" label={`Give to ${animal.name}'s care`} to={`/donate?animal=${animal.id}`}>
                  <HeartIcon size={26} />
                </Orb>
                <div className="arch-photo">
                  <AnimalPhoto animal={animal} />
                </div>
                <div className="arch-panel">
                  <p>{profile.about ?? STATUS[animal.status]?.sentence(animal.name)}</p>
                  {canAsk ? (
                    <Pill href="#ask">Adopt {animal.name}</Pill>
                  ) : (
                    <Pill to="/animals">Meet other friends</Pill>
                  )}
                </div>
                <a href="#ask" className="orb orb-paw" aria-label={`Ask about ${animal.name}`}>
                  <PawPrint size={24} />
                </a>
              </div>

              <div className="facts-col facts-right facts-fade" key={`right-${animal.id}`}>
                <Fact label="Colour" value={profile.colour} />
                <Fact label="Personality" value={profile.personality} />
                <Fact label="Weight" value={profile.weight} />
              </div>
            </article>

            <nav className="prevnext" aria-label="Other animals">
              {prev ? (
                <Link to={`/animals/${prev.id}`} state={{ direction: "prev", keepScroll: true }} title={`Previous: ${prev.name} (←)`}>
                  PREV
                </Link>
              ) : (
                <span>PREV</span>
              )}
              {next ? (
                <Link to={`/animals/${next.id}`} state={{ direction: "next", keepScroll: true }} title={`Next: ${next.name} (→)`}>
                  NEXT
                </Link>
              ) : (
                <span>NEXT</span>
              )}
            </nav>

            <div className="profile-more">
              <section className="panel">
                <h2>
                  <ShieldIcon /> Health &amp; vaccinations
                </h2>
                <p className="muted small">With us since {friendlyDate(animal.intake_date)}.</p>
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

              {canAsk && <RequestForm animal={animal} />}

              <section className="panel">
                <h2>
                  <HeartIcon /> Help with {animal.name}'s care
                </h2>
                <p>A gift towards {animal.name}'s food, vaccinations and vet visits goes to {animal.name} alone.</p>
                <Pill to={`/donate?animal=${animal.id}`} tone="soft">
                  Give to {animal.name}
                </Pill>
              </section>
            </div>
          </>
        );
      }}
    </Loaded>
  );
}

function Fact({ label, value }) {
  return (
    <div>
      <span className="fact-label">{label}</span>
      <span className="fact-value">{value || "—"}</span>
    </div>
  );
}

// The real photo when the API has one; a drawing of the species until then,
// or if the photo cannot be loaded.
function AnimalPhoto({ animal }) {
  const [failed, setFailed] = useState(false);
  return animal.photo_url && !failed ? (
    <img src={animal.photo_url} alt={`Photo of ${animal.name}`} loading="lazy" onError={() => setFailed(true)} />
  ) : (
    <Portrait species={animal.species} name={animal.name} />
  );
}

// The adoption and foster form: the real workflow that replaces the old
// Google Forms. Asking never changes the animal; staff decide every request.
function RequestForm({ animal }) {
  const kinds = REQUEST_KINDS[animal.status];
  const [kind, setKind] = useState(kinds[0]);
  const { status, error, sending, submit } = useSubmit((form) => api.askToAdoptOrFoster(animal.id, form));

  if (status === "done") {
    return (
      <section id="ask" className="panel panel-warm" aria-live="polite">
        <h2>
          <HomeIcon /> Thank you!
        </h2>
        <p>
          We've received your request about {animal.name}. Our team reads every one and will reply
          by email, usually within a few days.
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
    <section id="ask" className="panel panel-warm">
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
        <Pill type="submit" disabled={sending}>
          {sending ? "Sending…" : `Send my request about ${animal.name}`}
        </Pill>
        <p className="muted small">Only our team sees your details, and only to reply to you.</p>
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

