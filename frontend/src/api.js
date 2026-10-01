// The only file that talks to the backend. Pages call these functions and
// never use fetch directly, so error handling lives in exactly one place.
import { useEffect, useState } from "react";

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

export const api = {
  listAnimals: (status) =>
    request(status ? `/api/animals?status=${encodeURIComponent(status)}` : "/api/animals"),
  getAnimal: (id) => request(`/api/animals/${encodeURIComponent(id)}`),
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
