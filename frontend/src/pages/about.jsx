// About the rescue, and the contact and volunteer form.
//
// The story is the association's own, carried over from its previous website
// (alrahmehforanimals.org, "About us"), so the new site says everything the old
// one did. The contact form replaces the old WordPress form and the volunteer
// Google Form: messages are stored for staff in the enquiries domain.
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, useSubmit } from "../api.js";
import { BowlIcon, HeartIcon, HomeIcon, PawIcon, PawPrint, Pill, ShieldIcon } from "../art.jsx";
import { PRODUCTS } from "./shop.jsx";

export const ORG = {
  email: "admin@alrahmeh.org",
  facebook: "https://www.facebook.com/Rahmehforanimals/",
  instagram: "https://www.instagram.com/rahmehforanimals/",
  gofundme: "https://gf.me/u/ynkxwp",
};

const WAYS_TO_HELP = [
  {
    icon: <HomeIcon size={72} />,
    title: "Adopt",
    text: "Visit with our dogs who are ready for adoption. Come and meet your perfect match today!",
    link: "/animals?status=available",
    action: "Meet the animals",
  },
  {
    icon: <PawIcon size={72} />,
    title: "Foster",
    text: "Without fostering, there can be no rescue. Every year we save the lives of over 100 dogs.",
    link: "/animals?status=available",
    action: "Become a foster home",
  },
  {
    icon: <HeartIcon size={72} />,
    title: "Donate",
    text: "Every little bit counts! Your generous donation helps the animals most in need.",
    link: "/donate",
    action: "Give today",
  },
  {
    icon: <ShieldIcon size={72} />,
    title: "Volunteer",
    text: "Your time can help animals in ways we could never manage alone.",
    link: "/contact?topic=volunteer",
    action: "Volunteer with us",
  },
];

export function WaysToHelp() {
  return (
    <ul className="cards">
      {WAYS_TO_HELP.map((way) => (
        <li key={way.title}>
          <Link to={way.link} className="fcard">
            <div className="fcard-top">{way.icon}</div>
            <div className="fcard-panel">
              <h3>{way.title}</h3>
              <p>{way.text}</p>
              <span className="fcard-link">{way.action}</span>
            </div>
          </Link>
        </li>
      ))}
    </ul>
  );
}

export function PageHead({ eyebrow, title, children }) {
  return (
    <section className="page-head">
      <PawPrint size={44} className="paw-1" />
      <PawPrint size={36} className="paw-2" />
      <p className="eyebrow">{eyebrow}</p>
      <h1>{title}</h1>
      <p className="lead">{children}</p>
    </section>
  );
}

export function About() {
  return (
    <>
      <PageHead eyebrow="About us · who we are" title="Al Rahmeh Association for Animals">
        An animal rescue charity in Jordan, spreading the word about the work we do and reaching
        out to people here in Jordan and beyond.
      </PageHead>

      <section className="story" aria-labelledby="story-heading">
        <div>
          <h2 id="story-heading" className="section-title">
            Our story
          </h2>
          <p>
            Al Rahmeh began when a group of animal lovers decided to build a much-needed
            organisation to counter the abuse and demonisation of the Canaan dog breed in Jordan,
            and of animals in general.
          </p>
          <p>
            There were, and still are, many campaigns pursuing the annihilation of stray dogs in
            Jordan, most of them of the ancient Canaan dog breed and village dogs. We stand up for
            them.
          </p>
          <p>
            Canaan dogs and village dogs are often overlooked in Jordan, and many find their
            families abroad, in the United States and Canada. We arrange those journeys as well as
            adoptions here at home.
          </p>
        </div>
        <ul className="story-facts panel">
          <li>
            <span className="fact-label">Founded</span>
            <span className="fact-value">January 2018</span>
          </li>
          <li>
            <span className="fact-label">Dogs fostered since</span>
            <span className="fact-value">More than 300</span>
          </li>
          <li>
            <span className="fact-label">Our shelter</span>
            <span className="fact-value">A rented farm in Madaba</span>
          </li>
          <li>
            <span className="fact-label">Funded by</span>
            <span className="fact-value">Our members' contributions</span>
          </li>
        </ul>
      </section>

      <section aria-labelledby="costs-heading">
        <h2 id="costs-heading" className="section-title">
          What it takes
        </h2>
        <p className="lead">Caring for our animals costs around 60,000 US dollars a year. Your gifts pay for:</p>
        <ul className="costs" style={{ marginTop: "1rem" }}>
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
        <Pill to="/donate">Help with a gift</Pill>
      </section>

      <section aria-labelledby="help-heading">
        <h2 id="help-heading" className="section-title">
          Want to get involved?
        </h2>
        <WaysToHelp />
      </section>
    </>
  );
}

const TOPICS = [
  { value: "volunteer", label: "I'd like to volunteer" },
  { value: "question", label: "I have a question" },
  { value: "shop_order", label: "A gift shop order" },
  { value: "other", label: "Something else" },
];

export function Contact() {
  const [params] = useSearchParams();
  const requested = params.get("topic");
  const initialTopic = TOPICS.some((t) => t.value === requested) ? requested : "question";
  // A product named in the address bar is only used to look it up in our own
  // catalogue; the text shown always comes from the catalogue, never the URL.
  const product = PRODUCTS.find((p) => p.slug === params.get("product"));
  const [topic, setTopic] = useState(product ? "shop_order" : initialTopic);
  const { status, error, sending, submit } = useSubmit(api.sendEnquiry);

  function onSubmit(event) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    submit({
      topic,
      name: fields.get("name"),
      email: fields.get("email"),
      subject: fields.get("subject"),
      message: fields.get("message"),
      website: fields.get("website"),
    });
  }

  return (
    <>
      <PageHead eyebrow="We'd love to hear from you" title="Contact us & get involved">
        Questions, gift shop orders, or a few free hours for the animals: write to us and our team
        will reply by email.
      </PageHead>

      <div className="contact-grid">
        {status === "done" ? (
          <section className="panel panel-warm" aria-live="polite">
            <h2>
              <HeartIcon /> Thank you!
            </h2>
            <p>Your message is with our team. We read every one and reply by email.</p>
          </section>
        ) : (
          <form className="donate form" onSubmit={onSubmit}>
            <fieldset>
              <legend>What is it about?</legend>
              <div className="chips" role="radiogroup">
                {TOPICS.map((t) => (
                  <button
                    key={t.value}
                    type="button"
                    role="radio"
                    aria-checked={topic === t.value}
                    className={topic === t.value ? "chip active" : "chip"}
                    onClick={() => setTopic(t.value)}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            </fieldset>
            <label>
              Your name
              <input name="name" required maxLength={120} autoComplete="name" />
            </label>
            <label>
              Your email
              <input name="email" type="email" required maxLength={254} autoComplete="email" />
            </label>
            <label>
              Subject
              <input
                name="subject"
                required
                maxLength={150}
                defaultValue={product ? `Order: ${product.name}` : topic === "volunteer" ? "Volunteering" : ""}
              />
            </label>
            <label>
              Message
              <textarea
                name="message"
                rows={6}
                required
                maxLength={4000}
                placeholder={
                  product
                    ? "Size, colour, how many, and where you are, so we can arrange collection or delivery."
                    : topic === "volunteer"
                      ? "Tell us when you're free and how you'd like to help."
                      : ""
                }
              />
            </label>
            {/* The bot trap: invisible, unreachable by keyboard, hidden from screen readers. */}
            <div className="trap" aria-hidden="true">
              <label>
                Website
                <input name="website" tabIndex={-1} autoComplete="off" />
              </label>
            </div>
            {status === "error" && <p className="error">{error.message}</p>}
            <Pill type="submit" disabled={sending}>
              {sending ? "Sending…" : "Send message"}
            </Pill>
            <p className="muted small">Only our team sees your details, and only to reply to you.</p>
          </form>
        )}

        <aside className="panel">
          <h2>Find us online</h2>
          <ul className="links">
            <li>
              Email: <a href={`mailto:${ORG.email}`}>{ORG.email}</a>
            </li>
            <li>
              <a href={ORG.facebook} target="_blank" rel="noopener noreferrer">
                Facebook
              </a>
            </li>
            <li>
              <a href={ORG.instagram} target="_blank" rel="noopener noreferrer">
                Instagram
              </a>
              <span className="muted">: see more of our animals, and save a life</span>
            </li>
          </ul>
        </aside>
      </div>
    </>
  );
}
