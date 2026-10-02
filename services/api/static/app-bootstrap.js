"use strict";

// Let Next finish hydrating the static shell before the API controller starts
// updating live tables and session state.
window.addEventListener("load", () => {
  window.setTimeout(() => {
    const auth = document.createElement("script");
    auth.src = "/browser-auth.js";
    auth.onload = () => {
      const runtime = document.createElement("script");
      runtime.src = "/app-runtime.js";
      document.head.append(runtime);
    };
    document.head.append(auth);
  }, 100);
});
