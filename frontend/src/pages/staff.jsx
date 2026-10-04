// The staff portal. Everything here goes through staffApi, which holds the
// password in memory only. Each action calls the same @require_admin endpoints
// the README's commands use, so the server stays the only judge of what is
// allowed: a refused action shows the server's own message.
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, staffApi, useApi, useSubmit } from "../api.js";

const TABS = [
  { key: "requests", label: "Adoption & foster requests" },
  { key: "messages", label: "Messages" },
  { key: "offline", label: "Record offline" },
  { key: "animals", label: "Animals" },
];
const STATUSES = ["available", "fostering", "pending", "adopted"];
const PURPOSES = [
  { value: "general", label: "General" },
  { value: "medical_fund", label: "Medical fund" },
  { value: "food_fund", label: "Food fund" },
];

// Today's date in the browser's own calendar, as YYYY-MM-DD.
const today = () => new Date().toLocaleDateString("en-CA");

// Drop empty optional fields, so the server sees "not given" rather than "".
function filled(fields) {
  return Object.fromEntries(Object.entries(fields).filter(([, value]) => value !== "" && value != null));
}

export function StaffPortal() {
  const [client, setClient] = useState(null);
  return client ? <Portal client={client} onSignOut={() => setClient(null)} /> : <SignIn onSignedIn={setClient} />;
}

function SignIn({ onSignedIn }) {
  const [problem, setProblem] = useState(null);
  const [checking, setChecking] = useState(false);

  async function onSubmit(event) {
    event.preventDefault();
    const client = staffApi(new FormData(event.currentTarget).get("password"));
    setChecking(true);
    try {
      await client.checkSignIn();
      onSignedIn(client);
    } catch (error) {
      setProblem(
        error.status === 401
          ? "That password isn't right."
          : error.status === 503
            ? "Staff access isn't switched on for this site yet. Ask whoever runs the server to set the staff password."
            : error.message,
      );
      setChecking(false);
    }
  }

  return (
    <section className="staff-signin panel">
      <h1>Staff sign-in</h1>
      <p className="muted">For Al-Rahmeh's team. The password is kept only while this tab is open.</p>
      <form className="form" onSubmit={onSubmit}>
        <label>
          Staff password
          <input name="password" type="password" required autoComplete="current-password" />
        </label>
        {problem && <p className="error">{problem}</p>}
        <button className="button" type="submit" disabled={checking}>
          {checking ? "Checking…" : "Sign in"}
        </button>
      </form>
    </section>
  );
}

function Portal({ client, onSignOut }) {
  const [tab, setTab] = useState(TABS[0].key);
  return (
    <section className="staff">
      <div className="staff-top">
        <h1>Staff portal</h1>
        <button type="button" className="button button-soft" onClick={onSignOut}>
          Sign out
        </button>
      </div>
      <div className="chips" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            className={tab === t.key ? "chip active" : "chip"}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "requests" && <RequestsTab client={client} />}
      {tab === "messages" && <MessagesTab client={client} />}
      {tab === "offline" && <OfflineTab client={client} />}
      {tab === "animals" && <AnimalsTab client={client} />}
    </section>
  );
}

// --- requests ------------------------------------------------------------------

function RequestsTab({ client }) {
  const [status, setStatus] = useState("open");
  const [version, setVersion] = useState(0);
  const [problem, setProblem] = useState(null);
  const requests = useApi(() => client.requests(status), [status, version]);
  const animals = useApi(() => api.listAnimals(), [version]);
  const names = animals.status === "ok" ? Object.fromEntries(animals.data.animals.map((a) => [a.id, a.name])) : {};

  async function decide(id, outcome) {
    setProblem(null);
    try {
      await client.decide(id, outcome);
      setVersion((v) => v + 1);
    } catch (error) {
      setProblem(error.message);
    }
  }

  return (
    <>
      <Filter value={status} onChange={setStatus} options={["open", "approved", "declined"]} />
      {problem && <p className="error">{problem}</p>}
      <Listing state={requests} empty="No requests here." items={(data) => data.requests}>
        {(r) => (
          <li key={r.id} className="staff-item">
            <p>
              <strong>{r.kind === "adoption" ? "Adopt" : "Foster"}</strong>{" "}
              <Link to={`/animals/${r.animal_id}`}>{names[r.animal_id] ?? `animal ${r.animal_id}`}</Link>{" "}
              <span className="muted">· {r.submitted_at} · {r.outcome}</span>
            </p>
            <p>
              {r.applicant_name} · <a href={`mailto:${r.applicant_email}`}>{r.applicant_email}</a>
            </p>
            {r.message && <p className="quote">{r.message}</p>}
            {r.outcome === "open" && (
              <p className="row">
                <button type="button" className="button" onClick={() => decide(r.id, "approved")}>
                  Approve
                </button>
                <button type="button" className="button button-soft" onClick={() => decide(r.id, "declined")}>
                  Decline
                </button>
              </p>
            )}
            {r.outcome === "approved" && r.kind === "adoption" && (
              <p className="row">
                <button type="button" className="button button-soft" onClick={() => decide(r.id, "declined")}>
                  Adoption fell through
                </button>
              </p>
            )}
          </li>
        )}
      </Listing>
    </>
  );
}

// --- messages ------------------------------------------------------------------

function MessagesTab({ client }) {
  const [handled, setHandled] = useState(false);
  const [version, setVersion] = useState(0);
  const messages = useApi(() => client.enquiries(handled), [handled, version]);

  async function markHandled(id) {
    await client.markHandled(id);
    setVersion((v) => v + 1);
  }

  return (
    <>
      <Filter
        value={handled ? "handled" : "waiting"}
        onChange={(v) => setHandled(v === "handled")}
        options={["waiting", "handled"]}
      />
      <Listing state={messages} empty="No messages here." items={(data) => data.enquiries}>
        {(m) => (
          <li key={m.id} className="staff-item">
            <p>
              <span className={`badge badge-topic`}>{m.topic.replace("_", " ")}</span>{" "}
              <strong>{m.subject}</strong> <span className="muted">· {m.received_at}</span>
            </p>
            <p>
              {m.name} · <a href={`mailto:${m.email}?subject=${encodeURIComponent(`Re: ${m.subject}`)}`}>{m.email}</a>
            </p>
            <p className="quote">{m.message}</p>
            {!m.handled && (
              <p className="row">
                <button type="button" className="button button-soft" onClick={() => markHandled(m.id)}>
                  Mark handled
                </button>
              </p>
            )}
          </li>
        )}
      </Listing>
    </>
  );
}

// --- offline donations and adoptions --------------------------------------------

function OfflineTab({ client }) {
  const [version, setVersion] = useState(0);
  const refresh = () => setVersion((v) => v + 1);
  const animals = useApi(() => api.listAnimals(), []);
  const donations = useApi(() => client.donations(), [version]);
  const adoptions = useApi(() => client.offlineAdoptions(), [version]);
  const donation = useSubmit(client.recordDonation);
  const adoption = useSubmit(client.recordOfflineAdoption);

  async function onDonation(event) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const animalId = f.get("earmarked_animal_id");
    const saved = await donation.submit(
      filled({
        amount_jod: f.get("amount_jod").trim(),
        purpose: f.get("purpose"),
        donor_name: f.get("donor_name").trim(),
        received_on: f.get("received_on"),
        earmarked_animal_id: animalId ? Number.parseInt(animalId, 10) : null,
      }),
    );
    if (saved) {
      event.target.reset();
      refresh();
    }
  }

  async function onAdoption(event) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const saved = await adoption.submit(
      filled({
        animal_count: Number.parseInt(f.get("animal_count"), 10),
        adopted_on: f.get("adopted_on"),
        note: f.get("note").trim(),
      }),
    );
    if (saved) {
      event.target.reset();
      refresh();
    }
  }

  return (
    <div className="staff-columns">
      <section className="panel">
        <h2>A donation received offline</h2>
        <p className="muted small">Cash, CliQ or bank transfer. Card donations record themselves.</p>
        <form className="form" onSubmit={onDonation}>
          <label>
            Amount in JOD
            <input name="amount_jod" required inputMode="decimal" placeholder="25.500" />
          </label>
          <label>
            Purpose
            <select name="purpose" defaultValue="general">
              {PURPOSES.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>
              For one animal <span className="muted">(optional)</span>
            </span>
            <select name="earmarked_animal_id" defaultValue="">
              <option value="">All the animals</option>
              {animals.status === "ok" &&
                animals.data.animals.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
            </select>
          </label>
          <label>
            <span>
              Donor's name <span className="muted">(optional)</span>
            </span>
            <input name="donor_name" maxLength={120} />
          </label>
          <label>
            Received on
            <input name="received_on" type="date" defaultValue={today()} max={today()} />
          </label>
          <Outcome state={donation} done="Donation recorded." />
          <button className="button" type="submit" disabled={donation.sending}>
            Record donation
          </button>
        </form>
        <h3>Latest donations</h3>
        <Listing state={donations} empty="None yet." items={(data) => data.donations}>
          {(d) => (
            <li key={d.id} className="staff-line">
              {d.received_on} · <strong>{d.amount_jod} JOD</strong> · {d.purpose.replace("_", " ")}
              {d.donor_name && ` · ${d.donor_name}`}
            </li>
          )}
        </Listing>
      </section>

      <section className="panel">
        <h2>Adoptions arranged offline</h2>
        <p className="muted small">
          For animals not on the website, or adoptions from before it. Animals on the website are
          adopted from the Requests or Animals tab instead.
        </p>
        <form className="form" onSubmit={onAdoption}>
          <label>
            How many animals
            <input name="animal_count" type="number" min={1} max={10000} required defaultValue={1} />
          </label>
          <label>
            <span>
              Adopted on <span className="muted">(or the end of the period)</span>
            </span>
            <input name="adopted_on" type="date" required defaultValue={today()} max={today()} />
          </label>
          <label>
            <span>
              Note <span className="muted">(optional)</span>
            </span>
            <input name="note" maxLength={500} placeholder="e.g. January 2018 to December 2025" />
          </label>
          <Outcome state={adoption} done="Adoptions recorded. They now count on the homepage." />
          <button className="button" type="submit" disabled={adoption.sending}>
            Record adoptions
          </button>
        </form>
        <h3>Recorded so far</h3>
        <Listing state={adoptions} empty="None yet." items={(data) => data.offline_adoptions}>
          {(a) => (
            <li key={a.id} className="staff-line">
              {a.adopted_on} · <strong>{a.animal_count}</strong> {a.animal_count === 1 ? "animal" : "animals"}
              {a.note && ` · ${a.note}`}
            </li>
          )}
        </Listing>
      </section>
    </div>
  );
}

// --- animals ---------------------------------------------------------------------

function AnimalsTab({ client }) {
  const [version, setVersion] = useState(0);
  const refresh = () => setVersion((v) => v + 1);
  const animals = useApi(() => api.listAnimals(), [version]);
  const admit = useSubmit(client.admit);

  async function onAdmit(event) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const saved = await admit.submit(
      filled({
        name: f.get("name").trim(),
        species: f.get("species").trim(),
        breed: f.get("breed").trim(),
        intake_date: f.get("intake_date"),
        notes: f.get("notes").trim(),
      }),
    );
    if (saved) {
      event.target.reset();
      refresh();
    }
  }

  return (
    <div className="staff-columns">
      <section className="panel">
        <h2>Admit an animal</h2>
        <form className="form" onSubmit={onAdmit}>
          <label>
            Name
            <input name="name" required maxLength={80} />
          </label>
          <label>
            Species
            <input name="species" required maxLength={40} placeholder="Dog, Cat…" />
          </label>
          <label>
            <span>
              Breed <span className="muted">(optional)</span>
            </span>
            <input name="breed" maxLength={80} />
          </label>
          <label>
            Arrived on
            <input name="intake_date" type="date" required defaultValue={today()} max={today()} />
          </label>
          <label>
            <span>
              Staff notes <span className="muted">(never shown publicly)</span>
            </span>
            <textarea name="notes" rows={3} maxLength={2000} />
          </label>
          <Outcome state={admit} done="Animal admitted." />
          <button className="button" type="submit" disabled={admit.sending}>
            Admit
          </button>
        </form>
      </section>

      <section className="panel">
        <h2>All animals</h2>
        <Listing state={animals} empty="No animals yet." items={(data) => data.animals}>
          {(animal) => <AnimalRow key={animal.id} animal={animal} client={client} onChange={refresh} />}
        </Listing>
      </section>
    </div>
  );
}

function AnimalRow({ animal, client, onChange }) {
  const [problem, setProblem] = useState(null);
  const [note, setNote] = useState(null);
  const [editing, setEditing] = useState(false);
  const [uploading, setUploading] = useState(false);

  async function act(action, success) {
    setProblem(null);
    setNote(null);
    try {
      await action();
      setNote(success);
      onChange();
    } catch (error) {
      setProblem(error.message);
    }
  }

  function onMove(event) {
    event.preventDefault();
    const to = new FormData(event.currentTarget).get("to");
    act(() => client.transition(animal.id, to), `Moved to ${to}.`);
  }

  function onRecord(event) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    act(
      () =>
        client.addMedicalRecord(animal.id, {
          record_type: f.get("record_type"),
          description: f.get("description").trim(),
          occurred_on: f.get("occurred_on"),
        }),
      "Medical record added.",
    );
    event.target.reset();
  }

  async function onPhoto(event) {
    const input = event.target;
    const file = input.files[0];
    // Cleared at once, so picking the same file again still uploads it. The
    // thumbnail and the button, not the browser's file field, show the result.
    input.value = "";
    if (!file) return;
    setUploading(true);
    await act(() => client.uploadPhoto(animal.id, file), `Photo uploaded: ${file.name}`);
    setUploading(false);
  }

  return (
    <li className="staff-item">
      <p>
        <Link to={`/animals/${animal.id}`}>
          <strong>{animal.name}</strong>
        </Link>{" "}
        <span className="muted">
          · {animal.species} · {animal.status}
        </span>
      </p>
      <form className="row" onSubmit={onMove}>
        <select name="to" defaultValue="" required aria-label={`New status for ${animal.name}`}>
          <option value="" disabled>
            Change status…
          </option>
          {STATUSES.filter((s) => s !== animal.status).map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <button className="button button-soft" type="submit">
          Move
        </button>
      </form>
      <form className="row" onSubmit={onRecord}>
        <select name="record_type" defaultValue="vaccination" aria-label="Record type">
          <option value="vaccination">Vaccination</option>
          <option value="treatment">Treatment</option>
          <option value="checkup">Check-up</option>
        </select>
        <input name="description" required maxLength={500} placeholder="e.g. Rabies" aria-label="Description" />
        <input name="occurred_on" type="date" required defaultValue={today()} max={today()} aria-label="Date" />
        <button className="button button-soft" type="submit">
          Add
        </button>
      </form>
      <div className="row photo-input">
        {animal.photo_url && (
          <img className="photo-thumb" src={animal.photo_url} alt={`Current photo of ${animal.name}`} />
        )}
        <label className="button button-soft">
          {uploading ? "Uploading…" : animal.photo_url ? "Replace photo" : "Add a photo"}
          <input
            className="visually-hidden"
            type="file"
            accept="image/jpeg,image/png,image/webp"
            onChange={onPhoto}
            disabled={uploading}
          />
        </label>
        <span className="muted small">JPEG, PNG or WebP, up to 10 MB</span>
      </div>
      <details onToggle={(event) => setEditing(event.currentTarget.open)}>
        <summary>Profile for adopters (age, colour, personality, weight, about)</summary>
        {editing && <ProfileEditor animal={animal} client={client} onSaved={(text) => setNote(text)} />}
      </details>
      {note && <p className="success">{note}</p>}
      {problem && <p className="error">{problem}</p>}
    </li>
  );
}

// The public "about me" details, loaded only when staff open the section.
// Saving replaces the whole profile, so every field is sent, blank or not.
function ProfileEditor({ animal, client, onSaved }) {
  const current = useApi(() => client.staffAnimal(animal.id), [animal.id]);
  const save = useSubmit((profile) => client.updateProfile(animal.id, profile));

  if (current.status !== "ok") return <Listing state={current} empty="" items={() => []} />;
  const profile = current.data.profile;

  async function onSubmit(event) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const saved = await save.submit(
      filled({
        born_on: f.get("born_on"),
        colour: f.get("colour").trim(),
        personality: f.get("personality").trim(),
        weight_kg: f.get("weight_kg").trim(),
        about: f.get("about").trim(),
      }),
    );
    if (saved) onSaved(`${animal.name}'s profile saved.`);
  }

  return (
    <form className="form" onSubmit={onSubmit}>
      <label>
        <span>
          Date of birth <span className="muted">(an estimate is fine)</span>
        </span>
        <input name="born_on" type="date" max={today()} defaultValue={profile.born_on ?? ""} />
      </label>
      <label>
        Colour
        <input name="colour" maxLength={40} defaultValue={profile.colour ?? ""} placeholder="Rich golden" />
      </label>
      <label>
        Personality
        <input name="personality" maxLength={60} defaultValue={profile.personality ?? ""} placeholder="Friendly" />
      </label>
      <label>
        <span>
          Weight <span className="muted">(kg)</span>
        </span>
        <input name="weight_kg" inputMode="decimal" defaultValue={profile.weight_kg ?? ""} placeholder="12.5" />
      </label>
      <label>
        <span>
          About {animal.name} <span className="muted">(shown on the public profile)</span>
        </span>
        <textarea name="about" rows={3} maxLength={1000} defaultValue={profile.about ?? ""} />
      </label>
      <Outcome state={save} done="Saved." />
      <button className="button" type="submit" disabled={save.sending}>
        Save profile
      </button>
    </form>
  );
}

// --- small shared pieces -------------------------------------------------------

function Filter({ value, onChange, options }) {
  return (
    <div className="chips">
      {options.map((option) => (
        <button
          key={option}
          type="button"
          className={value === option ? "chip active" : "chip"}
          aria-pressed={value === option}
          onClick={() => onChange(option)}
        >
          {option}
        </button>
      ))}
    </div>
  );
}

function Listing({ state, empty, items, children }) {
  if (state.status === "loading") return <p className="muted">Loading…</p>;
  if (state.status === "error") return <p className="error">{state.error.message}</p>;
  const list = items(state.data);
  return list.length === 0 ? <p className="muted">{empty}</p> : <ul className="staff-list">{list.map(children)}</ul>;
}

function Outcome({ state, done }) {
  if (state.status === "done") return <p className="success">{done}</p>;
  if (state.status === "error") return <p className="error">{state.error.message}</p>;
  return null;
}
