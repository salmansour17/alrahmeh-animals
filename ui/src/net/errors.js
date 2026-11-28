// The one error type the website shows. Pages read `message`; a few read `code`.
export class ApiError extends Error {
  constructor(status, code, message, { retryable = false } = {}) {
    super(message);
    this.status = status; // 0 means no answer from the server at all
    this.code = code;
    // True when trying again later may work (the earmark check); the page then
    // offers a "Try again" button.
    this.retryable = retryable;
  }
}

// A loop stopped because the visitor moved to another page. Nobody is waiting
// for its result, so pages ignore it.
export class Cancelled extends Error {
  constructor() {
    super("cancelled");
    this.name = "Cancelled";
  }
}

export const UNREACHABLE = "Could not reach the server. Please try again.";
export const UNCONFIRMED = "We could not confirm that went through. Please check before sending again.";
