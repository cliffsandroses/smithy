// Grab a Teams/Stream recording from SharePoint into EC01\PCAI\inbox — a bookmark for the signed-in work laptop.
// (Moosa, 2026-11-02: "I'll be using the video tool on my work laptop that's alr signed in"; "get the video-transcript
// tool done asap, I have many recordings")
// On the recording's page (…/stream.aspx?id=… or the file's link) click the bookmark:
//   1. the first time it asks for a folder: pick EC01\PCAI\inbox (remembered after that on this SharePoint site);
//   2. it saves <name>.vtt — Teams' own transcript, with speakers — when the meeting had one;
//   3. it asks what the recording is for (PNIP, me, team meeting) and puts that in the file names as [pnip]/[me]/[meeting];
//   4. it saves <name>.txt with a fresh download link for the video; the homelab downloads it within a minute, takes
//      screenshots and (when there was no Teams transcript) transcribes it.
// Uses only the browser's existing sign-in. Nothing is installed; nothing goes anywhere but that folder.
(async () => {
  const note = (m, bad) => { let d = document.getElementById("grabrec"); if (!d) { d = document.createElement("div"); d.id = "grabrec"; d.style.cssText = "position:fixed;z-index:2147483647;right:16px;bottom:16px;max-width:420px;padding:12px 14px;border-radius:10px;font:14px Segoe UI,sans-serif;box-shadow:0 8px 30px rgba(0,0,0,.3);white-space:pre-wrap"; document.body.append(d) } d.style.background = bad ? "#fdecea" : "#eefaf6"; d.style.color = "#1c1c1c"; d.textContent = m };
  // --- the inbox folder (asked once, kept in this site's storage) ---
  const idb = () => new Promise((ok, no) => { const r = indexedDB.open("grabrec", 1); r.onupgradeneeded = () => r.result.createObjectStore("h"); r.onsuccess = () => ok(r.result); r.onerror = () => no(r.error) });
  const get = async () => { const db = await idb(); return new Promise(ok => { const t = db.transaction("h").objectStore("h").get("inbox"); t.onsuccess = () => ok(t.result); t.onerror = () => ok(null) }) };
  const put = async h => { const db = await idb(); db.transaction("h", "readwrite").objectStore("h").put(h, "inbox") };
  let dir = null;
  try {
    dir = await get();
    if (dir && (await dir.queryPermission({ mode: "readwrite" })) !== "granted" && (await dir.requestPermission({ mode: "readwrite" })) !== "granted") dir = null;
    if (!dir) { note("Pick the EC01 \\ PCAI \\ inbox folder (asked once)."); dir = await showDirectoryPicker({ id: "ec01inbox", mode: "readwrite" }); await put(dir) }
  } catch (e) { dir = null }   // no folder access: fall back to normal downloads
  const save = async (name, text) => {
    if (dir) { const f = await dir.getFileHandle(name, { create: true }); const w = await f.createWritable(); await w.write(text); await w.close(); return }
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([text])); a.download = name; document.body.append(a); a.click(); a.remove();
  };
  try {
    note("Finding the recording…");
    const qs = new URLSearchParams(location.search), id = qs.get("id");
    const fileUrl = id ? location.origin + id : location.href.split("?")[0];
    const site = location.origin + ((id || location.pathname).match(/^\/(sites|teams|personal)\/[^/]+/) || [""])[0];
    const enc = "u!" + btoa(unescape(encodeURIComponent(fileUrl))).replace(/=+$/, "").replace(/\//g, "_").replace(/\+/g, "-");
    const api = async (p, raw) => { const r = await fetch(site + "/_api/v2.1/" + p, { credentials: "include", headers: { accept: raw ? "*/*" : "application/json" } }); if (!r.ok) throw new Error(r.status + " on " + p.split("?")[0]); return raw ? r.text() : r.json() };
    const item = await api(`shares/${enc}/driveItem?$select=id,name,parentReference,@content.downloadUrl`);
    const why = (prompt("What is this recording for?\n1 = PNIP / PCAI tool\n2 = me (my notes, my questions)\n3 = team meeting (summary + actions)", "1") || "1").trim();
    const tag = { "1": "pnip", "2": "me", "3": "meeting" }[why] || "pnip";
    const drive = item.parentReference.driveId, base = `[${tag}] ` + item.name.replace(/\.[^.]+$/, "").replace(/[\\/:*?"<>|]+/g, " ").trim();
    let got = [];
    // Teams transcript
    try {
      const tr = (await api(`drives/${drive}/items/${item.id}/media/transcripts`)).value || [];
      if (tr.length) {
        let t = null;
        try { t = await api(`drives/${drive}/items/${item.id}/media/transcripts/${tr[0].id}/streamContent?format=vtt`, true); if (!/WEBVTT/.test(t)) t = null } catch (e) { }
        if (!t) {                                            // JSON form → VTT
          const j = JSON.parse(await api(`drives/${drive}/items/${item.id}/media/transcripts/${tr[0].id}/streamContent?format=json`, true));
          const ts = s => { s = String(s).replace(/^(\d+):(\d+):(\d+)\.?(\d*).*$/, (m, h, mi, se, f) => `${h.padStart(2, "0")}:${mi}:${se}.${(f || "0").padEnd(3, "0").slice(0, 3)}`); return s };
          t = "WEBVTT\n\n" + (j.entries || []).map(e => `${ts(e.startOffset)} --> ${ts(e.endOffset)}\n<v ${e.speakerDisplayName || "Speaker"}>${e.text}`).join("\n\n");
        }
        await save(base + ".vtt", t); got.push("Teams transcript");
      }
    } catch (e) { }
    // fresh video link for the homelab (download + screenshots, and transcription if there was no Teams transcript)
    const dl = item["@content.downloadUrl"] || (await api(`drives/${drive}/items/${item.id}?$select=@content.downloadUrl`))["@content.downloadUrl"];
    if (dl) { await save(base + ".txt", dl + "\n"); got.push("video link") }
    if (!got.length) throw new Error("no transcript and no video link came back");
    note(`Saved ${got.join(" + ")} for "${base}"${dir ? " in the inbox folder" : " to Downloads — move them to EC01\\PCAI\\inbox"}. The homelab takes it from here.`);
  } catch (e) { note("Couldn't grab this recording: " + e.message + "\nOpen the recording itself (the page that plays it) and click again.", true) }
})();
