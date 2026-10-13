/* Display helpers of the member pages of the bureau (statuses, keys, dates, phone links).
   The member list itself comes from the API (alj-members-sync.js, domain/member_view.py). */

export const STATUS_MAP = {
  "processed": "Traité", "validated": "Validé", "validé": "Validé", "valide": "Validé",
  "terminé": "Terminé", "termine": "Terminé", "annulé": "Annulé", "annule": "Annulé",
  "canceled": "Annulé", "en cours": "En cours"
};

export const STATUS_COLORS = {
  "Validé": "#16A34A",
  "Traité": "#2563EB",
  "Terminé": "#8B5CF6",
  "En cours": "#D97706",
  "Annulé": "#DC2626"
};

export function normKey(s) {
  return String(s || "").trim().toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
}

export function normalizeStatus(s) {
  const r = String(s || "").trim();
  return STATUS_MAP[r.toLowerCase()] || r;
}

export function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d) ? String(iso) : d.toLocaleString("fr-FR", {
    day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit"
  });
}

export function telHref(phone) {
  return String(phone || "").replace(/[^\d+]/g, "");
}

/**
 * Formate un nom de famille en majuscules (norme française).
 * Ex: "dupont" -> "DUPONT", "de lima ferreira" -> "DE LIMA FERREIRA"
 */
export function fmtLastName(name) {
  if (!name) return "";
  return String(name).trim().toUpperCase();
}

/**
 * Formate un prénom en casse nom propre (1ère lettre en majuscule, reste en minuscule),
 * en respectant les prénoms composés avec tiret ou espace.
 * Ex: "JEAN-PIERRE" -> "Jean-Pierre", "marie-claire" -> "Marie-Claire", "ERIC" -> "Eric"
 */
export function fmtFirstName(name) {
  if (!name) return "";
  const s = String(name).trim();
  return s.toLowerCase().replace(/(^|[\s\-'’])([a-zà-öø-ÿ])/gi, (_, sep, letter) => sep + letter.toUpperCase());
}

/**
 * Formate un nom de ville (1ère lettre en majuscule, reste en minuscule),
 * en gérant les noms composés (tirets, espaces, apostrophes) et particules françaises.
 * Ex: "JONAGE" -> "Jonage", "CHARVIEU-CHAVAGNEUX" -> "Charvieu-Chavagneux", "VILLETTE D'ANTHON" -> "Villette d'Anthon"
 */
export function fmtCity(city) {
  if (!city) return "";
  const s = String(city).trim().replace(/[’‘]/g, "'").replace(/\s+/g, " ");
  const particles = new Set(["de", "des", "du", "d", "en", "sur", "sous", "les", "la", "le"]);

  const capWord = (w, isFirst = false) => {
    const parts = w.split(/(')/);
    return parts.map(p => {
      if (p === "'") return "'";
      if (!isFirst && particles.has(p.toLowerCase())) return p.toLowerCase();
      return p.charAt(0).toUpperCase() + p.slice(1).toLowerCase();
    }).join("");
  };

  const tokens = s.split(/([-\s])/);
  let wordIdx = 0;
  return tokens.map(tok => {
    if (tok === "-" || tok === " " || /^\s+$/.test(tok)) {
      return tok;
    }
    const res = capWord(tok, wordIdx === 0);
    wordIdx++;
    return res;
  }).join("");
}

/**
 * Formate un numéro de téléphone avec un espace entre chaque paire de chiffres.
 * Ex: "0601821825" -> "06 01 82 18 25", "+33619984329" -> "06 19 98 43 29"
 */
export function fmtPhone(phone) {
  if (!phone) return "";
  let s = String(phone).trim();
  // Remplacement de l'indicatif international +33 ou 0033 par le 0 national
  s = s.replace(/^(\+33|0033)\s*/, "0");
  const digits = s.replace(/\D/g, "");
  let cleanDigits = digits;
  if (digits.length === 9 && /^[1-9]/.test(digits)) {
    cleanDigits = "0" + digits;
  }
  if (cleanDigits.length === 10) {
    return cleanDigits.replace(/(\d{2})(?=\d)/g, "$1 ");
  }
  if (cleanDigits.length > 4 && cleanDigits.length % 2 === 0) {
    return cleanDigits.replace(/(\d{2})(?=\d)/g, "$1 ");
  }
  return s;
}

/**
 * Retourne la liste des diplômes et badges obtenus par un adhérent.
 * Badge rouge (🔴), Autonomie bloc (🧗), Passeport Orange (🟠).
 * @param {Record<string, any>} m
 * @returns {Array<{ type: string, label: string, icon: string }>}
 */
export function getMemberDiplomes(m) {
  const items = [];
  if (!m) return items;
  const br = String(m.badge_rouge || "").trim().toLowerCase();
  if (br === "oui" || br === "x" || br === "true" || br === "1") {
    items.push({ type: "badge_rouge", label: "Badge rouge diff", icon: "🔴" });
  }
  const ab = String(m.autonomie_bloc || "").trim().toLowerCase();
  if (ab === "oui" || ab === "x" || ab === "true" || ab === "1") {
    items.push({ type: "autonomie_bloc", label: "Autonomie bloc", icon: "🧗" });
  }
  const pass = (String(m.raw_passports || "") + " " + String(m.passeports || "") + " " + String(m.passeport_orange || "")).toLowerCase();
  if (pass.includes("orange") || String(m.passeport_orange || "").toLowerCase() === "oui") {
    items.push({ type: "passeport_orange", label: "Passeport orange", icon: "🟠" });
  }
  return items;
}
