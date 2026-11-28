// What the waking banner says, from the waker's state. Plain data, so it is
// tested without a browser; WakeBanner.jsx only draws it.
import { UNREACHABLE } from "./errors.js";

export const WAKING_TEXT = "The site is waking up, this can take up to a minute…";
export const TRY_AGAIN = "Try again";

export function bannerView({ waking, failed }) {
  if (waking > 0) return { visible: true, tone: "waking", text: WAKING_TEXT, action: null };
  if (failed) return { visible: true, tone: "failed", text: UNREACHABLE, action: TRY_AGAIN };
  return { visible: false, tone: null, text: "", action: null };
}
