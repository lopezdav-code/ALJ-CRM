/* Member list of the web pages, loaded from the API one season at a time
   (replaces the Firestore listeners on the crm_* collections and the rebuild in the browser).
   Classic script (not a module), like alj-sync.js which it needs: usable from the PWA page
   through <script> as well as from the bureau modules. Exposes window.ALJMembersSync.

   start({ fetch, season, intervalMs, onData, onStatus }) polls /api/seasons and
   /api/members?season=… (ETag: an unchanged poll is a 304 without body) and calls
   onData({ members, creneaux, seasons, activeSeason, season }) once both are known and on
   every change. Without `season`, the server answers with the active season. The returned
   setSeason(name) switches season, refresh() reloads now (after the user's own write),
   stop() ends the polling (logout). No offline copy: member data stays online only (plan D2). */
(function () {
  "use strict";

  function start(opts) {
    const o = Object.assign({ intervalMs: 20000, onData() {}, onStatus() {} }, opts || {});
    if (!window.ALJSync) throw new Error("ALJMembersSync: load alj-sync.js first");
    let season = o.season || "";
    let seasons = null;        // { seasons, active }
    let current = null;        // { season, members, creneaux }
    let membersPoll = null;

    function emit() {
      if (!seasons || !current) return;
      o.onData({
        members: current.members,
        creneaux: current.creneaux,
        seasons: seasons.seasons,
        activeSeason: seasons.active,
        season: current.season
      });
    }

    function pollMembers() {
      if (membersPoll) membersPoll.stop();
      const url = "/api/members" + (season ? "?season=" + encodeURIComponent(season) : "");
      membersPoll = ALJSync.poll(url, {
        fetch: o.fetch, intervalMs: o.intervalMs,
        onStatus: (status, info) => {
          // A season that no longer exists: fall back to the active one
          if (status === "error" && info && info.status === 404 && season) { setSeason(""); return; }
          o.onStatus(status, info);
        },
        onData: data => { current = data; season = data.season; emit(); }
      });
    }

    const seasonsPoll = ALJSync.poll("/api/seasons", {
      fetch: o.fetch, intervalMs: Math.max(o.intervalMs, 60000),
      onStatus: (status, info) => { if (status !== "ok") o.onStatus(status, info); },
      onData: data => { seasons = data; emit(); }
    });
    pollMembers();

    function setSeason(name) {
      if ((name || "") === season && membersPoll) return;
      season = name || "";
      current = null;
      pollMembers();
    }

    return {
      setSeason,
      refresh: () => Promise.all([seasonsPoll.refresh(), membersPoll && membersPoll.refresh()]),
      stop: () => { seasonsPoll.stop(); if (membersPoll) membersPoll.stop(); }
    };
  }

  window.ALJMembersSync = Object.freeze({ start });
})();
