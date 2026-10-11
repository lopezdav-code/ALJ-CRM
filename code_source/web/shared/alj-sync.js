/* Keeps a page's data up to date through the API (replaces the Firestore listeners).
   Classic script (not a module): usable from the PWA pages through <script> as well as
   from the bureau modules. Exposes window.ALJSync.

   - poll(url, opts): loads url now, then every intervalMs while the page is visible;
     reloads when the page becomes visible again, when the network comes back, and on
     demand (refresh() right after the user's own write). Sends If-None-Match so an
     unchanged poll is a 304 without body. Responses are never put in the HTTP cache.
   - snapshot: last data kept in localStorage for read-only offline viewing, tied to the
     signed-in user; clearAll() on logout. Only for data the plan allows offline
     (competitions and participants), never the member directory. */
(function () {
  "use strict";

  const SNAPSHOT_PREFIX = "alj_snapshot:";

  function poll(url, opts) {
    const o = Object.assign({ intervalMs: 20000, onData() {}, onStatus() {} }, opts || {});
    if (typeof o.fetch !== "function") throw new Error("ALJSync.poll: opts.fetch is required");
    let etag = null;
    let timer = null;
    let inFlight = null;
    let again = false;
    let stopped = false;

    function schedule() {
      clearTimeout(timer);
      if (!stopped) timer = setTimeout(tick, o.intervalMs);
    }
    function tick() {
      if (document.hidden) { schedule(); return; }  // paused while hidden
      refresh();
    }

    async function load() {
      const headers = etag ? { "If-None-Match": etag } : {};
      let res;
      try {
        res = await o.fetch(url, { headers, cache: "no-store" });
      } catch (error) {
        o.onStatus(navigator.onLine === false ? "offline" : "error", { error });
        return;
      }
      if (res.status === 304) { o.onStatus("ok", { changed: false }); return; }
      if (!res.ok) { o.onStatus("error", { status: res.status }); return; }
      let data;
      try { data = await res.json(); } catch (error) { o.onStatus("error", { error }); return; }
      etag = res.headers.get("ETag");
      o.onData(data);
      o.onStatus("ok", { changed: true });
    }

    /* Concurrent calls are merged: one more load runs after the current one. */
    function refresh() {
      if (stopped) return Promise.resolve();
      if (inFlight) { again = true; return inFlight; }
      clearTimeout(timer);
      inFlight = load().finally(() => {
        inFlight = null;
        if (again) { again = false; return refresh(); }
        schedule();
      });
      return inFlight;
    }

    const onVisible = () => { if (!document.hidden) refresh(); };
    const onOnline = () => refresh();
    const onOffline = () => o.onStatus("offline", {});
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);

    function stop() {
      stopped = true;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    }

    refresh();
    return { refresh, stop };
  }

  /* localStorage can be missing or throw (private window, blocked site data): every access
     is guarded and a failure only means "no offline copy". */
  function storage() {
    try { return window.localStorage; } catch (e) { return null; }
  }

  const snapshot = Object.freeze({
    save(name, uid, data) {
      const s = storage();
      if (!s || !uid) return false;
      try {
        s.setItem(SNAPSHOT_PREFIX + name, JSON.stringify({ uid, savedAt: Date.now(), data }));
        return true;
      } catch (e) { return false; }  // quota exceeded
    },
    /* Returns { data, savedAt } or null (none, unreadable, or saved by another user). */
    load(name, uid) {
      const s = storage();
      if (!s || !uid) return null;
      try {
        const v = JSON.parse(s.getItem(SNAPSHOT_PREFIX + name) || "null");
        return v && v.uid === uid ? { data: v.data, savedAt: v.savedAt } : null;
      } catch (e) { return null; }
    },
    clearAll() {
      const s = storage();
      if (!s) return;
      try {
        const keys = [];
        for (let i = 0; i < s.length; i++) {
          const k = s.key(i);
          if (k && k.startsWith(SNAPSHOT_PREFIX)) keys.push(k);
        }
        keys.forEach(k => s.removeItem(k));
      } catch (e) { /* nothing stored */ }
    }
  });

  window.ALJSync = Object.freeze({ poll, snapshot });
})();
