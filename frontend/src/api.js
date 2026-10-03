// The only file that talks to the backend. Pages call these functions and
// never use fetch directly, so error handling lives in exactly one place.
import { useCallback, useEffect, useState } from "react";

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status; // 0 means the server could not be reached at all
    this.code = code;
  }
}

async function request(path, options = {}, extraHeaders = {}) {
  const headers = { Accept: "application/json", ...extraHeaders };
  if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";

  let response;
  try {
    response = await fetch(path, { ...options, headers });
  } catch {
    throw new ApiError(0, "network_error", "Could not reach the server. Please try again.");
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(
      response.status,
      body?.error ?? "error",
      body?.detail ?? `Something went wrong (${response.status}).`,
    );
  }
  return body;
}

const post = (path, data, headers) =>
  request(path, { method: "POST", body: JSON.stringify(data ?? {}) }, headers);

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
  const send = (path, data) => post(path, data, auth);
  const put = (path, data) => request(path, { method: "PUT", body: JSON.stringify(data) }, auth);
  const id = encodeURIComponent;
  return {
    checkSignIn: () => get("/api/requests?status=open"),
    requests: (status) => get(status ? `/api/requests?status=${id(status)}` : "/api/requests"),
    decide: (requestId, outcome) => send(`/api/requests/${id(requestId)}/decision`, { outcome }),
    enquiries: (handled) => get(`/api/enquiries?handled=${handled ? "true" : "false"}`),
    markHandled: (enquiryId) => send(`/api/enquiries/${id(enquiryId)}/handled`),
    donations: () => get("/api/donations?limit=20"),
    recordDonation: (donation) => send("/api/donations", donation),
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
// A late answer for a page the visitor has already left is ignored. With
// keepPrevious, what is on screen stays there (marked refreshing) until the
// new data arrives, instead of flashing a loading state in between.
export function useApi(load, deps, { keepPrevious = false } = {}) {
  const [state, setState] = useState({ status: "loading" });
  useEffect(() => {
    let current = true;
    setState((previous) =>
      keepPrevious && previous.status === "ok" ? { ...previous, refreshing: true } : { status: "loading" },
    );
    load()
      .then((data) => current && setState({ status: "ok", data }))
      .catch((error) => current && setState({ status: "error", error }));
    return () => {
      current = false;
    };
  }, deps);
  return state;
}

// Submit a form once: { status: "idle" | "sending" | "done" | "error", error,
// submit }. Shared by the donate and request forms so neither re-implements
// double-click protection or error display. The server's own message is shown,
// because the server is the one that decides what is valid.
export function useSubmit(send) {
  const [state, setState] = useState({ status: "idle" });
  const submit = useCallback(
    async (data) => {
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
  return { ...state, submit, sending: state.status === "sending" };
}
