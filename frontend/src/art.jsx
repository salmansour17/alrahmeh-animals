import { Link as PillLink } from "react-router-dom";
import logoUrl from "./logo.png";

// Line icons and the drawn animal portraits used until a real photo exists.
// All inline SVG: no image files, no icon library, and they take the text
// colour, so they follow the palette in styles.css.

const line = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round",
  strokeLinejoin: "round",
};

function Icon({ children, size = 20, label }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      {...line}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      className="icon"
    >
      {children}
    </svg>
  );
}

export const PawIcon = (props) => (
  <Icon {...props}>
    <ellipse cx="12" cy="16" rx="4.2" ry="3.4" />
    <circle cx="6.2" cy="10.5" r="1.8" />
    <circle cx="9.6" cy="6.8" r="1.8" />
    <circle cx="14.4" cy="6.8" r="1.8" />
    <circle cx="17.8" cy="10.5" r="1.8" />
  </Icon>
);

export const HeartIcon = (props) => (
  <Icon {...props}>
    <path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z" />
  </Icon>
);

export const HomeIcon = (props) => (
  <Icon {...props}>
    <path d="M4 11.5 12 5l8 6.5" />
    <path d="M6 10v9h12v-9" />
    <path d="M10 19v-4.5h4V19" />
  </Icon>
);

export const CalendarIcon = (props) => (
  <Icon {...props}>
    <rect x="4" y="5.5" width="16" height="14" rx="3" />
    <path d="M4 10h16M9 3.5v4M15 3.5v4" />
  </Icon>
);

export const ShieldIcon = (props) => (
  <Icon {...props}>
    <path d="M12 3.5 19 6v5.5c0 4.3-3 7.4-7 9-4-1.6-7-4.7-7-9V6z" />
    <path d="m9 12 2.2 2.2L15.5 10" />
  </Icon>
);

export const BowlIcon = (props) => (
  <Icon {...props}>
    <path d="M3.5 12h17a8.5 6 0 0 1-17 0z" />
    <path d="M8 9.5c.8-1.2 2.2-1.8 4-1.8s3.2.6 4 1.8" />
  </Icon>
);

// --- drawn portraits ----------------------------------------------------------

function DogFace() {
  return (
    <g {...line} strokeWidth={2.4}>
      <path d="M40 46c-9-2-14 6-12 18 2 8 7 9 10 6" />
      <path d="M88 46c9-2 14 6 12 18-2 8-7 9-10 6" />
      <path d="M40 50c0-14 11-22 24-22s24 8 24 22v16c0 16-11 26-24 26S40 82 40 66z" />
      <circle cx="54" cy="58" r="2.6" fill="currentColor" />
      <circle cx="74" cy="58" r="2.6" fill="currentColor" />
      <path d="M58 70c2-2 10-2 12 0-1 4-3 6-6 6s-5-2-6-6z" fill="currentColor" />
      <path d="M64 76v5M57 82c3 3 11 3 14 0" />
    </g>
  );
}

function CatFace() {
  return (
    <g {...line} strokeWidth={2.4}>
      <path d="M38 52 36 26l18 13M90 52l2-26-18 13" />
      <path d="M38 54c0-12 11-17 26-17s26 5 26 17v10c0 16-12 26-26 26S38 80 38 64z" />
      <path d="M50 60c2-2 6-2 8 0M70 60c2-2 6-2 8 0" />
      <path d="M61 68h6l-3 3z" fill="currentColor" />
      <path d="M64 71v3c-2 3-6 3-8 1M64 74c2 3 6 3 8 1" />
      <path d="M44 70l-12-2M44 74l-12 3M84 70l12-2M84 74l12 3" strokeWidth={1.6} />
    </g>
  );
}

function OtherFace() {
  return (
    <g transform="translate(34 30) scale(2.5)" className="other-face">
      <PawIcon size={24} />
    </g>
  );
}

// A friendly drawing in the photo's place, chosen by species.
export function Portrait({ species, name }) {
  const kind = /cat|kitten/i.test(species) ? "cat" : /dog|pupp/i.test(species) ? "dog" : "other";
  return (
    <svg
      viewBox="0 0 128 112"
      className={`portrait portrait-${kind}`}
      role="img"
      aria-label={`Drawing of a ${kind === "other" ? "pet" : kind}, until we have a photo of ${name}`}
    >
      <path className="portrait-blob" d="M20 64C14 34 40 12 70 14s46 22 42 52-28 42-56 40S26 94 20 64z" />
      {kind === "cat" ? <CatFace /> : kind === "dog" ? <DogFace /> : <OtherFace />}
    </svg>
  );
}

// --- shared visual pieces -----------------------------------------------------

export const ArrowIcon = (props) => (
  <Icon {...props}>
    <path d="M5 12h13M13 6l6 6-6 6" />
  </Icon>
);

// A filled paw print, for decoration (scattered paws, the logo).
export function PawPrint({ size = 28, className = "" }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={`pawprint ${className}`} aria-hidden="true">
      <ellipse cx="12" cy="16.2" rx="4.6" ry="3.8" fill="currentColor" />
      <ellipse cx="5.6" cy="10.6" rx="2" ry="2.5" fill="currentColor" transform="rotate(-18 5.6 10.6)" />
      <ellipse cx="9.4" cy="6.4" rx="2" ry="2.6" fill="currentColor" transform="rotate(-6 9.4 6.4)" />
      <ellipse cx="14.6" cy="6.4" rx="2" ry="2.6" fill="currentColor" transform="rotate(6 14.6 6.4)" />
      <ellipse cx="18.4" cy="10.6" rx="2" ry="2.5" fill="currentColor" transform="rotate(18 18.4 10.6)" />
    </svg>
  );
}

export function Cloud({ className = "" }) {
  return (
    <svg viewBox="0 0 120 48" className={`cloud ${className}`} aria-hidden="true">
      <path
        d="M14 40c-8 0-12-6-9-11 2-4 7-5 11-3 1-9 10-15 19-12 4-8 15-11 23-5 6 4 7 10 6 13 6-4 15-2 18 5 7-2 14 3 13 9-1 3-4 4-7 4z"
        fill="#fff"
        stroke="#e9ded6"
        strokeWidth="1.5"
      />
    </svg>
  );
}

// A pill button or link with the round arrow chip from the designs. Pass `to`
// for a page link, `href` for an outside link, or neither for a button.
export function Pill({ children, to, href, tone = "orange", className = "", ...rest }) {
  const content = (
    <>
      <span>{children}</span>
      <span className="pill-chip" aria-hidden="true">
        <ArrowIcon size={16} />
      </span>
    </>
  );
  const classes = `pill pill-${tone} ${className}`;
  if (to) return <PillLink to={to} className={classes} {...rest}>{content}</PillLink>;
  if (href) return <a href={href} className={classes} {...rest}>{content}</a>;
  return <button className={classes} {...rest}>{content}</button>;
}

// A round glowing icon button, like the heart and paw floating on the profile.
export function Orb({ children, label, to, onClick, className = "" }) {
  if (to) {
    return (
      <PillLink to={to} className={`orb ${className}`} aria-label={label}>
        {children}
      </PillLink>
    );
  }
  return (
    <button type="button" className={`orb ${className}`} aria-label={label} onClick={onClick}>
      {children}
    </button>
  );
}

// The association's own logo (a dog and a cat held by two hands over a heart),
// recoloured blue with a burnt-orange heart to match this site.
export function Logo() {
  return (
    <span className="logo" aria-hidden="true">
      <img src={logoUrl} alt="" width="46" height="51" />
    </span>
  );
}
