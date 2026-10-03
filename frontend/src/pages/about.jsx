// About the rescue, and the contact and volunteer form.
//
// The story is the association's own, carried over from its previous website
// (alrahmehforanimals.org, "About us"), so the new site says everything the old
// one did. The contact form replaces the old WordPress form and the volunteer
// Google Form: messages are stored for staff in the enquiries domain.
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, useSubmit } from "../api.js";
import { BowlIcon, CalendarIcon, HeartIcon, HomeIcon, PawIcon, ShieldIcon } from "../art.jsx";
import { PRODUCTS } from "./shop.jsx";

export const ORG = {
  email: "admin@alrahmeh.org",
  facebook: "https://www.facebook.com/Rahmehforanimals/",
  instagram: "https://www.instagram.com/rahmehforanimals/",
  gofundme: "https://gf.me/u/ynkxwp",
};

const WAYS_TO_HELP = [
  {
    icon: <HomeIcon size={28} />,
    title: "Adopt",
    text: "Visit with our dogs who are ready for adoption. Come and meet your perfect match today!",
    link: "/animals?status=available",
    action: "Meet the animals",
  },
  {
    icon: <PawIcon size={28} />,
    title: "Foster",
    text: "Without fostering, there can be no rescue. Every year we save the lives of over 100 dogs.",
    link: "/animals?status=available",
    action: "Become a foster home",
  },
  {
    icon: <HeartIcon size={28} />,
    title: "Donate",
    text: "Every little bit counts! Your generous donation helps the animals most in need.",
    link: "/donate",
    action: "Give today",
  },
  {
    icon: <ShieldIcon size={28} />,
    title: "Volunteer",
    text: "Your time can help animals in ways we could never manage alone.",
    link: "/contact?topic=volunteer",
    action: "Volunteer with us",
  },
];

export function WaysToHelp() {
  return (
    <ul className="ways">
      {WAYS_TO_HELP.map((way) => (
        <li key={way.title} className="way">
          <span className="way-icon">{way.icon}</span>
          <h3>{way.title}</h3>
          <p>{way.text}</p>
          <Link to={way.link}>{way.action} →</Link>
        </li>
      ))}
    </ul>
  );
}

export function About() {
  return (
    <>
      <section className="hero">
        <div className="hero-text">
          <p className="eyebrow">
            <PawIcon size={18} /> Who we are
          </p>
          <h1>Al Rahmeh Association for Animals</h1>
          <p className="lead">
            An animal rescue charity in Jordan, spreading the word about the work we do and reaching
            out to people here in Jordan and beyond.
          </p>
        </div>
      </section>

      <section className="story" aria-labelledby="story-heading">
        <h2 id="story-heading" className="section-title">
          Our story
        </h2>
        <p>
          Al Rahmeh began when a group of animal lovers decided to build a much-needed organisation
          to counter the abuse and demonisation of the Canaan dog breed in Jordan, and of animals in
          general.
        </p>
        <p>
          There were, and still are, many campaigns pursuing the annihilation of stray dogs in
          Jordan, most of them of the ancient Canaan dog breed and village dogs. We stand up for
          them.
        </p>
        <ul className="facts story-facts">
          <li>
            <CalendarIcon /> Founded in January 2018
          </li>
          <li>
            <HomeIcon /> More than 300 dogs fostered since then, on a farm we rent in Madaba
          </li>
          <li>
            <HeartIcon /> Funded entirely by our members' continuing contributions
          </li>
        </ul>
        <p>
          Canaan dogs and village dogs are often overlooked in Jordan, and many find their families
          abroad, in the United States and Canada. We arrange those journeys as well as adoptions
          here at home.
        </p>
      </section>

      <section aria-labelledby="costs-heading">
        <h2 id="costs-heading" className="section-title">
          What it takes
        </h2>
        <p>
          Caring for our animals costs around 60,000 US dollars a year. Your gifts pay for:
        </p>
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
      <section className="hero">
        <div className="hero-text">
          <p className="eyebrow">
            <HeartIcon size={18} /> We'd love to hear from you
          </p>
          <h1>Contact us &amp; get involved</h1>
          <p className="lead">
            Questions, gift shop orders, or a few free hours for the animals: write to us and our
            team will reply by email.
          </p>
        </div>
      </section>

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
            <button className="button" type="submit" disabled={sending}>
              {sending ? "Sending…" : "Send message"}
            </button>
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
