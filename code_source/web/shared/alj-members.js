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

export function fmtDay(s) {
  const m = String(s || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : String(s || "");
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
      last_name: u.last_name || "",
      first_name: u.first_name || "",
      birth_date: birthDate,
      age: age,
      gender: u.gender || "",
      address: u.address || "",
      zip_code: u.zip_code || "",
      city: u.city || "",
      phone: u.phone || "",
      email_primary: u.email_primary || "",
      email_secondary: u.email_secondary || "",
      emergency1_name: u.emergency1_name || "",
      emergency1_phone: u.emergency1_phone || "",
      emergency2_name: u.emergency2_name || "",
      emergency2_phone: u.emergency2_phone || "",
      licence_ffme: u.licence_ffme || "",
      health_commitment: u.health_commitment || "",
      photo_auth: u.photo_auth || "",
      badge_rouge: u.badge_rouge || "",
      autonomie_bloc: u.autonomie_bloc || "",
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
