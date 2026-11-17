// Where the website finds each service. Loaded before the app, by index.html.
//
// This copy is for local development: empty addresses mean "this same origin",
// and the Vite dev server forwards /api/... to each service (vite.config.js).
// The deployment pipeline overwrites this file with the real HTTPS addresses
// of the deployed services, so the addresses are configuration, never code.
window.ALRAHMEH_CONFIG = {
  animalsUrl: "",
  donationsUrl: "",
  enquiriesUrl: "",
};
