// The "waking up" notice (brief section 7.5). One for the whole site, however
// many requests are waiting: the waker counts them (net/waker.js).
//
// It floats above the page instead of pushing it down, so nothing jumps when it
// appears. The live region is always in the page and only its text changes,
// which is what lets screen readers announce it.
import { useSyncExternalStore } from "react";
import { client } from "./api.js";
import { bannerView } from "./net/banner.js";

export function WakeBanner() {
  const { waker } = client;
  const state = useSyncExternalStore(waker.subscribe, waker.getSnapshot);
  const view = bannerView(state);
  return (
    <div className={`wake-banner${view.visible ? ` is-${view.tone}` : ""}`} role="status" aria-live="polite">
      {view.visible && (
        <p className="wake-banner-box">
          {view.tone === "waking" && <span className="wake-spinner" aria-hidden="true" />}
          <span>{view.text}</span>
          {view.action && (
            <button type="button" className="button button-small" onClick={waker.retry}>
              {view.action}
            </button>
          )}
        </p>
      )}
    </div>
  );
}
