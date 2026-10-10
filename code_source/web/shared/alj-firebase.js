/* Single Firebase initialisation for every page (PWA and office portal).
   Classic script (not a module): usable from pages through <script> as well as from
   alj-core.js. Must be loaded after the firebase-*-compat.js SDKs and after
   /runtime-config.js, which defines window.ALJ_RUNTIME (served by server.py).

   - Production: the club's project configuration, nothing else.
   - Development (ALJ_RUNTIME.env === "dev"): "demo-alj" project connected to the
     local Firebase emulator (Auth + Firestore). No call to the real services. */
(function () {
  "use strict";

  const FIREBASE_CONFIG = Object.freeze({
    apiKey: "AIzaSyDtwH7A6XokZZjUcyoL83gx9ZjyuN4IJoQ",
    authDomain: "smart-amplifier-510811-n6.firebaseapp.com",
    projectId: "smart-amplifier-510811-n6",
    storageBucket: "smart-amplifier-510811-n6.firebasestorage.app",
    messagingSenderId: "796572126711",
    appId: "1:796572126711:web:a827fd60c313ba2c46f2f2"
  });

  const runtime = window.ALJ_RUNTIME || { env: "prod" };
  const isEmulator = runtime.env === "dev";
  let services = null;

  function showDevBanner() {
    const add = () => {
      if (document.getElementById("alj-dev-banner")) return;
      const b = document.createElement("div");
      b.id = "alj-dev-banner";
      b.textContent = "DEV — Firebase emulator (" + runtime.projectId + "): fake data";
      b.setAttribute("role", "status");
      b.style.cssText = "position:fixed;left:0;right:0;bottom:0;z-index:99999;padding:4px 12px;"
        + "background:#b45309;color:#fff;font:600 12px/1.4 system-ui,sans-serif;text-align:center;"
        + "pointer-events:none;opacity:.92";
      document.body.appendChild(b);
    };
    if (document.body) add();
    else document.addEventListener("DOMContentLoaded", add);
  }

  /* Idempotent: returns { auth, db } (compat). */
  function init() {
    if (services) return services;
    const config = isEmulator
      ? Object.assign({}, FIREBASE_CONFIG, { projectId: runtime.projectId })
      : FIREBASE_CONFIG;
    firebase.initializeApp(config);
    const auth = firebase.auth();
    const db = firebase.firestore();
    if (isEmulator) {
      auth.useEmulator(runtime.authEmulator);
      const [host, port] = String(runtime.firestoreEmulator).split(":");
      db.useEmulator(host, Number(port));
      showDevBanner();
    }
    services = { auth, db };
    return services;
  }

  /* Sign-in through the Auth emulator: fake account picker (no real Google).
     Redirect rather than popup: sign-in can start without a click (?login=1). */
  function devLogin() {
    return init().auth.signInWithRedirect(new firebase.auth.GoogleAuthProvider());
  }
  /* Back from the emulator's account picker: true if a sign-in just completed. */
  async function completeDevLogin() {
    if (!isEmulator) return false;
    const result = await init().auth.getRedirectResult();
    return Boolean(result && result.user);
  }

  window.ALJFirebase = Object.freeze({ init, devLogin, completeDevLogin, isEmulator, env: runtime.env });
})();
