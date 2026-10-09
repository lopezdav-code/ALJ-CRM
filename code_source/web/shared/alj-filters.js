/* Logique de filtrage et d'arborescence des créneaux/tarifs des adhérents.
   Extrait et adapté de l'annuaire pour le portail bureau web (ordinateur). */

import { normKey, fmtDay, normalizeStatus } from "/static-web/alj-members.js";

export const FILTER_KEY = "alj_bureau_adherents_filters";

export function accentClassPattern(word) {
  const tr = {
    "e": "[eèéêë]", "a": "[aàâä]", "i": "[iîï]", "o": "[oôö]", "u": "[uùûü]", "c": "[cç]", "y": "[yÿ]"
  };
  return word.split("").map(ch => tr[ch] || ch).join("");
}

export function shortenGroupLabel(name, keyword, dropPatterns) {
  const parts = name.split(new RegExp(accentClassPattern(keyword), "i"));
  let rest = parts.length > 1 ? parts.reduce((a, b) => (b.length > a.length ? b : a)) : name;
  for (const dp of dropPatterns || []) {
    rest = rest.replace(new RegExp(dp, "ig"), "");
  }
  rest = rest.replace(/\s{2,}/g, " ").replace(/^[\s\u2013\u2014-]+|[\s\u2013\u2014-]+$/g, "");
  if (rest.startsWith("(") && rest.endsWith(")")) rest = rest.slice(1, -1).trim();
  return rest || name;
}

export function isWaiting(rawName, label) {
  return normKey(rawName).includes("attente") || normKey(label).includes("attente");
}

export function buildCreneauItems(creneaux) {
  const SECTION_ORDER = ["Collège", "Enfants", "Perfectionnement", "Compétition"];
  const buckets = { "Collège": [], "Enfants": {}, "Perfectionnement": [], "Compétition": [] };
  const others = [];

  for (const c of creneaux) {
    const name = c.groupe, n = normKey(name);
    if (n.includes("competition")) {
      buckets["Compétition"].push([name, shortenGroupLabel(name, "competition")]);
    } else if (n.includes("college")) {
      buckets["Collège"].push([name, shortenGroupLabel(name, "college")]);
    } else if (n.includes("enfants")) {
      const m = n.match(/20\d\d\s*-\s*20\d\d/);
      const sub = m ? m[0].replace(/\s/g, "") : "Autres tranches";
      const short = shortenGroupLabel(name, "enfants", ["20\\d\\d\\s*-\\s*20\\d\\d"]);
      (buckets["Enfants"][sub] = buckets["Enfants"][sub] || []).push([name, short]);
    } else if (n.includes("perfectionnement")) {
      buckets["Perfectionnement"].push([name, shortenGroupLabel(name, "perfectionnement")]);
    } else {
      others.push([name, name]);
    }
  }

  const cmp = (a, b) => a[0].localeCompare(b[0], "fr");
  const items = [];

  for (const [name, short] of others.sort(cmp)) {
    items.push({ kind: "group", label: short, raw: name });
  }

  for (const section of SECTION_ORDER) {
    const entries = buckets[section];
    const empty = Array.isArray(entries) ? !entries.length : !Object.keys(entries).length;
    if (empty) continue;

    items.push({ kind: "section", label: section, raw: section });
    if (Array.isArray(entries)) {
      for (const [name, short] of entries.sort(cmp)) {
        items.push({ kind: "group", label: short, raw: name });
      }
    } else {
      for (const sub of Object.keys(entries).sort()) {
        items.push({ kind: "sub", label: sub, raw: sub });
        for (const [name, short] of entries[sub].sort(cmp)) {
          items.push({ kind: "group", label: short, raw: name });
        }
      }
    }
  }

  for (const it of items) {
    if (it.kind === "group") {
      it.tarifs = ((creneaux.find(c => c.groupe === it.raw) || {}).tarifs) || [];
    }
  }

  return items;
}

export function computeFilterCache(members, creneaux, itemsCache, season) {
  const seasonMembers = members.filter(m => (m.season_name || "") === season);
  const covered = new Set();
  for (const c of creneaux) {
    for (const t of c.tarifs) covered.add(normKey(t));
  }

  const others = {}, tarifIndex = {};
  for (const m of seasonMembers) {
    const k = normKey(m.tarif_name);
    if (!k) continue;
    tarifIndex[k] = (tarifIndex[k] || 0) + 1;
    if (!covered.has(k)) {
      others[m.tarif_name] = (others[m.tarif_name] || 0) + 1;
    }
  }

  for (const it of itemsCache) {
    if (it.kind !== "group") continue;
    it.count = (it.tarifs || []).reduce((s, t) => s + (tarifIndex[normKey(t)] || 0), 0);
  }

  return { members: seasonMembers, others };
}

export function allowedTarifKeys(itemsCache, filterCache, filters) {
  const allowed = new Set();
  const groupsStore = filters.groups || {};
  const othersStore = filters.others || {};

  for (const it of itemsCache) {
    if (it.kind !== "group") continue;
    const on = groupsStore[it.raw] !== undefined ? groupsStore[it.raw] : !isWaiting(it.raw, it.label);
    if (on) {
      for (const t of it.tarifs) allowed.add(normKey(t));
    }
  }

  if (filterCache && filterCache.others) {
    for (const t of Object.keys(filterCache.others)) {
      const k = "other:" + t;
      const on = othersStore[k] !== undefined ? othersStore[k] : !isWaiting(t, t);
      if (on) allowed.add(normKey(t));
    }
  }

  return allowed;
}

export function filterMembers(members, filters, allowedTarifs) {
  const q = normKey(filters.search || "");
  const st = filters.status || "";

  return members.filter(m => {
    const k = normKey(m.tarif_name);
    if (k && allowedTarifs && !allowedTarifs.has(k)) return false;
    if (st && m.status_norm !== st) return false;
    if (q) {
      const nom = normKey(m.last_name);
      const prenom = normKey(m.first_name);
      const plein1 = normKey(m.first_name + " " + m.last_name);
      const plein2 = normKey(m.last_name + " " + m.first_name);
      const tarif = normKey(m.tarif_name);
      const licence = normKey(m.licence_ffme);
      const mail = normKey(m.email_primary);
      const tel = normKey(m.phone);
      if (!(nom.includes(q) || prenom.includes(q) || plein1.includes(q) || plein2.includes(q)
            || tarif.includes(q) || licence.includes(q) || mail.includes(q) || tel.includes(q))) {
        return false;
      }
    }
    return true;
  });
}

export function sortMembers(list, sortKey, sortAsc = true) {
  const coll = new Intl.Collator("fr", { sensitivity: "base", numeric: true });
  return [...list].sort((a, b) => {
    let va = a[sortKey] != null ? a[sortKey] : "";
    let vb = b[sortKey] != null ? b[sortKey] : "";

    // Traitement spécifique selon le type
    if (sortKey === "amount" || sortKey === "age") {
      const na = va === "" || va == null ? -1 : Number(va);
      const nb = vb === "" || vb == null ? -1 : Number(vb);
      return sortAsc ? na - nb : nb - na;
    }

    const res = coll.compare(String(va), String(vb));
    return sortAsc ? res : -res;
  });
}

export function exportMembersCsv(members, seasonName) {
  const headers = [
    "Nom", "Prénom", "Date de naissance", "Âge", "Sexe", "Catégorie", "Créneau", "Tarif",
    "Montant (€)", "Statut", "N° Licence FFME", "E-mail principal", "E-mail secondaire",
    "Téléphone", "Adresse", "Code postal", "Ville", "Urgence 1 - Nom", "Urgence 1 - Tél",
    "Urgence 2 - Nom", "Urgence 2 - Tél", "Payeur", "E-mail payeur", "Réf Commande", "Date commande"
  ];

  const escapeCsv = val => {
    if (val == null) return "";
    const s = String(val).replace(/"/g, '""');
    return `"${s}"`;
  };

  const rows = [headers.map(escapeCsv).join(";")];

  for (const m of members) {
    const row = [
      m.last_name,
      m.first_name,
      fmtDay(m.birth_date),
      m.age != null ? m.age : "",
      m.gender,
      m.categorie,
      m.creneau_groupe,
      m.tarif_name,
      m.amount != null ? m.amount : "",
      m.status_norm,
      m.licence_ffme,
      m.email_primary,
      m.email_secondary,
      m.phone,
      m.address,
      m.zip_code,
      m.city,
      m.emergency1_name,
      m.emergency1_phone,
      m.emergency2_name,
      m.emergency2_phone,
      m.payer,
      m.payer_email,
      m.order_ref,
      fmtDay(m.order_date)
    ];
    rows.push(row.map(escapeCsv).join(";"));
  }

  // BOM UTF-8 pour Excel
  const blob = new Blob(["\uFEFF" + rows.join("\r\n")], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const cleanSeason = String(seasonName || "saison").replace(/[^\w-]/g, "_");
  a.href = url;
  a.download = `adherents_${cleanSeason}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
