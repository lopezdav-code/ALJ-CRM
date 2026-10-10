/* Initialisation Firebase unique pour toutes les pages (PWA et portail bureau).
   Script classique (pas un module) : utilisable par les pages en <script> comme par
   alj-core.js. Doit être chargé après les SDK firebase-*-compat.js et après
   /runtime-config.js, qui définit window.ALJ_RUNTIME (servi par server.py).

   - Production : configuration du projet du club, rien d'autre.
   - Développement (ALJ_RUNTIME.env === "dev") : projet « demo-alj » branché sur
     l'émulateur Firebase local (Auth + Firestore). Aucun appel aux services réels. */
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
      b.textContent = "DEV — émulateur Firebase (" + runtime.projectId + ") : données fictives";
      b.setAttribute("role", "status");
      b.style.cssText = "position:fixed;left:0;right:0;bottom:0;z-index:99999;padding:4px 12px;"
        + "background:#b45309;color:#fff;font:600 12px/1.4 system-ui,sans-serif;text-align:center;"
        + "pointer-events:none;opacity:.92";
      document.body.appendChild(b);
    };
    if (document.body) add();
    else document.addEventListener("DOMContentLoaded", add);
  }

  /* Idempotent : renvoie { auth, db } (compat). */
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

  /* Connexion via l'émulateur Auth : sélecteur de comptes fictifs (aucun Google réel).
     Redirection plutôt que popup : la connexion peut être lancée sans clic (?login=1). */
  function devLogin() {
    return init().auth.signInWithRedirect(new firebase.auth.GoogleAuthProvider());
  }
  /* Retour du sélecteur de l'émulateur : vrai si une connexion vient d'aboutir. */
  async function completeDevLogin() {
    if (!isEmulator) return false;
    const result = await init().auth.getRedirectResult();
    return Boolean(result && result.user);
  }

  window.ALJFirebase = Object.freeze({ init, devLogin, completeDevLogin, isEmulator, env: runtime.env });
})();
