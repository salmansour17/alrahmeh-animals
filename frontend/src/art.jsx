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
