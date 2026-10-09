/* Mise en page commune des pages « bureau » (ordinateur) : menu latéral, en-tête,
   contrôle de connexion et de rôle (coach / administrateur). Chaque page appelle
   startBureau() puis remplit la zone #content dans onReady(). */
import {
  initFirebase, login, logout, roleFor, isStaff,
  checkWebVersion, registerServiceWorker, WEB_VERSION
} from "/static-web/alj-core.js";

const NAV = [
  { id: "accueil", label: "🏠 Accueil", href: "/bureau/" },
  { id: "adherents", label: "👥 Adhérents", href: "/bureau/adherents" },
  { id: "outils", label: "🛠️ Outils", href: "/bureau/outils" },
  { id: "competitions", label: "🏆 Compétitions", href: "/competitions?vue=pwa" }
];
const ROLE_LABEL = {
  admin: "🛡️ Administrateur", coach: "🏃 Coach", lecture: "👁️ Lecture seule", aucun: "⛔ Non autorisé"
};

const esc = s => (s == null ? "" : String(s)).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const $ = id => document.getElementById(id);

/**
 * @param {{page: string, title: string, onReady: function({user, role, isAdmin, claims}): void}} opts
 * @returns {{setStatus: function(string): void}}
 */
export function startBureau({ page, title, onReady }) {
  $("shell").innerHTML = `
    <div class="app">
      <aside class="side">
        <div class="brand">
          <b>🧗 ALJ Escalade</b>
          <span>Bureau · <span class="web-version" id="web-version">v${esc(WEB_VERSION)}</span></span>
        </div>
        <nav>
          ${NAV.map(n => `<a href="${n.href}" data-page="${n.id}"${n.id === page ? ' class="active" aria-current="page"' : ""}>${n.label}</a>`).join("")}
        </nav>
        <div class="side-foot">
          <a class="mobile-link" href="/competitions?vue=mobile">📱 Version mobile</a>
          <div class="who" id="who">Vérification de la connexion…</div>
          <button class="btn btn-muted btn-mini" id="logout-btn" hidden>🚪 Se déconnecter</button>
        </div>
      </aside>
      <div class="main">
        <header class="top">
          <h1>${esc(title)}</h1>
          <span class="sync" id="sync-info"></span>
        </header>
        <section class="gate card" id="gate" hidden></section>
        <div id="content" hidden></div>
      </div>
    </div>`;

  const { auth } = initFirebase();
  const setStatus = msg => { $("sync-info").textContent = msg; };
  const showGate = html => { $("gate").innerHTML = html; $("gate").hidden = false; };

  $("logout-btn").addEventListener("click", logout);
  $("gate").addEventListener("click", e => {
    const id = e.target && e.target.id;
    if (id === "gate-login") login();
    if (id === "gate-logout") logout();
  });
  checkWebVersion($("web-version"));
  registerServiceWorker();

  let readyUid = null;
  auth.onAuthStateChanged(async user => {
    if (!user) {
      readyUid = null;
      $("who").textContent = "Non connecté";
      $("logout-btn").hidden = true;
      setStatus("");
      $("content").hidden = true;
      showGate(`<h2>🔐 Connexion</h2>
        <p>Le bureau est réservé aux coachs et administrateurs du club. Connectez-vous avec votre compte Google.</p>
        <button class="btn btn-primary" id="gate-login">🔑 Se connecter avec Google</button>`);
      return;
    }

    let claims = {};
    try { claims = ((await user.getIdTokenResult()) || {}).claims || {}; } catch (e) { /* jetons sans claims */ }
    const role = roleFor(user, claims);
    $("who").textContent = (user.email || "(compte sans e-mail)") + " · " + (ROLE_LABEL[role] || "");
    $("logout-btn").hidden = false;

    if (!isStaff(role)) {
      readyUid = null;
      setStatus("");
      $("content").hidden = true;
      showGate(`<h2>⛔ Accès réservé</h2>
        <p>Ce compte n'est pas autorisé à consulter le bureau. Déconnectez-vous et utilisez un compte coach ou administrateur.</p>
        <button class="btn btn-muted" id="gate-logout">🚪 Se déconnecter</button>`);
      return;
    }

    $("gate").hidden = true;
    $("content").hidden = false;
    if (readyUid !== user.uid) {
      readyUid = user.uid;
      onReady({ user, role, isAdmin: role === "admin", claims });
    }
  });

  return { setStatus };
}
