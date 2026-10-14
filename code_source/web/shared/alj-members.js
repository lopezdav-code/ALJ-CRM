/* Chargement des adhérents depuis Google Cloud Firestore (collections crm_*)
   et reconstruction de la vue v_adherents_legacy côté navigateur.
   Partagé entre les pages du bureau web (ordinateur). */

export const CRM_COLLECTIONS = [
  "crm_seasons",
  "crm_users",
  "crm_orders",
  "crm_purchases",
  "crm_planning"
];

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

export function normalizeGender(val) {
  const s = String(val || "").trim().toLowerCase();
  if (s === "f" || s === "femme" || s === "féminin" || s === "feminin") return "Femme";
  if (s === "h" || s === "m" || s === "homme" || s === "masculin") return "Homme";
  return String(val || "").trim();
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

export function calcAge(birthDate, refDate) {
  if (!birthDate) return null;
  const m = String(birthDate).match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return null;
  const bYear = parseInt(m[1], 10), bMonth = parseInt(m[2], 10), bDay = parseInt(m[3], 10);
  const ref = refDate ? new Date(refDate) : new Date();
  if (isNaN(ref.getTime())) return null;
  let age = ref.getFullYear() - bYear;
  const refMonth = ref.getMonth() + 1;
  const refDay = ref.getDate();
  if (refMonth < bMonth || (refMonth === bMonth && refDay < bDay)) {
    age -= 1;
  }
  return age >= 0 ? age : null;
}

function tsMillis(v) {
  if (!v) return 0;
  if (typeof v.toMillis === "function") return v.toMillis();
  const t = Date.parse(v);
  return isNaN(t) ? 0 : t;
}

function alive(map) {
  const out = [];
  if (!map) return out;
  if (map instanceof Map) {
    for (const [id, d] of map) {
      if (d && d._deleted !== true) out.push(Object.assign({ _id: id }, d));
    }
  } else if (Array.isArray(map)) {
    for (const d of map) {
      if (d && d._deleted !== true) out.push(d);
    }
  }
  return out;
}

function byId(list) {
  const o = {};
  for (const d of list) o[String(d.id != null ? d.id : d._id)] = d;
  return o;
}

/**
 * Reconstruit la vue des adhérents à partir des collections crm_*.
 * @param {Record<string, Map|Array>} raw
 * @returns {{ members: Array, seasons: Array<string>, activeSeason: string, creneaux: Array, planning: Array }}
 */
export function buildMembersData(raw) {
  const seasons = alive(raw.crm_seasons);
  const seasonById = byId(seasons);
  const users = byId(alive(raw.crm_users));
  const orders = byId(alive(raw.crm_orders));

  // Planning & correspondance des tarifs
  const planning = alive(raw.crm_planning).sort((a, b) => Number(a.id) - Number(b.id));
  const creneaux = [];
  const byName = {};
  const planningByTarif = {};

  for (const item of planning) {
    const g = String(item.groupe || "").trim();
    if (!g) continue;
    let c = byName[g];
    if (!c) {
      c = { groupe: g, tarifs: [], categorie_age: item.categorie_age || "", type: item.type || "" };
      byName[g] = c;
      creneaux.push(c);
    }
    let tarifs = [];
    try { tarifs = JSON.parse(item.helloasso_tarifs || "[]"); } catch (e) { tarifs = []; }
    for (const t of tarifs) {
      const ts = String(t || "").trim();
      if (ts) {
        if (!c.tarifs.includes(ts)) c.tarifs.push(ts);
        const k = normKey(ts);
        if (!planningByTarif[k]) {
          planningByTarif[k] = {
            groupe: g,
            categorie_age: item.categorie_age || "",
            type: item.type || "",
            jour: item.jour || "",
            horaires: item.horaires || ""
          };
        }
      }
    }
  }
  creneaux.sort((a, b) => a.groupe.localeCompare(b.groupe, "fr"));

  const seasonNames = seasons.map(s => s.name).filter(Boolean).sort().reverse();
  const act = seasons.find(s => String(s.is_active) === "1" || s.is_active === true);
  const activeSeason = act ? act.name : (seasonNames[0] || "");

  // Détermination de la date de référence de la saison pour le calcul de l'âge (ex: 2026-09-01)
  const seasonYearMatch = activeSeason.match(/^(\d{4})/);
  const refSeasonDate = seasonYearMatch ? `${seasonYearMatch[1]}-09-01` : "";

  const members = [];
  for (const p of alive(raw.crm_purchases)) {
    const u = users[String(p.user_id)];
    const o = orders[String(p.order_id)];
    if (!u || !o) continue;
    const s = seasonById[String(o.season_id)];
    if (!s) continue;

    const tarif = p.tarif_name || "";
    const pInfo = planningByTarif[normKey(tarif)] || null;
    const creneauGroupe = pInfo ? pInfo.groupe : "";
    const categorie = (pInfo && pInfo.categorie_age) || (pInfo && pInfo.type) || "";

    const birthDate = u.birth_date || "";
    const age = calcAge(birthDate, refSeasonDate);

    members.push({
      user_id: u.id,
      purchase_id: p.id || p._id,
      last_name: fmtLastName(u.last_name || ""),
      first_name: fmtFirstName(u.first_name || ""),
      birth_date: birthDate,
      age: age,
      gender: normalizeGender(u.gender),
      address: u.address || "",
      zip_code: u.zip_code || "",
      city: fmtCity(u.city || ""),
      phone: fmtPhone(u.phone || ""),
      email_primary: u.email_primary || "",
      email_secondary: u.email_secondary || "",
      emergency1_name: fmtFirstName(u.emergency1_name || ""),
      emergency1_phone: fmtPhone(u.emergency1_phone || ""),
      emergency2_name: fmtFirstName(u.emergency2_name || ""),
      emergency2_phone: fmtPhone(u.emergency2_phone || ""),
      licence_ffme: u.licence_ffme || "",
      health_commitment: u.health_commitment || "",
      photo_auth: u.photo_auth || "",
      badge_rouge: u.badge_rouge || "",
      autonomie_bloc: u.autonomie_bloc || "",
      raw_passports: u.raw_passports || u.passeports || u.passports || "",
      raw_diplomas: u.raw_diplomas || u.diplomes || u.diplomas || "",
      passeport_orange: u.passeport_orange || "",
      payer: [o.payer_first_name, o.payer_last_name].filter(Boolean).join(" "),
      payer_email: o.payer_email || "",
      order_ref: o.order_ref || "",
      order_date: o.order_date || "",
      tarif_name: tarif,
      amount: p.amount,
      status: p.status || "",
      status_norm: normalizeStatus(p.status),
      document_sante: p.document_sante || "",
      email_sent_date: p.email_sent_date || "",
      commentaires_correctif: p.commentaires_correctif || p.comment || p.commentaire || "",
      season_name: s.name || "",
      creneau_groupe: creneauGroupe,
      categorie: categorie,
      creneau_details: pInfo ? `${pInfo.jour} ${pInfo.horaires}`.trim() : ""
    });
  }

  const coll = new Intl.Collator("fr", { sensitivity: "base" });
  members.sort((a, b) => coll.compare(a.last_name, b.last_name) || coll.compare(a.first_name, b.first_name));

  return { members, seasons: seasonNames, activeSeason, creneaux, planning };
}

/**
 * Lance l'écoute temps réel sur les collections crm_* dans Firestore.
 * @param {firebase.firestore.Firestore} fsdb
 * @param {{
 *   onData: (data: ReturnType<typeof buildMembersData>) => void,
 *   onStatus?: (status: string) => void,
 *   onError?: (error: Error) => void
 * }} callbacks
 * @returns {{ stop: () => void, refresh: (full?: boolean) => Promise<void> }}
 */
export function startMembersListener(fsdb, { onData, onStatus, onError }) {
  let listeners = [];
  let raw = {};
  let ready = new Set();
  let lastSyncAt = null;
  let renderTimer = null;

  const setStatus = msg => { if (onStatus) onStatus(msg); };

  function stop() {
    listeners.forEach(unsub => { try { unsub(); } catch (e) {} });
    listeners = [];
  }

  async function start(full = false) {
    stop();
    raw = {};
    ready = new Set();
    setStatus(full ? "Relecture complète de la base…" : "Chargement de la base…");

    for (const name of CRM_COLLECTIONS) {
      const col = fsdb.collection(name);
      const map = new Map();
      raw[name] = map;
      let watermark = 0;

      if (!full) {
        try {
          const cached = await col.get({ source: "cache" });
          cached.forEach(d => {
            const x = d.data();
            map.set(d.id, x);
            watermark = Math.max(watermark, tsMillis(x._modified_at));
          });
        } catch (e) {
          /* Pas de cache hors-ligne encore disponible */
        }
      }

      let query = col;
      if (watermark > 0) {
        query = col.where("_modified_at", ">=", firebase.firestore.Timestamp.fromMillis(watermark - 300000));
      }

      listeners.push(query.onSnapshot(
        snap => {
          snap.docChanges().forEach(ch => {
            if (ch.type === "removed" && watermark === 0) {
              map.delete(ch.doc.id);
            } else if (ch.type !== "removed") {
              map.set(ch.doc.id, ch.doc.data());
            }
          });
          ready.add(name);
          if (!snap.metadata.fromCache) lastSyncAt = new Date();
          if (ready.size < CRM_COLLECTIONS.length) {
            setStatus(`Chargement de la base… (${ready.size}/${CRM_COLLECTIONS.length})`);
            return;
          }
          clearTimeout(renderTimer);
          renderTimer = setTimeout(() => {
            const data = buildMembersData(raw);
            setStatus("☁️ Firestore temps réel — màj " + fmtDate((lastSyncAt || new Date()).toISOString()));
            if (onData) onData(data);
          }, 150);
        },
        err => {
          console.error("Firestore " + name + " :", err);
          if (onError) onError(err);
          setStatus("⚠️ Erreur Firestore : " + (err.code || err.message));
        }
      ));
    }
  }

  start(false);

  return {
    stop,
    refresh: (full = true) => start(full)
  };
}
