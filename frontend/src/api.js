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

async function request(path, options = {}) {
  const headers = { Accept: "application/json" };
  if (options.body) headers["Content-Type"] = "application/json";

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

const post = (path, data) => request(path, { method: "POST", body: JSON.stringify(data) });

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
};

// Load data for a page: { status: "loading" | "ok" | "error", data, error }.
// A late answer for a page the visitor has already left is ignored.
export function useApi(load, deps) {
  const [state, setState] = useState({ status: "loading" });
  useEffect(() => {
    let current = true;
    setState({ status: "loading" });
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
