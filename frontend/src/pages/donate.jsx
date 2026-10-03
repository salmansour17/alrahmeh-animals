// The donate page and the thank-you page Stripe returns donors to.
//
// Amounts are strings from start to finish ("25.000"), exactly what the
// server's amount rule expects, so the browser never does arithmetic on money.
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, useApi, useSubmit } from "../api.js";
import { BowlIcon, HeartIcon, HomeIcon, PawIcon, ShieldIcon } from "../art.jsx";
import { ORG } from "./about.jsx";

const AMOUNTS = [
  { value: "5.000", label: "5 JOD" },
  { value: "10.000", label: "10 JOD" },
  { value: "25.000", label: "25 JOD" },
  { value: "50.000", label: "50 JOD" },
];

const PURPOSES = [
  {
    value: "medical_fund",
    title: "Medical care",
    text: "Vaccinations, surgery and medicine for animals who arrive sick or hurt.",
    icon: <ShieldIcon size={26} />,
  },
  {
    value: "food_fund",
    title: "Food & shelter",
    text: "Full bowls, warm bedding and a safe place to sleep tonight.",
    icon: <BowlIcon size={26} />,
  },
  {
    value: "general",
    title: "Wherever it's needed most",
    text: "Lets our team put your gift where the need is greatest this week.",
    icon: <HomeIcon size={26} />,
  },
];

export function Donate() {
  const [params] = useSearchParams();
  // Only a plain number from the address bar is used, and only to look the
  // animal up: the name shown always comes from the API, never the URL.
  const animalParam = params.get("animal");
  const animalId = animalParam && /^\d+$/.test(animalParam) ? animalParam : null;
  const animal = useApi(() => (animalId ? api.getAnimal(animalId) : Promise.resolve(null)), [animalId]);
  const earmarked = animal.status === "ok" && animal.data ? animal.data : null;

  const [amount, setAmount] = useState(AMOUNTS[1].value);
  const [custom, setCustom] = useState("");
  const [purpose, setPurpose] = useState(animalId ? "medical_fund" : "general");
  const { status, error, sending, submit } = useSubmit(api.startCheckout);

  async function onSubmit(event) {
    event.preventDefault();
    const donorName = new FormData(event.currentTarget).get("donor_name").trim();
    const session = await submit({
      amount_jod: custom.trim() || amount,
      purpose,
      ...(earmarked ? { earmarked_animal_id: earmarked.id } : {}),
      ...(donorName ? { donor_name: donorName } : {}),
    });
    // Off to Stripe's own secure page; the card never touches this site.
    if (session?.checkout_url?.startsWith("https://")) window.location.assign(session.checkout_url);
  }

  const unavailable = status === "error" && error.status === 503;

  return (
    <>
      <section className="hero hero-donate">
        <div className="hero-text">
          <p className="eyebrow">
            <HeartIcon size={18} /> Every gift is a meal, a vaccine, a second chance
          </p>
          <h1>{earmarked ? `Help ${earmarked.name}` : "Give a rescued animal a better tomorrow"}</h1>
          <p className="lead">
            Al-Rahmeh runs on kindness. Whatever you can give, it reaches the animals in our care.
          </p>
        </div>
      </section>

      <form className="donate" onSubmit={onSubmit}>
        <fieldset>
          <legend>How much would you like to give?</legend>
          <div className="chips">
            {AMOUNTS.map(({ value, label }) => (
              <button
                key={value}
                type="button"
                className={!custom && amount === value ? "chip active" : "chip"}
                aria-pressed={!custom && amount === value}
                onClick={() => {
                  setAmount(value);
                  setCustom("");
                }}
              >
                {label}
              </button>
            ))}
          </div>
          <label className="inline">
            Or your own amount (JOD)
            <input
              inputMode="decimal"
              placeholder="e.g. 15.500"
              value={custom}
              onChange={(event) => setCustom(event.target.value)}
              maxLength={9}
            />
          </label>
        </fieldset>

        {earmarked ? (
          <p className="panel panel-warm earmark">
            <HeartIcon /> Your gift will go to <strong>{earmarked.name}</strong>'s care.{" "}
            <Link to="/donate">Give to all the animals instead</Link>
          </p>
        ) : (
          <fieldset>
            <legend>What should it help with?</legend>
            <div className="purposes" role="radiogroup">
              {PURPOSES.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  role="radio"
                  aria-checked={purpose === option.value}
                  className={purpose === option.value ? "purpose active" : "purpose"}
                  onClick={() => setPurpose(option.value)}
                >
                  {option.icon}
                  <strong>{option.title}</strong>
                  <span>{option.text}</span>
                </button>
              ))}
            </div>
          </fieldset>
        )}

        <label>
          <span>
            Your name <span className="muted">(optional, so we can thank you)</span>
          </span>
          <input name="donor_name" maxLength={120} autoComplete="name" />
        </label>

        {status === "error" && !unavailable && <p className="error">{error.message}</p>}
        {unavailable && (
          <p className="panel">
            Card donations are resting for a moment. You can still give by CliQ or bank transfer
            below, and thank you for your patience.
          </p>
        )}

        <button className="button button-big" type="submit" disabled={sending}>
          {sending ? "Taking you to secure payment…" : "Continue to secure payment"}
        </button>
        <p className="muted small">
          Card payments are handled by Stripe and charged in US dollars at the Central Bank of
          Jordan's fixed rate. We never see your card details.
        </p>
      </form>

      <OtherWays />

      <section className="panel where-it-goes" aria-labelledby="where-heading">
        <h2 id="where-heading">Where your gift goes</h2>
        <p>Caring for our animals costs around 60,000 US dollars a year, spent on:</p>
        <ul className="costs">
          <li>
            <ShieldIcon /> Vet services
          </li>
          <li>
            <HomeIcon /> Rent for the shelter
          </li>
          <li>
            <BowlIcon /> Caretakers' salaries
          </li>
          <li>
            <PawIcon /> Travel for animals adopted abroad
          </li>
        </ul>
        <p className="muted small">
          If 100 people give just 5 dinars, that's 500 dinars more for the animals than yesterday.
        </p>
        <p>
          Giving from abroad? You can also support us through our{" "}
          <a href={ORG.gofundme} target="_blank" rel="noopener noreferrer">
            GoFundMe campaign
          </a>
          .
        </p>
      </section>
    </>
  );
}

// CliQ and bank transfer, from the server's configuration. Hidden entirely if
// the rescue has not set them, so no placeholder can ever be mistaken for real.
function OtherWays() {
  const methods = useApi(() => api.offlineMethods(), []);
  if (methods.status !== "ok" || (!methods.data.cliq && !methods.data.bank)) return null;
  const { cliq, bank } = methods.data;
  return (
    <section className="panel other-ways" aria-labelledby="other-ways">
      <h2 id="other-ways">Other ways to give</h2>
      {cliq && (
        <p>
          <strong>CliQ:</strong> send to the alias <code>{cliq.alias}</code>
        </p>
      )}
      {bank && (
        <p>
          <strong>Bank transfer:</strong> {bank.account_name}
          {bank.bank_name && `, ${bank.bank_name}`}
          <br />
          IBAN <code>{bank.iban}</code>
        </p>
      )}
      <p className="muted small">Our team adds these gifts to our totals by hand once they arrive.</p>
    </section>
  );
}

// Where Stripe sends donors after paying. It deliberately reads nothing from
// the address bar: the gift is recorded only when Stripe confirms it to our
// server, never because someone landed on this page.
export function Thanks() {
  return (
    <section className="gentle-page thanks">
      <HeartIcon size={56} />
      <h1>Thank you, from all of us and all of them</h1>
      <p className="lead">
        Your kindness will become full bowls, warm beds and trips to the vet. Your gift appears
        in our totals once the payment is confirmed.
      </p>
      <p className="actions center">
        <Link className="button" to="/animals">
          Meet the animals you're helping
        </Link>
        <Link className="button button-soft" to="/">
          Back to home
        </Link>
      </p>
    </section>
  );
}
