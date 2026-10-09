/* Socle commun des pages « bureau » (ordinateur) : Firebase, connexion Google,
   rôles, appels à l'API avec jeton, version de la page et mise à jour du cache.
   Ne contient aucune donnée d'adhérent. Les rôles sont des miroirs de
   firestore.rules et de src/infrastructure/api_auth.py (un test vérifie les listes). */

export const FIREBASE_CONFIG = {
  apiKey: "AIzaSyDtwH7A6XokZZjUcyoL83gx9ZjyuN4IJoQ",
  authDomain: "smart-amplifier-510811-n6.firebaseapp.com",
  projectId: "smart-amplifier-510811-n6",
  storageBucket: "smart-amplifier-510811-n6.firebasestorage.app",
  messagingSenderId: "796572126711",
  appId: "1:796572126711:web:a827fd60c313ba2c46f2f2"
};

/* Mêmes listes que competitions.html / index.html. COACH_EMAILS contient aussi les
   administrateurs (convention des pages PWA). */
export const ADMIN_DOMAIN = "alj-escalade.fr";
export const ADMIN_EMAILS = [
  "lopez.dav@gmail.com"
];
export const COACH_EMAILS = [
  "lopez.dav@gmail.com",
  "stephane.loridant@orange.fr"
];
export const READONLY_EMAILS = [
  "muah.did@gmail.com",
  "clement.dlf78@gmail.com",
  "delphine0910@gmail.com"
];

export const COMPETITIONS_URL = "/competitions";
export const WEB_VERSION = (document.querySelector('meta[name="alj-web-version"]') || {}).content || "?";

/* ===================== Firebase ===================== */
let firebaseReady = false;
export function initFirebase() {
  if (!firebaseReady) {
    firebase.initializeApp(FIREBASE_CONFIG);
    firebaseReady = true;
  }
  return { auth: firebase.auth(), db: firebase.firestore() };
}

/* ===================== Rôles ===================== */
/* Rôle d'affichage : le serveur et Firestore restent les seuls juges des droits. */
export function roleFor(user, claims) {
  if (!user) return "anonyme";
  const c = claims || {};
  const email = String(user.email || "").toLowerCase().trim();
  if (c.admin === true || email.endsWith("@" + ADMIN_DOMAIN) || ADMIN_EMAILS.includes(email)) return "admin";
  if (c.coach === true || COACH_EMAILS.includes(email)) return "coach";
  if (c.readonly === true || READONLY_EMAILS.includes(email)) return "lecture";
  return "aucun";
}
export function isStaff(role) {
  return role === "admin" || role === "coach";
}

/* ===================== Connexion ===================== */
/* La connexion Google passe par la page des compétitions (même origine, URI de
   redirection OAuth déjà autorisée), qui renvoie ensuite à la page d'origine. */
export function login() {
  sessionStorage.setItem("alj_after_login", location.pathname + location.search);
  location.assign(COMPETITIONS_URL + "?login=1");
}
export function logout() {
  firebase.auth().signOut().catch(() => {});
}

/* ===================== API Cloud Run ===================== */
/* Jeton d'identité Firebase joint à chaque appel ; renouvelé une fois en cas de 401. */
export async function apiFetch(url, opts = {}) {
  const send = async (forceRefresh) => {
    const headers = Object.assign({}, opts.headers || {});
    const user = firebase.auth().currentUser;
    if (user) headers["Authorization"] = "Bearer " + await user.getIdToken(forceRefresh);
    return fetch(url, Object.assign({}, opts, { headers }));
  };
  let res = await send(false);
  if (res.status === 401 && firebase.auth().currentUser) res = await send(true);
  return res;
}

/* ===================== Version et cache ===================== */
/* Même numéro que <meta name="alj-web-version"> et que CACHE_NAME de sw.js. */
export async function checkWebVersion(badge) {
  if (!badge) return;
  badge.textContent = "v" + WEB_VERSION;
  badge.title = "Version de la page : v" + WEB_VERSION;
  try {
    const r = await fetch("/api/web-version", { cache: "no-store" });
    if (!r.ok) return;
    const online = String((await r.json()).web_version || "");
    if (online && online !== WEB_VERSION) {
      badge.textContent = "v" + WEB_VERSION + " ⬆ v" + online;
      badge.title = "Une nouvelle version est en ligne : toucher pour mettre à jour";
      badge.classList.add("outdated");
      badge.onclick = forceWebUpdate;
    } else {
      badge.title = "Version de la page : v" + WEB_VERSION + " (à jour)";
    }
  } catch (e) { /* hors-ligne */ }
}
export async function forceWebUpdate() {
  try {
    if ("serviceWorker" in navigator) {
      const regs = await navigator.serviceWorker.getRegistrations();
      await Promise.all(regs.map(r => r.unregister()));
    }
    if (window.caches) {
      const keys = await caches.keys();
      await Promise.all(keys.map(k => caches.delete(k)));
    }
  } catch (e) { console.warn("Mise à jour forcée :", e); }
  location.reload();
}
export function registerServiceWorker() {
  if ("serviceWorker" in navigator && !/github\.io$/.test(location.hostname)) {
    navigator.serviceWorker.register("/sw.js").catch(err => console.warn("Service Worker :", err));
  }
}
