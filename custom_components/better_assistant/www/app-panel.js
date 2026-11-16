// Better Assistant app (the sidebar page): Home, Alarms & reminders, Voice and Settings.
// One module, no build step, no dependencies; colours come from the Home Assistant theme.
//
// The Voice page (<better-assistant-voice-view>). Training: a live view of the session
// (better_assistant/voice_training/subscribe) with Start, Skip and Stop, plus voice match status per
// person. Recordings: what the speakers heard, who voice match thought it was, with play, "That was..."
// and delete. The app (<better-assistant-app>, further down) shows it on its Voice page.

const VOICE_CSS = `
  :host { display: block; color: var(--primary-text-color); }
  .tabs { display: flex; gap: 4px; margin: 0 0 16px; }
  .tab { flex: 1; text-align: center; padding: 10px; border-radius: 12px; cursor: pointer; font-weight: 600;
         color: var(--secondary-text-color); border: 1px solid var(--divider-color); background: transparent; font: inherit; }
  .tab.on { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: transparent; }
  .wrap { }
  .card { background: var(--card-background-color); border-radius: 16px; padding: 22px;
          box-shadow: var(--ha-card-box-shadow, none); border: 1px solid var(--divider-color); margin-bottom: 16px; }
  .lead { color: var(--secondary-text-color); font-size: 15px; line-height: 1.5; margin: 0 0 18px; }
  .progress { color: var(--secondary-text-color); font-size: 14px; margin-bottom: 6px; }
  .bar { height: 6px; border-radius: 3px; background: var(--divider-color); overflow: hidden; margin-bottom: 22px; }
  .bar > div { height: 100%; background: var(--primary-color); transition: width .3s; }
  .say { font-size: 13px; text-transform: uppercase; letter-spacing: .08em; color: var(--secondary-text-color); }
  .now { font-size: 28px; font-weight: 600; line-height: 1.25; margin: 8px 0 14px; }
  .hint { color: var(--warning-color, #f0a020); font-size: 15px; min-height: 22px; margin-bottom: 8px; }
  ul { list-style: none; padding: 0; margin: 18px 0 0; border-top: 1px solid var(--divider-color); }
  li { display: flex; align-items: center; gap: 12px; padding: 11px 0; font-size: 16px;
       border-bottom: 1px solid var(--divider-color); }
  li .mark { width: 22px; text-align: center; flex: none; }
  li.said, li.skipped { color: var(--disabled-text-color, #888); text-decoration: line-through; }
  li.said .mark { color: var(--success-color, #43a047); text-decoration: none; }
  li.current { font-weight: 600; color: var(--primary-color); }
  li.waiting { color: var(--secondary-text-color); }
  .tag { font-size: 12px; text-decoration: none; margin-left: auto; }
  .buttons { display: flex; gap: 12px; margin-top: 18px; flex-wrap: wrap; }
  button { font: inherit; font-size: 15px; border-radius: 22px; padding: 10px 18px; cursor: pointer;
           border: 1px solid var(--divider-color); background: transparent; color: var(--primary-text-color); }
  button.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); border: none;
                   width: 100%; padding: 15px; font-size: 18px; font-weight: 600; }
  button.small { padding: 6px 12px; font-size: 13px; }
  button.picked { border-color: var(--primary-color); color: var(--primary-color); }
  button.danger { color: var(--error-color, #db4437); }
  button:disabled { opacity: .5; cursor: default; }
  .big { font-size: 24px; font-weight: 600; margin: 0 0 8px; }
  h3 { margin: 0 0 6px; font-size: 18px; }
  .error { color: var(--error-color, #db4437); }
  .person { display: flex; align-items: center; gap: 10px; padding: 10px 0; border-top: 1px solid var(--divider-color); flex-wrap: wrap; }
  .person .who { font-weight: 600; }
  .person .what { color: var(--secondary-text-color); font-size: 14px; flex: 1; min-width: 50%; }
  .ok { color: var(--success-color, #43a047); } .warn { color: var(--warning-color, #f0a020); }
  .clip { padding: 12px 0; border-top: 1px solid var(--divider-color); }
  .clip .line1 { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  .clip .heard { font-size: 16px; flex: 1; min-width: 60%; }
  .clip .meta { color: var(--secondary-text-color); font-size: 13px; margin-top: 2px; }
  .chip { font-size: 12px; border-radius: 10px; padding: 2px 8px; border: 1px solid var(--divider-color); white-space: nowrap; }
  .chip.me { border-color: var(--success-color, #43a047); color: var(--success-color, #43a047); }
  .chip.unsure { border-color: var(--warning-color, #f0a020); color: var(--warning-color, #f0a020); }
  .clip .acts { display: flex; gap: 8px; align-items: center; margin-top: 8px; flex-wrap: wrap; }
  select { font: inherit; font-size: 13px; padding: 5px 8px; border-radius: 10px; background: var(--card-background-color);
           color: var(--primary-text-color); border: 1px solid var(--divider-color); }
  .filters { display: flex; gap: 8px; margin-bottom: 4px; align-items: center; flex-wrap: wrap; }
  .count { color: var(--secondary-text-color); font-size: 13px; margin-left: auto; }
  .bulk { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; padding: 8px 0; font-size: 14px; }
  .bulk.on { position: sticky; top: 0; z-index: 1; background: var(--card-background-color);
             border-bottom: 1px solid var(--primary-color); }
  .pickall { color: var(--secondary-text-color); display: flex; gap: 6px; align-items: center; margin-right: 8px; }
  .clip.picked { background: rgba(var(--rgb-primary-color, 3, 169, 244), 0.08); }
  input.pick { width: 18px; height: 18px; margin: 0 4px 0 0; align-self: center; }
  .empty { color: var(--secondary-text-color); padding: 12px 0; }
`;

class BetterAssistantVoiceView extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._view = null; this._error = ""; this._busy = false;
    this._tab = "training"; this._clips = null; this._loading = false;
    this._people = []; this._filter = "all"; this._sort = "newest"; this._picked = new Set();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._subscribe();
  }

  async _subscribe() {
    if (this._unsub) { try { this._unsub(); } catch (e) { /* already gone */ } this._unsub = null; }
    try {
      this._unsub = await this._hass.connection.subscribeMessage(
        (view) => { this._view = view; this._render(); },
        { type: "better_assistant/voice_training/subscribe" });
      this._error = "";
    } catch (err) {
      this._error = "Voice training isn't ready yet. Try again in a moment.";
      setTimeout(() => this._hass && this._subscribe(), 4000);
    }
    this._render();
  }

  disconnectedCallback() { if (this._unsub) { this._unsub(); this._unsub = null; this._hass = null; } }

  refresh() { this._clips = null; this._subscribe(); }

  async _act(action) {
    if (action === "match_off" && !confirm("Turn off voice match? It stops recording everyday requests and deletes " +
        "the ones nobody labelled. Training recordings stay, so turning it back on works straight away.")) return;
    this._busy = true; this._error = ""; this._render();
    try {
      const res = await this._hass.callWS({ type: "better_assistant/voice_training/action", action });
      if (res && res.problem) this._error = res.problem;
      if (action.startsWith("match_")) setTimeout(() => this._subscribe(), 4000);   // Better Assistant reloads
    } catch (err) { this._error = err.message || String(err); }
    this._busy = false; this._render();
  }

  async _loadClips() {
    if (this._loading) return;
    this._loading = true;
    try {
      const res = await this._hass.callWS({ type: "better_assistant/voice/clips", limit: 150 });
      this._clips = res.clips; this._people = res.people;
    } catch (err) { this._clips = []; this._error = err.message || String(err); }
    this._loading = false; this._render();
  }

  async _clipAction(action, id, person) {
    const many = Array.isArray(id);
    if (action === "delete" && !confirm(many ? `Delete ${id.length} recordings?` : "Delete this recording?")) return;
    if (action === "delete_person" && !confirm("Delete every recording of this voice? Voice match will forget them.")) return;
    try {
      await this._hass.callWS({ type: "better_assistant/voice/clip_action", action,
                                ...(many ? { clips: id } : id ? { clip: id } : {}), ...(person ? { person } : {}) });
      if (many) this._picked.clear();
    } catch (err) { this._error = err.message || String(err); }
    this._clips = null; this._render();
  }

  _esc(s) { return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

  // ------------------------------------------------------------ training tab
  _list(v) {
    const marks = { said: "✓", skipped: "–", current: "▶", waiting: "" };
    return `<ul>${v.phrases.map((p) => `<li class="${p.state}"><span class="mark">${marks[p.state]}</span>
      <span>${this._esc(p.text)}</span>${p.state === "skipped" ? '<span class="tag">skipped</span>' : ""}</li>`).join("")}</ul>`;
  }

  _training(v) {
    const busy = this._busy ? "disabled" : "";
    if (v.status === "training") {
      const cur = v.phrases.find((p) => p.state === "current");
      const done = v.phrases.filter((p) => p.state === "said" || p.state === "skipped").length;
      return `<div class="card">
        <div class="progress">Phrase ${Math.min(done + 1, v.total)} of ${v.total}</div>
        <div class="bar"><div style="width:${(done / v.total) * 100}%"></div></div>
        <div class="say">After the ding, take a breath, then say</div>
        <div class="now">${this._esc(cur ? cur.text : "")}</div>
        <div class="hint">${this._esc(v.hint || "")}</div>
        <div class="buttons"><button ${busy} data-a="skip">Skip</button><button ${busy} data-a="stop">Stop</button></div>
        ${this._list(v)}</div>`;
    }
    const start = `<button class="primary" ${busy} data-a="start">${v.status === "idle" ? "Start" : "Train again"}</button>`;
    if (v.status === "done" || v.status === "stopped") {
      const n = v.saved || 0;
      return `<div class="card"><p class="big">${v.status === "done" ? "All done" : "Stopped"}</p>
        <p class="lead">Saved ${n} recording${n === 1 ? "" : "s"} of ${this._esc(v.name || "your")}'s voice.</p>
        ${start}${this._list(v)}</div>`;
    }
    return `<div class="card"><p class="big">Teach Better Assistant your voice</p>
      <p class="lead">We're going to have you repeat some phrases on the screen. After each ding,
        take a breath, then say the highlighted phrase to your voice speaker. There are 8, and it takes about a minute.</p>
      ${start}</div>`;
  }

  _match(v) {
    const m = v.match || { status: "off" };
    const busy = this._busy ? "disabled" : "";
    if (!v.match_on) {
      return `<div class="card"><h3>Voice match</h3>
        <p class="lead">Recognise who's speaking, so "my calendar" and "my reminders" work for whoever asks.
          It runs on this machine (a one-time 19 MB download) and only knows people who've trained their voice.
          It's never used to unlock doors. While it's on, everyday requests are kept for 14 days so you can check them;
          when it's off, nothing is recorded except training.</p>
        <button ${busy} data-a="match_on">Turn on voice match</button></div>`;
    }
    if (m.status === "downloading" || m.status === "off") {
      return `<div class="card"><h3>Voice match</h3><p class="lead">Getting the voice model ready…</p></div>`;
    }
    if (m.status === "error") {
      return `<div class="card"><h3>Voice match</h3><p class="error">It couldn't start: ${this._esc(m.problem)}</p>
        <button ${busy} data-a="match_on">Try again</button></div>`;
    }
    const grades = { ready: ['<span class="ok">Ready ✓</span>', ""],
                     weak: ['<span class="warn">Needs a better sample</span>', " Train again somewhere quieter."],
                     too_few: ['<span class="warn">Not enough recordings</span>', " Train again to finish."] };
    const rows = (m.people || []).map((p) => {
      const [g, tip] = grades[p.grade] || [this._esc(p.grade), ""];
      const left = p.dropped ? `, ${p.dropped} left out` : "";
      return `<div class="person"><span class="who">${this._esc(p.name)}</span>
        <span class="what">${g} · ${p.clips} recordings${left}.${tip}</span>
        <button class="small danger" data-p="${this._esc(p.person)}" data-del-person="1">Delete voice</button></div>`;
    }).join("") || `<p class="empty">Nobody has trained yet. Press Start above.</p>`;
    return `<div class="card"><h3>Voice match</h3>
      <p class="lead">Who it knows. Recordings that don't sound like the rest (the TV, someone else) are left out automatically.</p>
      ${rows}<div class="buttons"><button class="small" ${busy} data-a="match_off">Turn off voice match</button></div></div>`;
  }

  // ------------------------------------------------------------ recordings tab
  _when(iso) {
    if (!iso) return "";
    return new Date(iso).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric",
                                                     hour: "numeric", minute: "2-digit" });
  }

  _chip(c) {
    if (c.label === "train") return `<span class="chip">Training · ${this._esc(c.name || "")}</span>`;
    if (c.label === "other") return `<span class="chip">Someone else / TV</span>`;
    if (c.confirmed) return `<span class="chip me">${this._esc(c.name || "")} ✓</span>`;
    if (c.match && c.match.person)
      return `<span class="chip me">Sounded like ${this._esc(c.match.name || "")}${c.match.score < 0.5 ? " (weak)" : ""}</span>`;
    if (c.match) return `<span class="chip unsure">Not sure who</span>`;
    return `<span class="chip">Not checked</span>`;
  }

  _who(c) {
    // the person a recording belongs to: labelled / training first, then who it sounded like
    if (c.label === "other") return "other";
    if (c.confirmed || c.label === "train") return c.person;
    return c.match && c.match.person ? c.match.person : null;
  }

  _shown() {
    const f = this._filter;
    const keep = (c) => {
      if (f === "all") return true;
      if (f === "unsure") return c.label === "test" && !c.confirmed && !(c.match && c.match.person);
      if (f === "unlabelled") return c.label === "test" && !c.confirmed;
      if (f === "train") return c.label === "train";
      if (f === "other") return c.label === "other";
      return this._who(c) === f;                            // a person
    };
    const score = (c) => (c.match && typeof c.match.score === "number" ? c.match.score : 2);
    const clips = this._clips.filter(keep);
    if (this._sort === "oldest") clips.reverse();
    else if (this._sort === "weakest") clips.sort((a, b) => score(a) - score(b));
    return clips;
  }

  _bulk(clips, opts) {
    // keep only picks that still exist; "Select all" means the ones shown
    const ids = new Set(this._clips.map((c) => c.id));
    for (const id of [...this._picked]) if (!ids.has(id)) this._picked.delete(id);
    const n = this._picked.size;
    const all = clips.length && clips.every((c) => this._picked.has(c.id));
    const pickAll = `<label class="pickall"><input type="checkbox" data-pick-all="1" ${all ? "checked" : ""}> Select all shown</label>`;
    if (!n) return `<div class="bulk">${pickAll}</div>`;
    return `<div class="bulk on">${pickAll}<b>${n} selected:</b>
      <select data-bulk-assign="1"><option value="">That was…</option>${opts}<option value="other">Someone else / the TV</option></select>
      <button class="small danger" data-bulk-delete="1">Delete</button><button class="small" data-bulk-clear="1">Clear</button></div>`;
  }

  _recordings() {
    if (this._clips === null) { this._loadClips(); return `<div class="card"><p class="lead">Loading…</p></div>`; }
    const clips = this._shown();
    const opts = this._people.map((p) => `<option value="${this._esc(p.person)}">${this._esc(p.name)}</option>`).join("");
    const sel = (v) => (this._filter === v ? "selected" : "");
    const filters = `<select data-filter-select="1">
        <option value="all" ${sel("all")}>All recordings</option>
        <option value="unsure" ${sel("unsure")}>Not sure who</option>
        <option value="unlabelled" ${sel("unlabelled")}>Not labelled yet</option>
        <option value="train" ${sel("train")}>Training</option>
        <option value="other" ${sel("other")}>Someone else / the TV</option>
        ${this._people.map((p) => `<option value="${this._esc(p.person)}" ${sel(p.person)}>${this._esc(p.name)}</option>`).join("")}
      </select>
      <select data-sort-select="1">
        <option value="newest" ${this._sort === "newest" ? "selected" : ""}>Newest first</option>
        <option value="oldest" ${this._sort === "oldest" ? "selected" : ""}>Oldest first</option>
        <option value="weakest" ${this._sort === "weakest" ? "selected" : ""}>Weakest match first</option>
      </select>
      <span class="count">${clips.length} of ${this._clips.length}</span>`;
    const rows = clips.map((c) => {
      const meta = [this._when(c.when), c.speaker, c.seconds ? `${c.seconds}s` : "",
                    c.match && typeof c.match.score === "number" ? `match ${Math.round(c.match.score * 100)}` : ""]
        .filter(Boolean).join(" · ");
      const on = this._picked.has(c.id) ? "checked" : "";
      return `<div class="clip ${on ? "picked" : ""}"><div class="line1"><input type="checkbox" class="pick" data-pick="${this._esc(c.id)}" ${on}>
        <span class="heard">“${this._esc(c.transcript || "…")}”</span>${this._chip(c)}</div>
        <div class="meta">${this._esc(meta)}</div>
        <div class="acts"><button class="small" data-play="${this._esc(c.url)}">▶ Play</button>
          <select data-assign="${this._esc(c.id)}"><option value="">That was…</option>${opts}
            <option value="other">Someone else / the TV</option></select>
          <button class="small danger" data-delete="${this._esc(c.id)}">Delete</button></div></div>`;
    }).join("") || `<p class="empty">${this._filter === "all" ? "No recordings yet." : "Nothing here."}</p>`;
    return `<div class="card"><h3>Recordings</h3>
      <p class="lead">What your speakers heard and who voice match thought it was. Fix a mistake with
        "That was…" and voice match learns from it. Everyday recordings are deleted after 14 days unless you label them.</p>
      <div class="filters">${filters}</div>
      ${this._bulk(clips, opts)}
      ${rows}</div>`;
  }

  _body() {
    const v = this._view;
    if (!v) return `<div class="card"><p class="lead">${this._esc(this._error || "Loading…")}</p></div>`;
    const err = this._error ? `<div class="card error">${this._esc(this._error)}</div>` : "";
    return err + (this._tab === "training" ? this._training(v) + this._match(v) : this._recordings());
  }

  _render() {
    if (!this.shadowRoot.querySelector(".wrap")) {
      this.shadowRoot.innerHTML = `<style>${VOICE_CSS}</style>
        <div class="tabs"><button class="tab" data-tab="training">Training</button><button class="tab" data-tab="recordings">Recordings</button></div>
        <div class="wrap"></div><audio class="player" preload="none"></audio>`;
      this.shadowRoot.addEventListener("click", (ev) => this._click(ev));
      this.shadowRoot.addEventListener("change", (ev) => {
        const d = ev.target.dataset || {};
        if (d.assign && ev.target.value) this._clipAction("assign", d.assign, ev.target.value);
        else if (d.pick) { ev.target.checked ? this._picked.add(d.pick) : this._picked.delete(d.pick); this._render(); }
        else if (d.pickAll) {
          const shown = this._shown().map((c) => c.id);
          shown.forEach((id) => (ev.target.checked ? this._picked.add(id) : this._picked.delete(id)));
          this._render();
        }
        else if (d.bulkAssign && ev.target.value) this._clipAction("assign", [...this._picked], ev.target.value);
        else if (d.filterSelect) { this._filter = ev.target.value; this._render(); }
        else if (d.sortSelect) { this._sort = ev.target.value; this._render(); }
      });
    }
    this.shadowRoot.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.dataset.tab === this._tab));
    this.shadowRoot.querySelector(".wrap").innerHTML = this._body();
  }

  _click(ev) {
    const b = ev.target.closest("button");
    if (!b) return;
    const d = b.dataset;
    if (d.tab) { this._tab = d.tab; if (d.tab === "recordings") this._clips = null; this._error = ""; this._render(); }
    else if (d.a) this._act(d.a);
    else if (d.play) {
      // one player kept outside the part that redraws, so moving or deleting doesn't cut it off
      const player = this.shadowRoot.querySelector("audio.player");
      player.pause(); player.src = d.play;
      player.play().catch((e) => {
        if (e && e.name === "AbortError") return;           // interrupted by the next Play: not a problem
        this._error = `Couldn't play it: ${e}`; this._render();
      });
    }
    else if (d.delete) this._clipAction("delete", d.delete);
    else if (d.bulkDelete) this._clipAction("delete", [...this._picked]);
    else if (d.bulkClear) { this._picked.clear(); this._render(); }
    else if (d.delPerson) this._clipAction("delete_person", null, d.p);
  }

  connectedCallback() { this._render(); }
}

customElements.define("better-assistant-voice-view", BetterAssistantVoiceView);


// ------------------------------------------------------------------ the app
// One subscription (better_assistant/app/subscribe) carries everything the Home, Alarms and Settings
// pages show; changes go back through better_assistant/app/alarm, /item, /settings and /fix.

const APP_CSS = `
  :host { display: block; min-height: 100vh; background: var(--primary-background-color);
          color: var(--primary-text-color); font-family: var(--paper-font-body1_-_font-family, inherit); }
  .top { display: flex; align-items: center; height: 56px; padding: 0 4px; position: sticky; top: 0; z-index: 3;
         background: var(--app-header-background-color, var(--primary-color));
         color: var(--app-header-text-color, #fff); font-size: 20px; }
  .top .title { margin-left: 8px; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  nav { display: flex; gap: 6px; max-width: 680px; margin: 16px auto 0; padding: 0 16px; box-sizing: border-box; }
  nav button { flex: 1; display: flex; align-items: center; justify-content: center; gap: 6px; padding: 10px 6px;
               border-radius: 12px; border: 1px solid var(--divider-color); background: transparent; cursor: pointer;
               color: var(--secondary-text-color); font: inherit; font-weight: 600; font-size: 15px; }
  nav button.on { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: transparent; }
  nav ha-icon { --mdc-icon-size: 20px; }
  :host([narrow]) nav { position: fixed; bottom: 0; left: 0; right: 0; z-index: 3; margin: 0; max-width: none; gap: 0;
         padding: 6px 4px calc(6px + env(safe-area-inset-bottom, 0px)); background: var(--card-background-color);
         border-top: 1px solid var(--divider-color); }
  :host([narrow]) nav button { flex-direction: column; gap: 2px; border: none; font-size: 12px; padding: 6px 2px; border-radius: 14px; }
  :host([narrow]) nav button.on { background: transparent; color: var(--primary-color); }
  :host([narrow]) nav button.on ha-icon { background: rgba(var(--rgb-primary-color, 3, 169, 244), .16);
         border-radius: 14px; padding: 2px 16px; }
  .wrap { max-width: 680px; margin: 0 auto; padding: 16px 16px 48px; box-sizing: border-box; }
  :host([narrow]) .wrap { padding-bottom: calc(96px + env(safe-area-inset-bottom, 0px)); }
  .card { background: var(--card-background-color); border-radius: 16px; padding: 20px;
          box-shadow: var(--ha-card-box-shadow, none); border: 1px solid var(--divider-color); margin-bottom: 16px; }
  h2 { font-size: 22px; margin: 0 0 4px; }
  h3 { margin: 0 0 4px; font-size: 18px; display: flex; align-items: center; gap: 8px; }
  h3 .grow { flex: 1; }
  .lead { color: var(--secondary-text-color); font-size: 15px; line-height: 1.45; margin: 0 0 12px; }
  .muted { color: var(--secondary-text-color); font-size: 14px; }
  .hero { display: flex; gap: 14px; align-items: center; }
  .hero .icon { width: 52px; height: 52px; border-radius: 50%; display: grid; place-items: center; flex: none;
                background: rgba(var(--rgb-success-color, 67, 160, 71), .15); color: var(--success-color, #43a047); }
  .hero .icon.warn { background: rgba(var(--rgb-warning-color, 240, 160, 32), .15); color: var(--warning-color, #f0a020); }
  .hero .icon ha-icon { --mdc-icon-size: 30px; }
  .row { display: flex; align-items: center; gap: 12px; padding: 12px 0; border-top: 1px solid var(--divider-color); }
  .row:first-of-type { border-top: none; }
  .row .main { flex: 1; min-width: 0; }
  .row .name { font-size: 16px; font-weight: 500; }
  .row .sub { color: var(--secondary-text-color); font-size: 14px; margin-top: 2px; }
  .row ha-icon { color: var(--secondary-text-color); flex: none; }
  .row.attn ha-icon { color: var(--warning-color, #f0a020); }
  .row.attn, .row.alarm { flex-wrap: wrap; }
  .row.alarm .main { min-width: 55%; }
  :host([narrow]) .row.attn .main { flex-basis: calc(100% - 40px); }
  :host([narrow]) .row.attn .acts { flex-basis: 100%; }
  .acts { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
  .tile { border: 1px solid var(--divider-color); border-radius: 14px; padding: 12px 14px; cursor: default; }
  .tile.go { cursor: pointer; }
  .tile ha-icon { color: var(--primary-color); --mdc-icon-size: 22px; }
  .tile .k { color: var(--secondary-text-color); font-size: 13px; margin-top: 6px; }
  .tile .v { font-size: 16px; font-weight: 600; margin-top: 2px; }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; }
  .say { border-radius: 18px; padding: 8px 14px; font-size: 14px; background: rgba(var(--rgb-primary-color, 3, 169, 244), .1);
         color: var(--primary-text-color); }
  .chip { font-size: 12px; border-radius: 10px; padding: 2px 8px; border: 1px solid var(--divider-color); white-space: nowrap; }
  .chip.ok { border-color: var(--success-color, #43a047); color: var(--success-color, #43a047); }
  .chip.warn { border-color: var(--warning-color, #f0a020); color: var(--warning-color, #f0a020); }
  .chip.ring { border-color: var(--error-color, #db4437); color: var(--error-color, #db4437); }
  button { font: inherit; font-size: 14px; border-radius: 20px; padding: 8px 16px; cursor: pointer; white-space: nowrap;
           border: 1px solid var(--divider-color); background: transparent; color: var(--primary-text-color); }
  button.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: transparent; font-weight: 600; }
  button.danger { color: var(--error-color, #db4437); }
  button.wide { width: 100%; padding: 12px; font-size: 16px; }
  button:disabled { opacity: .5; cursor: default; }
  .time { font-size: 30px; font-weight: 600; line-height: 1.1; font-variant-numeric: tabular-nums; }
  .sound-note { margin: -4px 0 0; font-size: 13px; color: var(--secondary-text-color); }
  .form { display: grid; gap: 12px; padding: 14px; margin: 8px 0 4px; border-radius: 14px;
          background: rgba(var(--rgb-primary-color, 3, 169, 244), .06); border: 1px solid var(--divider-color); }
  .form label, .field { display: grid; gap: 4px; font-size: 13px; color: var(--secondary-text-color); }
  input[type=time], input[type=number], input[type=text], select {
    font: inherit; font-size: 16px; padding: 9px 10px; border-radius: 10px; min-width: 0; box-sizing: border-box; width: 100%;
    background: var(--card-background-color); color: var(--primary-text-color); border: 1px solid var(--divider-color); }
  input[type=time] { font-size: 22px; }
  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .setting { display: flex; align-items: center; gap: 12px; padding: 12px 0; border-top: 1px solid var(--divider-color); }
  .setting:first-of-type { border-top: none; }
  .setting .main { flex: 1; min-width: 0; }
  .setting .name { font-size: 16px; }
  .setting .sub { color: var(--secondary-text-color); font-size: 13px; margin-top: 2px; line-height: 1.35; }
  .setting select { width: auto; max-width: 55%; }
  .setting input[type=number] { width: auto; max-width: 120px; }
  .setting .inline { display: flex; gap: 8px; flex: 1; }
  .switch { position: relative; width: 46px; height: 28px; flex: none; }
  .switch input { opacity: 0; width: 100%; height: 100%; margin: 0; position: absolute; cursor: pointer; z-index: 1; }
  .switch span { position: absolute; inset: 0; border-radius: 14px; background: var(--disabled-color, #bdbdbd); transition: .2s; }
  .switch span::after { content: ""; position: absolute; top: 3px; left: 3px; width: 22px; height: 22px; border-radius: 50%;
                        background: #fff; transition: .2s; box-shadow: 0 1px 3px rgba(0,0,0,.3); }
  .switch input:checked + span { background: var(--primary-color); }
  .switch input:checked + span::after { transform: translateX(18px); }
  .switch input:disabled { cursor: default; }
  .switch input:disabled + span { opacity: .5; }
  details { border-top: 1px solid var(--divider-color); padding-top: 10px; margin-top: 10px; }
  summary { cursor: pointer; font-weight: 600; padding: 4px 0; }
  .note { font-size: 14px; padding: 10px 14px; border-radius: 12px; margin-bottom: 16px;
          background: rgba(var(--rgb-warning-color, 240, 160, 32), .12); }
  .error { color: var(--error-color, #db4437); }
  .toast { position: fixed; left: 50%; transform: translateX(-50%); bottom: 24px; z-index: 5; max-width: 90vw;
           background: var(--primary-text-color); color: var(--primary-background-color); padding: 10px 18px;
           border-radius: 20px; font-size: 14px; box-shadow: 0 2px 8px rgba(0,0,0,.3); }
  :host([narrow]) .toast { bottom: calc(84px + env(safe-area-inset-bottom, 0px)); }
  .empty { color: var(--secondary-text-color); padding: 8px 0; }
`;

const PAGES = [["home", "Home", "mdi:home-heart"], ["alarms", "Alarms", "mdi:alarm"],
               ["voice", "Voice", "mdi:account-voice"], ["settings", "Settings", "mdi:cog"]];
const REPEAT_NAMES = { once: "Once", daily: "Every day", weekdays: "Weekdays", weekends: "Weekends" };

class BetterAssistantApp extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._view = null; this._page = "home"; this._edit = null; this._error = ""; this._toast = "";
    const hash = (window.location.hash || "").slice(1);
    if (PAGES.some((p) => p[0] === hash)) this._page = hash;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (this._menu) this._menu.hass = hass;
    if (this._voice) this._voice.hass = hass;
    if (first) this._subscribe();
  }

  set narrow(narrow) {
    this._narrow = narrow;
    this.toggleAttribute("narrow", !!narrow);
    if (this._menu) this._menu.narrow = narrow;
  }

  set panel(panel) { this._panel = panel; }

  connectedCallback() {
    this._render();
    if (this._hass && !this._unsub) this._subscribe();
  }

  disconnectedCallback() { if (this._unsub) { this._unsub(); this._unsub = null; } }

  async _subscribe() {
    if (this._unsub) { try { this._unsub(); } catch (e) { /* already gone */ } this._unsub = null; }
    try {
      this._unsub = await this._hass.connection.subscribeMessage(
        (view) => { this._view = view; this._render(); }, { type: "better_assistant/app/subscribe" });
      this._error = "";
    } catch (err) {
      this._error = "Better Assistant isn't running. Check it under Settings > Devices & services.";
      setTimeout(() => this._hass && this._subscribe(), 5000);
    }
    this._render();
  }

  _esc(s) { return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

  _say(text) {
    this._toast = text; this._render();
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => { this._toast = ""; this._render(); }, 2600);
  }

  async _ws(msg, done) {
    try {
      const res = await this._hass.callWS(msg);
      if (done) this._say(done);
      return res || {};
    } catch (err) {
      this._say(err.message || String(err));
      return null;
    }
  }

  _navigate(path) {
    history.pushState(null, "", path);
    window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
  }

  _go(page) {
    this._page = page; this._edit = null;
    history.replaceState(null, "", `${window.location.pathname}#${page}`);
    if (page === "voice" && this._voice) this._voice.refresh();
    this._render();
    window.scrollTo(0, 0);
  }

  _clock(hhmm) {
    const [h, m] = hhmm.split(":").map(Number);
    const d = new Date(2000, 0, 1, h, m);
    return d.toLocaleTimeString(this._hass && this._hass.locale ? this._hass.locale.language : undefined,
                                { hour: "numeric", minute: "2-digit" });
  }

  _switch(attrs, on, disabled) {
    return `<label class="switch"><input type="checkbox" role="switch" ${attrs} ${on ? "checked" : ""} ${disabled ? "disabled" : ""}><span></span></label>`;
  }

  // ------------------------------------------------------------ home
  _home(v) {
    const h = v.home;
    const att = h.attention.map((a, i) => {
      const fix = a.fix && v.admin ? `<button class="primary" data-fix="${i}">${this._esc(a.fix_label || "Fix it")}</button>` : "";
      const link = a.link ? `<button data-link="${this._esc(a.link)}">Open</button>` : "";
      const go = a.goto ? `<button data-goto="${this._esc(a.goto)}">Show me</button>` : "";
      return `<div class="row attn"><ha-icon icon="mdi:alert-circle-outline"></ha-icon>
        <div class="main"><div class="sub" style="color:var(--primary-text-color);font-size:15px">${this._esc(a.text)}</div></div>
        <div class="acts">${fix || link || go}</div></div>`;
    }).join("");
    const n = h.attention.length;
    const ours = h.speakers.filter((s) => s.ours).length;
    const hero = `<div class="card"><div class="hero">
        <div class="icon ${n ? "warn" : ""}"><ha-icon icon="${n ? "mdi:alert-outline" : "mdi:check-bold"}"></ha-icon></div>
        <div><h2>${n ? `${n} thing${n === 1 ? "" : "s"} to look at` : "All set"}</h2>
        <div class="muted">${ours ? `Answering on ${ours} speaker${ours === 1 ? "" : "s"}.` : "Not answering on any speaker yet."}</div></div>
      </div>${att ? `<div style="margin-top:8px">${att}</div>` : ""}</div>`;
    const speakers = h.speakers.map((s) => `<div class="row"><ha-icon icon="mdi:speaker-message"></ha-icon>
        <div class="main"><div class="name">${this._esc(s.name)}</div>
        <div class="sub">${this._esc(s.area || "No room")}${s.online ? "" : " · offline"}</div></div>
        ${s.ours ? '<span class="chip ok">Better Assistant ✓</span>'
                 : `<span class="chip warn">${this._esc(s.pipeline || "Another assistant")}</span>`}</div>`).join("")
      || `<p class="empty">No voice speakers yet.</p>`;
    const next = v.alarms.find((a) => !a.ringing) || v.alarms[0];
    const s = h.search;
    const tiles = [
      ["mdi:alarm", "Next alarm", next ? this._clock(next.time) : "None", "alarms"],
      ["mdi:music", "Music", h.music ? "Ready" : "Not set up", null],
      ["mdi:calendar", "Calendars", h.calendars.length ? String(h.calendars.length) : "None", null],
      ["mdi:web", "Web answers", !s.on ? "Off" : !s.key ? "No key" : `${s.count} of ${s.cap}`, "settings"],
      ["mdi:account-voice", "Voice match", { ready: "On", downloading: "Getting ready", error: "Problem", off: "Off" }[h.match] || "Off", "voice"],
      ["mdi:bell-ring-outline", "Reminders", String(v.reminders.length), "alarms"],
    ].map(([icon, k, val, go]) => `<div class="tile ${go ? "go" : ""}" ${go ? `data-goto="${go}"` : ""}>
        <ha-icon icon="${icon}"></ha-icon><div class="k">${k}</div><div class="v">${this._esc(val)}</div></div>`).join("");
    const tries = h.try.map((t) => `<span class="say">“${this._esc(t)}”</span>`).join("");
    return `${hero}
      <div class="card"><h3>Speakers</h3><p class="lead">Your voice speakers and the assistant each one uses.</p>${speakers}</div>
      <div class="card"><h3>At a glance</h3><div class="grid" style="margin-top:10px">${tiles}</div></div>
      <div class="card"><h3>Try saying</h3><p class="lead">Say the wake word first, then:</p><div class="chips">${tries}</div></div>`;
  }

  // ------------------------------------------------------------ alarms & reminders
  // what an alarm wakes you with: picked from v.sounds ([{value, label}]), never typed
  _soundLabel(value) {
    const s = (this._view.sounds || []).find((x) => x.value === value);
    if (s) return s.label;
    const m = /^ma:[^:]+:.*\|(.*)$/.exec(value || "");
    return m ? m[1] : value;
  }

  _sound(music) {
    if (!music) return "";
    if (music === "tone") return "alarm sound";
    if (music === "default") return "wake-up music";
    if (music === "last") return "plays whatever played last";
    const m = /^ma:([^:]+):.*\|(.*)$/.exec(music);
    if (m) return m[1] === "artist" ? `plays music like ${m[2]}` : `plays ${m[2]}`;
    return `plays ${music}`;
  }

  _alarmForm(v) {
    const e = this._edit;
    const speakers = v.speakers.map((s) => `<option value="${this._esc(s.value)}" ${e.target === s.value ? "selected" : ""}>${this._esc(s.label)}</option>`).join("");
    const reps = Object.entries(REPEAT_NAMES).map(([k, n]) => `<option value="${k}" ${e.repeat === k ? "selected" : ""}>${n}</option>`).join("");
    // "" = whatever the wake-up setting says, "tone" = the alarm sound, else one of the library choices
    const setting = v.alarm_settings.music ? `Wake-up music (${this._esc(this._soundLabel(v.alarm_settings.music))})`
                                           : "Wake-up setting (alarm sound)";
    const choices = [["", setting], ["tone", "Alarm sound (just say \"stop\")"],
                     ...(v.sounds || []).filter((s) => s.value).map((s) => [s.value, s.label])];
    if (e.music && !choices.some(([k]) => k === e.music)) choices.push([e.music, this._soundLabel(e.music)]);
    const sounds = choices.map(([k, n]) => `<option value="${this._esc(k)}" ${e.music === k ? "selected" : ""}>${this._esc(n)}</option>`).join("");
    return `<div class="form">
      <label>Time<input type="time" data-f="time" value="${this._esc(e.time)}"></label>
      <div class="two">
        <label>Repeat<select data-f="repeat">${reps}</select></label>
        <label>Speaker<select data-f="target"><option value="all" ${e.target === "all" ? "selected" : ""}>All voice speakers</option>${speakers}</select></label>
      </div>
      <label>Sound<select data-f="music">${sounds}</select></label>
      <p class="sound-note">Only the alarm sound stops on a plain "stop". Music stops with your wake word first ("Hey Jarvis, stop") or the speaker's button.</p>
      <div class="acts" style="justify-content:flex-start"><button class="primary" data-alarm-save="1">${e.key ? "Save" : "Add alarm"}</button>
        <button data-alarm-cancel="1">Cancel</button></div></div>`;
  }

  _alarms(v) {
    const add = !this._edit || this._edit.key ? `<button class="primary" data-alarm-new="1">+ Add</button>` : "";
    const rows = v.alarms.map((a) => {
      if (this._edit && this._edit.key === a.key) return this._alarmForm(v);
      const status = a.ringing ? '<span class="chip ring">Ringing</span>' : a.snoozed ? '<span class="chip warn">Snoozed</span>' : "";
      const day = a.repeat === "once" ? a.said.replace(/ at .*$/, "") : (REPEAT_NAMES[a.repeat] || a.repeat);
      const bits = [a.where, this._sound(a.music)].filter(Boolean).join(" · ");
      const acts = a.ringing || a.snoozed
        ? `<button class="primary" data-alarm-stop="${this._esc(a.key)}">Stop</button>`
        : `<button data-alarm-edit="${this._esc(a.key)}">Change</button><button class="danger" data-alarm-delete="${this._esc(a.key)}">Delete</button>`;
      return `<div class="row alarm"><div class="main"><div class="time">${this._clock(a.time)}</div>
        <div class="sub">${this._esc(day.charAt(0).toUpperCase() + day.slice(1))}${status ? " " + status : ""}</div>
        <div class="sub">${this._esc(bits)}</div></div>
        <div class="acts">${acts}</div></div>`;
    }).join("");
    const newForm = this._edit && !this._edit.key ? this._alarmForm(v) : "";
    const empty = !v.alarms.length && !newForm ? `<p class="empty">No alarms. Add one here or say "set an alarm for 7".</p>` : "";
    const st = v.alarm_settings;
    const dis = v.admin ? "" : "disabled";
    const limits = [["", "No limit"], ...Array.from({ length: 10 }, (_, i) => [String(i + 1), String(i + 1)])]
      .map(([k, n]) => `<option value="${k}" ${String(st.snooze_limit ?? "") === k ? "selected" : ""}>${n}</option>`).join("");
    const lengths = [1, 2, 3, 5, 7, 9, 10, 15, 20, 30].concat(st.snooze).filter((x, i, a) => a.indexOf(x) === i).sort((a, b) => a - b)
      .map((m) => `<option value="${m}" ${st.snooze === m ? "selected" : ""}>${m} min</option>`).join("");
    const where = [["", "Speaker you ask"], ["all", "All speakers"], ...v.speakers.map((s) => [s.value, s.label])]
      .map(([k, n]) => `<option value="${this._esc(k)}" ${st.speaker === k ? "selected" : ""}>${this._esc(n)}</option>`).join("");
    const settings = `<div class="card"><h3>Alarm settings</h3>
      ${v.admin ? "" : '<p class="lead">Only an administrator can change these.</p>'}
      <div class="setting"><div class="main"><div class="name">Snooze</div><div class="sub">Off: the alarm rings until you stop it.</div></div>
        ${this._switch('data-set="snooze_enabled"', st.snooze_enabled, !v.admin)}</div>
      ${st.snooze_enabled ? `<div class="setting"><div class="main"><div class="name">Snooze length</div></div>
        <select data-set="snooze_minutes" ${dis}>${lengths}</select></div>
      <div class="setting"><div class="main"><div class="name">Snoozes per alarm</div></div>
        <select data-set="snooze_limit" ${dis}>${limits}</select></div>` : ""}
      <div class="setting"><div class="main"><div class="name">Rings on</div><div class="sub">When you don't say where.</div></div>
        <select data-set="alarm_speaker" ${dis}>${where}</select></div>
      <div class="setting"><div class="main"><div class="name">Wake up to</div>
        <div class="sub">${st.music_ready ? "The alarm sound stops when you just say \"stop\". Music stops with your wake word first (\"Hey Jarvis, stop\") or the speaker's button." :
          "Music needs Music Assistant. Until then alarms ring with the alarm sound."}</div></div>
        <select data-set="alarm_music" ${dis}>${(v.sounds || [{ value: "", label: "Alarm sound" }]).map((s) =>
          `<option value="${this._esc(s.value)}" ${st.music === s.value ? "selected" : ""}>${this._esc(s.label)}</option>`).join("")}</select></div></div>`;
    const list = (items, kind, empty) => items.map((i) => `<div class="row"><div class="main"><div class="name">${this._esc(i.summary)}</div>
        ${i.when ? `<div class="sub">${this._esc(i.when)}</div>` : ""}</div>
        <button class="danger" data-item="${kind}" data-uid="${this._esc(i.uid)}">Delete</button></div>`).join("")
      || `<p class="empty">${empty}</p>`;
    return `<div class="card"><h3><span class="grow">Alarms</span>${add}</h3>${newForm}${rows}${empty}</div>
      <div class="card"><h3>Reminders</h3>${list(v.reminders, "reminders", 'None. Say "remind me to call Mom at 5".')}
        <details><summary>Notes (${v.notes.length})</summary>${list(v.notes, "notes", "No notes.")}</details>
        <details><summary>Messages (${v.messages.length})</summary>${list(v.messages, "messages", "No messages.")}</details></div>
      ${settings}`;
  }

  _startEdit(key) {
    const v = this._view;
    if (key) {
      const a = v.alarms.find((x) => x.key === key);
      if (!a) return;
      const music = a.music || "";
      this._edit = { key, time: a.time, repeat: a.repeat, target: a.targets === "all" ? "all" : a.targets[0],
                     music: music === "default" ? "" : music };
    } else {
      this._edit = { key: null, time: "07:00", repeat: "once",
                     target: v.alarm_settings.speaker || (v.speakers[0] ? v.speakers[0].value : "all"),
                     music: "" };
    }
    this._render();
  }

  async _saveAlarm() {
    const e = this._edit;
    if (!e.time) { this._say("Pick a time."); return; }
    const music = e.music || "";
    const res = await this._ws({ type: "better_assistant/app/alarm", action: e.key ? "change" : "add",
                                 ...(e.key ? { key: e.key } : {}), time: e.time, repeat: e.repeat,
                                 targets: e.target === "all" ? "all" : [e.target], music },
                               e.key ? "Alarm changed" : "Alarm added");
    if (res) { this._edit = null; this._render(); }
  }

  // ------------------------------------------------------------ voice
  _voicePage(v) {
    if (v.voice.training_on) return "";
    return `<div class="card"><h3>Teach it your voice</h3>
      <p class="lead">Voice training records you saying 8 short phrases on your voice speaker. With voice match on,
        Better Assistant can then tell who's talking, so "my calendar" and "my reminders" work for whoever asks.
        Everything stays on this machine, and nothing is recorded until you start.</p>
      ${v.admin ? `<button class="primary wide" data-voice-on="1">Turn on voice training</button>`
                : '<p class="muted">Ask an administrator to turn on voice training.</p>'}</div>`;
  }

  // ------------------------------------------------------------ settings
  _settings(v) {
    const s = v.settings;
    const dis = !v.admin;
    const feats = s.features.map((f) => `<div class="setting"><div class="main"><div class="name">${this._esc(f.name)}</div>
        <div class="sub">${this._esc(f.about)}</div></div>${this._switch(`data-feature="${f.key}"`, f.on, dis)}</div>`).join("");
    const parts = [2, 3, 4].map((n) => `<option value="${n}" ${s.max_compound_parts === n ? "selected" : ""}>${n}</option>`).join("");
    return `${v.admin ? "" : '<div class="note">Only an administrator can change settings.</div>'}
      <div class="card"><h3>What it can do</h3><p class="lead">Turn off anything you don't use. Changes take a few seconds.</p>${feats}</div>
      <div class="card"><h3>Web answers</h3>
        <p class="lead">General questions ("how tall is Mount Everest?") are looked up with Brave Search. No AI writes the answer.
          ${s.has_key ? "" : "<br><b>There's no Brave Search key yet</b>: add one under More settings, then Reconfigure."}</p>
        <div class="setting"><div class="main"><div class="name">Look things up on the web</div></div>
          ${this._switch('data-set="web_search"', s.web_search, dis)}</div>
        <div class="setting"><div class="main"><div class="name">Searches per month</div>
          <div class="sub">${v.home.search.count} used this month. Searches stop at this number until next month.</div></div>
          <input type="number" min="0" max="100000" data-set="monthly_cap" value="${s.monthly_cap}" ${dis ? "disabled" : ""}></div>
        <div class="setting"><div class="main"><div class="name">Say where the answer came from</div></div>
          ${this._switch('data-set="speak_source"', s.speak_source, dis)}</div></div>
      <div class="card"><h3>Understanding</h3>
        <div class="setting"><div class="main"><div class="name">Only search for questions</div>
          <div class="sub">Something misheard gets "Sorry, I didn't catch that." instead of a web search.</div></div>
          ${this._switch('data-set="question_guard"', s.question_guard, dis)}</div>
        <div class="setting"><div class="main"><div class="name">Several things at once</div>
          <div class="sub">"Turn off the lamp and play the news".</div></div>
          ${this._switch('data-set="compound_commands"', s.compound_commands, dis)}</div>
        ${s.compound_commands ? `<div class="setting"><div class="main"><div class="name">Most things in one request</div></div>
          <select data-set="max_compound_parts" ${dis ? "disabled" : ""}>${parts}</select></div>` : ""}</div>
      <div class="card"><h3>More settings</h3><p class="lead">Devices for each feature, the voice passphrase, voice setup and the rest.</p>
        <button class="wide" data-link="/config/integrations/integration/better_assistant">Open all settings</button></div>`;
  }

  async _setOption(key, value) {
    await this._ws({ type: "better_assistant/app/settings", values: { [key]: value } }, "Saved");
  }

  // ------------------------------------------------------------ frame
  _body() {
    const v = this._view;
    if (!v) return `<div class="card"><p class="lead">${this._esc(this._error || "Loading…")}</p></div>`;
    if (!v.running) return `<div class="card"><h3>Better Assistant isn't running</h3>
      <p class="lead">Check it under Settings > Devices & services. This page comes back on its own once it's running.</p></div>`;
    if (this._page === "alarms") return this._alarms(v);
    if (this._page === "voice") return this._voicePage(v);
    if (this._page === "settings") return this._settings(v);
    return this._home(v);
  }

  _render() {
    const root = this.shadowRoot;
    if (!root.querySelector(".wrap")) {
      root.innerHTML = `<style>${APP_CSS}</style>
        <div class="top"><ha-menu-button></ha-menu-button><span class="title">Better Assistant</span></div>
        <nav>${PAGES.map(([k, n, i]) => `<button data-page="${k}"><ha-icon icon="${i}"></ha-icon><span>${n}</span></button>`).join("")}</nav>
        <div class="wrap"><div class="page"></div><div class="voice"></div></div><div class="toastbox"></div>`;
      this._menu = root.querySelector("ha-menu-button");
      this._menu.hass = this._hass; this._menu.narrow = this._narrow;
      root.addEventListener("click", (ev) => this._click(ev));
      root.addEventListener("change", (ev) => this._change(ev));
      root.addEventListener("input", (ev) => {
        const f = ev.target.dataset && ev.target.dataset.f;
        if (f && this._edit && ev.target.type === "text") this._edit[f] = ev.target.value;   // no redraw while typing
      });
    }
    root.querySelectorAll("nav button").forEach((b) => b.classList.toggle("on", b.dataset.page === this._page));
    const page = root.querySelector(".page");
    const html = this._body();
    if (html !== this._drawn) { page.innerHTML = html; this._drawn = html; }   // unchanged: keep focus and typing
    // the Voice page is its own element, kept between visits so a running session stays live
    const voiceBox = root.querySelector(".voice");
    const showVoice = this._page === "voice" && this._view && this._view.running && this._view.voice.training_on;
    if (showVoice && !this._voice) {
      this._voice = document.createElement("better-assistant-voice-view");
      this._voice.hass = this._hass;
      voiceBox.appendChild(this._voice);
    }
    voiceBox.style.display = showVoice ? "" : "none";
    root.querySelector(".toastbox").innerHTML = this._toast ? `<div class="toast">${this._esc(this._toast)}</div>` : "";
  }

  _click(ev) {
    const t = ev.target.closest("button, .tile.go");
    if (!t) return;
    const d = t.dataset;
    const v = this._view;
    if (d.page) this._go(d.page);
    else if (d.goto) this._go(d.goto);
    else if (d.link) this._navigate(d.link);
    else if (d.fix !== undefined) {
      const a = v.home.attention[Number(d.fix)];
      if (a && a.fix) this._ws({ type: "better_assistant/app/fix", ...a.fix }, "Done");
    }
    else if (d.alarmNew) this._startEdit(null);
    else if (d.alarmEdit) this._startEdit(d.alarmEdit);
    else if (d.alarmCancel) { this._edit = null; this._render(); }
    else if (d.alarmSave) this._saveAlarm();
    else if (d.alarmDelete) {
      if (confirm("Delete this alarm?")) this._ws({ type: "better_assistant/app/alarm", action: "delete", key: d.alarmDelete }, "Alarm deleted");
    }
    else if (d.alarmStop) this._ws({ type: "better_assistant/app/alarm", action: "stop", key: d.alarmStop }, "Alarm off");
    else if (d.item) {
      if (confirm("Delete it?")) this._ws({ type: "better_assistant/app/item", list: d.item, uid: d.uid }, "Deleted");
    }
    else if (d.voiceOn) this._ws({ type: "better_assistant/app/settings", values: { voice_training: true } },
                                 "Voice training is on");
  }

  _change(ev) {
    const el = ev.target;
    const d = el.dataset || {};
    if (d.f && this._edit) {
      this._edit[d.f] = el.value;
      return;
    }
    if (d.feature) {
      this._ws({ type: "better_assistant/app/settings", values: { features: { [d.feature]: el.checked } } },
               `${el.checked ? "Turned on" : "Turned off"}`);
      return;
    }
    if (!d.set) return;
    let value = el.type === "checkbox" ? el.checked : el.value;
    if (["monthly_cap", "max_compound_parts", "snooze_minutes"].includes(d.set)) value = Number(value);
    if (d.set === "snooze_limit") value = value === "" ? null : Number(value);
    if (d.set === "alarm_speaker") value = value || null;
    this._setOption(d.set, value);
  }
}

customElements.define("better-assistant-app", BetterAssistantApp);
