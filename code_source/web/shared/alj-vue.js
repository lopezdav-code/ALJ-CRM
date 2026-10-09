/* Choix « ordinateur / smartphone » pour les pages d'entrée de la PWA
   (/, /competitions, /index). Script classique, chargé dans <head> avant l'affichage.

   - Sur ordinateur (écran >= 1024 px avec souris, pas de téléphone), la page renvoie vers /bureau/.
   - ?vue=mobile : reste sur la PWA et mémorise le choix « mobile » (localStorage).
   - ?vue=pwa    : ouvre la PWA une fois, sans redirection (liens internes du bureau).
   - Pas de redirection pendant la connexion Google (?login=1, retour #access_token).
   - Un bouton 🖥️ ajouté dans l'en-tête permet de revenir au bureau (et oublie le choix). */
(function () {
  var MEMO = "alj_vue";
  var BUREAU = "/bureau/";
  var params = new URLSearchParams(location.search);
  var vue = params.get("vue");

  function storage() { try { return window.localStorage; } catch (e) { return null; } }
  function memoise(value) {
    var s = storage();
    try { if (!s) return; if (value) s.setItem(MEMO, value); else s.removeItem(MEMO); } catch (e) {}
  }
  function memorised() {
    var s = storage();
    try { return s ? s.getItem(MEMO) : null; } catch (e) { return null; }
  }
  function isDesktop() {
    return !!(window.matchMedia && window.matchMedia("(min-width: 1024px) and (any-pointer: fine)").matches);
  }

  if (vue === "mobile") memoise("mobile");

  var connexion = params.get("login") === "1" || /access_token=/.test(location.hash);
  var pwaDemandee = vue === "mobile" || vue === "pwa";
  if (isDesktop() && !connexion && !pwaDemandee && memorised() !== "mobile") {
    location.replace(BUREAU);
    return;
  }

  document.addEventListener("DOMContentLoaded", function () {
    if (!isDesktop()) return;
    var header = document.querySelector("header");
    if (!header) return;
    var lien = document.createElement("a");
    lien.href = BUREAU;
    lien.title = "Passer à la version ordinateur (bureau)";
    lien.textContent = "🖥️";
    lien.setAttribute("style", "display:inline-flex;align-items:center;justify-content:center;" +
      "min-width:40px;height:40px;border-radius:10px;background:rgba(255,255,255,.12);" +
      "color:#F8FAFC;font-size:17px;text-decoration:none;padding:0 10px;");
    lien.addEventListener("click", function () { memoise(null); });
    header.appendChild(lien);
  });
})();
