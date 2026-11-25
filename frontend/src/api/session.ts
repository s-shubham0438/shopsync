/**
 * Session signals shared by the HTTP client and the auth provider.
 *
 * - `sessionExpired`: the backend refused to refresh the session (signed out elsewhere,
 *   expired, or revoked). The UI must drop the cached user.
 * - `broadcastAuthChange`: tell other open tabs that this tab signed in or out, so they
 *   re-check /auth/me instead of showing a stale account for minutes.
 */
type Listener = () => void;

const expiredListeners = new Set<Listener>();

export function onSessionExpired(listener: Listener): () => void {
  expiredListeners.add(listener);
  return () => expiredListeners.delete(listener);
}

export function notifySessionExpired(): void {
  for (const listener of expiredListeners) listener();
}

const CHANNEL = "shopsync-auth";

function channel(): BroadcastChannel | null {
  return typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel(CHANNEL);
}

export function broadcastAuthChange(): void {
  const ch = channel();
  ch?.postMessage("changed");
  ch?.close();
}

export function onAuthChangeElsewhere(listener: Listener): () => void {
  const ch = channel();
  if (!ch) return () => {};
  ch.onmessage = () => listener();
  return () => ch.close();
}
