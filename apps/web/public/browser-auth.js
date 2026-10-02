"use strict";
// Only the short-lived, one-use login transaction is stored across the redirect.
// Access/ID/refresh tokens are never written to browser storage.
window.FinRiskLogin = (() => {
  const key = "finrisk.oidc.pending";
  let callback = null;
  if (location.pathname === "/auth/callback") {
    callback = new URLSearchParams(location.search);
    history.replaceState(null, "", "/");
  }
  const encode = (bytes) =>
    btoa(String.fromCharCode(...bytes))
      .replaceAll("+", "-")
      .replaceAll("/", "_")
      .replaceAll("=", "");
  const random = () => encode(crypto.getRandomValues(new Uint8Array(32)));
  const fingerprint = (config) => JSON.stringify(config);
  function clear() {
    try {
      sessionStorage.removeItem(key);
    } catch {
      // Signing out must still clear in-memory credentials when storage is blocked.
    }
  }
  async function start(config) {
    if (new URL(config.redirect_uri).origin !== location.origin)
      throw new Error(
        "Sign-in is configured for a different application address.",
      );
    if (!crypto.subtle)
      throw new Error(
        "Sign-in requires HTTPS or a localhost development address.",
      );
    const pending = {
      state: random(),
      nonce: random(),
      verifier: random(),
      created: Date.now(),
      config: fingerprint(config),
    };
    const challenge = encode(
      new Uint8Array(
        await crypto.subtle.digest(
          "SHA-256",
          new TextEncoder().encode(pending.verifier),
        ),
      ),
    );
    const url = new URL(config.authorization_url);
    url.search = new URLSearchParams({
      client_id: config.client_id,
      redirect_uri: config.redirect_uri,
      response_type: "code",
      response_mode: "query",
      scope: config.scope,
      state: pending.state,
      nonce: pending.nonce,
      code_challenge: challenge,
      code_challenge_method: "S256",
    });
    if (config.audience) url.searchParams.set("audience", config.audience);
    sessionStorage.setItem(key, JSON.stringify(pending));
    location.assign(url.href);
  }
  function consume(config) {
    if (!callback) return null;
    const params = callback;
    callback = null;
    const raw = sessionStorage.getItem(key);
    clear();
    let pending;
    try {
      pending = JSON.parse(raw);
    } catch {
      pending = null;
    }
    if (
      !config ||
      !pending ||
      pending.config !== fingerprint(config) ||
      typeof pending.created !== "number" ||
      Date.now() - pending.created > 600000 ||
      pending.created > Date.now() ||
      params.getAll("state").length !== 1 ||
      params.get("state") !== pending.state ||
      new URL(config.redirect_uri).origin !== location.origin ||
      (params.has("iss") &&
        (params.getAll("iss").length !== 1 ||
          params.get("iss") !== config.issuer))
    )
      throw new Error(
        "Sign-in expired or could not be verified. Please sign in again.",
      );
    if (params.has("error"))
      throw new Error("Sign-in was cancelled or refused. Please try again.");
    if (params.getAll("code").length !== 1 || !params.get("code"))
      throw new Error("The sign-in response is incomplete. Please try again.");
    return {
      code: params.get("code"),
      code_verifier: pending.verifier,
      nonce: pending.nonce,
    };
  }
  return { start, consume, clear };
})();
