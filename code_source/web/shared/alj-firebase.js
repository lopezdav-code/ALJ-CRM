/* Single Firebase initialisation for every page (PWA and office portal).
   Classic script (not a module): usable from pages through <script> as well as from
   alj-core.js. Must be loaded after the firebase-app/auth compat SDKs and after
   /runtime-config.js, which defines window.ALJ_RUNTIME (served by server.py).

   Firebase only signs the user in (ID token sent to the API); the pages never read or
   write Firestore (firestore.rules denies every client).

   - Production: the club's project configuration, nothing else.
   - Development (ALJ_RUNTIME.env === "dev"): "demo-alj" project connected to the
     local Auth emulator. No call to the real services. */
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

  /* Up to v22 the pages kept an offline copy of Firestore (SDK persistence): every member
     record, health and emergency data included, in IndexedDB. Deleted on every start, as a
     phone may come back after months; a no-op once the copy is gone. */
  const FIRESTORE_DB_PREFIX = "firestore/";
  const KNOWN_FIRESTORE_DBS = [
    "firestore/[DEFAULT]/" + FIREBASE_CONFIG.projectId + "/main",
    "firestore/[DEFAULT]/" + (runtime.projectId || "demo-alj") + "/main"
  ];

  function wipeFirestoreCache() {
    try {
      Object.keys(localStorage)
        .filter(k => k.startsWith("firestore_"))  // multi-tab bookkeeping of the old SDK
        .forEach(k => localStorage.removeItem(k));
    } catch (e) { /* storage unavailable (private mode) */ }
    if (!window.indexedDB) return;
    const drop = name => {
      try { indexedDB.deleteDatabase(name); } catch (e) { /* nothing to delete */ }
    };
    if (typeof indexedDB.databases === "function") {
      indexedDB.databases()
        .then(list => list.map(d => d.name).filter(n => n && n.startsWith(FIRESTORE_DB_PREFIX)).forEach(drop))
        .catch(() => KNOWN_FIRESTORE_DBS.forEach(drop));
    } else {
      KNOWN_FIRESTORE_DBS.forEach(drop);  // Firefox < 126: no databases()
    }
  }

  /* Idempotent: returns { auth } (compat). */
  function init() {
    if (services) return services;
    const config = isEmulator
      ? Object.assign({}, FIREBASE_CONFIG, { projectId: runtime.projectId })
      : FIREBASE_CONFIG;
    firebase.initializeApp(config);
    const auth = firebase.auth();
    if (isEmulator) {
      auth.useEmulator(runtime.authEmulator);
      showDevBanner();
    }
    wipeFirestoreCache();
    services = { auth };
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
