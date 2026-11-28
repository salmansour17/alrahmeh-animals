// The only file that talks to the backend. Pages call these functions and
// never use fetch directly, so error handling, and waking a service that has
// scaled to zero (net/client.js), live in exactly one place.
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { createClient } from "./net/client.js";
import { ApiError, Cancelled } from "./net/errors.js";

export { ApiError };

// The one client for the whole site, so every page shares one wake loop per
// service and one banner (WakeBanner.jsx).
export const client = createClient({ fetch: (...args) => window.fetch(...args) });

// Each API path belongs to exactly one service (ADR-6). The addresses come from
// public/config.js, which the deployment overwrites; an empty address means
// this same origin, which is how local development works through Vite's proxy.
const config = window.ALRAHMEH_CONFIG ?? {};

// The address of the service that owns a path; "" means this same site.
function serviceOrigin(path) {
  if (path.startsWith("/api/donations")) return config.donationsUrl ?? "";
  if (path.startsWith("/api/enquiries")) return config.enquiriesUrl ?? "";
  // /api/animals and /api/requests both belong to the animals service.
  return config.animalsUrl ?? "";
}

const serviceUrl = (path) => serviceOrigin(path) + path;

// For URLs the services hand back for the browser to load itself, such as an
// animal's photo_url ("/api/animals/3/photo?v=..."): same rule as API calls.
export const assetUrl = (path) => (path && path.startsWith("/api/") ? serviceUrl(path) : path);

// A GET may be tried again while a service wakes; anything else is sent once
// (net/client.js). `unconfirmed` is what to say if a send's outcome is unknown.
function request(path, options = {}, extraHeaders = {}, { unconfirmed } = {}) {
  const headers = { Accept: "application/json", ...extraHeaders };
  if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const method = (options.method ?? "GET").toUpperCase();
  return client.send({
    origin: serviceOrigin(path),
    url: serviceUrl(path),
    init: { ...options, headers },
    idempotent: method === "GET",
    unconfirmed,
  });
}

const post = (path, data, headers, outcome) =>
  request(path, { method: "POST", body: JSON.stringify(data ?? {}) }, headers, outcome);

// For staff money records: where to look before sending again.
const CHECK_THE_LIST = {
  unconfirmed: "We could not confirm that went through. Check the latest donations list before recording it again.",
};

export const api = {
  listAnimals: (status) =>
    request(status ? `/api/animals?status=${encodeURIComponent(status)}` : "/api/animals"),
  getAnimal: (id) => request(`/api/animals/${encodeURIComponent(id)}`),
  placementStats: () => request("/api/animals/stats"),
  impact: () => request("/api/donations/impact"),
  offlineMethods: () => request("/api/donations/offline-methods"),
  // Amounts travel as strings ("25.000"), never as JavaScript numbers.
  startCheckout: (donation) => post("/api/donations/checkout", donation),
  askToAdoptOrFoster: (animalId, form) =>
    post(`/api/animals/${encodeURIComponent(animalId)}/requests`, form),
  sendEnquiry: (form) => post("/api/enquiries", form),
};

// The staff portal's client. The password lives only inside this closure, in
// memory: it is never written to localStorage or a cookie, and it is gone when
// the tab closes. It travels as an Authorization header that this code adds
// itself, which is why another website cannot make a staff member's browser
// send it (no cookie, so no cross-site request forgery).
export function staffApi(password) {
  const auth = { Authorization: `Basic ${toBase64(`staff:${password}`)}` };
  const get = (path) => request(path, {}, auth);
  const send = (path, data, outcome) => post(path, data, auth, outcome);
  const put = (path, data) => request(path, { method: "PUT", body: JSON.stringify(data) }, auth);
  const id = encodeURIComponent;
  return {
    checkSignIn: () => get("/api/requests?status=open"),
    requests: (status) => get(status ? `/api/requests?status=${id(status)}` : "/api/requests"),
    decide: (requestId, outcome) => send(`/api/requests/${id(requestId)}/decision`, { outcome }),
    enquiries: (handled) => get(`/api/enquiries?handled=${handled ? "true" : "false"}`),
    markHandled: (enquiryId) => send(`/api/enquiries/${id(enquiryId)}/handled`),
    donations: () => get("/api/donations?limit=20"),
    recordDonation: (donation) => send("/api/donations", donation, CHECK_THE_LIST),
    reverseDonation: (donationId, reason) =>
      send(`/api/donations/${id(donationId)}/reversal`, { reason }, CHECK_THE_LIST),
    offlineAdoptions: () => get("/api/animals/offline-adoptions"),
    recordOfflineAdoption: (entry) => send("/api/animals/offline-adoptions", entry),
    admit: (animal) => send("/api/animals", animal),
    staffAnimal: (animalId) => get(`/api/animals/${id(animalId)}/staff`),
    updateProfile: (animalId, profile) => put(`/api/animals/${id(animalId)}/profile`, profile),
    transition: (animalId, to) => send(`/api/animals/${id(animalId)}/transitions`, { to }),
    addMedicalRecord: (animalId, record) => send(`/api/animals/${id(animalId)}/medical-records`, record),
    uploadPhoto: (animalId, file) =>
      request(
        `/api/animals/${id(animalId)}/photo`,
        { method: "PUT", body: file },
        { ...auth, "Content-Type": file.type },
      ),
  };
}

// btoa() only accepts Latin-1, so encode as UTF-8 first: a password with
// Arabic letters must work too.
function toBase64(text) {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary);
}

// Load data for a page: { status: "loading" | "ok" | "error", data, error }.
// Leaving the page cancels its waiting (a service still waking keeps no loop
// alive for nobody), and a late answer is ignored. With keepPrevious, what is
// on screen stays there (marked refreshing) until the new data arrives. The
// banner's "Try again" loads everything again (retryToken).
export function useApi(load, deps, { keepPrevious = false } = {}) {
  const [state, setState] = useState({ status: "loading" });
  const { retryToken } = useSyncExternalStore(client.waker.subscribe, client.waker.getSnapshot);
  useEffect(() => {
    const controller = new AbortController();
    setState((previous) =>
      keepPrevious && previous.status === "ok" ? { ...previous, refreshing: true } : { status: "loading" },
    );
    client
      .withSignal(controller.signal, load)
      .then((data) => !controller.signal.aborted && setState({ status: "ok", data }))
      .catch((error) => {
        if (!controller.signal.aborted && !(error instanceof Cancelled)) setState({ status: "error", error });
      });
    return () => controller.abort();
  }, [...deps, retryToken]);
  return state;
}

// Submit a form once: { status: "idle" | "sending" | "done" | "error", error,
// submit }. Shared by the donate and request forms so neither re-implements
// double-click protection or error display. The server's own message is shown,
// because the server is the one that decides what is valid.
// After an error the server says may pass (error.retryable), retry() sends the
// same data again.
export function useSubmit(send) {
  const [state, setState] = useState({ status: "idle" });
  const last = useRef(undefined);
  const submit = useCallback(
    async (data) => {
      last.current = data;
      setState({ status: "sending" });
      try {
        const result = await send(data);
        setState({ status: "done", result });
        return result;
      } catch (error) {
        setState({ status: "error", error });
        return undefined;
      }
    },
    [send],
  );
  const retry = useCallback(() => submit(last.current), [submit]);
  return { ...state, submit, retry, sending: state.status === "sending" };
}
