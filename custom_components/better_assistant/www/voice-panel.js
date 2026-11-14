// Better Assistant: the Voice training page in the sidebar.
// Training: a live view of the session (better_assistant/voice_training/subscribe) with Start, Skip
// and Stop, plus voice match status per person. Recordings: what the speakers heard, who voice match
// thought it was, with play, "That was..." and delete. No build step, no dependencies.

const CSS = `
  :host { display: block; min-height: 100vh; background: var(--primary-background-color);
          color: var(--primary-text-color); font-family: var(--paper-font-body1_-_font-family, inherit); }
  .top { display: flex; align-items: center; height: 56px; padding: 0 4px;
         background: var(--app-header-background-color, var(--primary-color));
         color: var(--app-header-text-color, #fff); font-size: 20px; }
  .top .title { margin-left: 8px; }
  .tabs { display: flex; gap: 4px; max-width: 640px; margin: 16px auto 0; padding: 0 16px; box-sizing: border-box; }
  .tab { flex: 1; text-align: center; padding: 10px; border-radius: 12px; cursor: pointer; font-weight: 600;
         color: var(--secondary-text-color); border: 1px solid var(--divider-color); background: transparent; font: inherit; }
  .tab.on { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: transparent; }
  .wrap { max-width: 640px; margin: 0 auto; padding: 16px 16px 48px; box-sizing: border-box; }
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

class BetterAssistantVoicePanel extends HTMLElement {
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
    if (this._menu) this._menu.hass = hass;
  }

  set narrow(narrow) { this._narrow = narrow; if (this._menu) this._menu.narrow = narrow; }

  async _subscribe() {
    if (this._unsub) { try { this._unsub(); } catch (e) { /* already gone */ } this._unsub = null; }
    try {
      this._unsub = await this._hass.connection.subscribeMessage(
        (view) => { this._view = view; this._render(); },
        { type: "better_assistant/voice_training/subscribe" });
      this._error = "";
    } catch (err) {
      this._error = "Voice training is turned off. Turn it on in Better Assistant's settings.";
    }
    this._render();
  }

  disconnectedCallback() { if (this._unsub) { this._unsub(); this._unsub = null; this._hass = null; } }

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
      this.shadowRoot.innerHTML = `<style>${CSS}</style>
        <div class="top"><ha-menu-button></ha-menu-button><span class="title">Voice training</span></div>
        <div class="tabs"><button class="tab" data-tab="training">Training</button><button class="tab" data-tab="recordings">Recordings</button></div>
        <div class="wrap"></div><audio class="player" preload="none"></audio>`;
      this._menu = this.shadowRoot.querySelector("ha-menu-button");
      this._menu.hass = this._hass; this._menu.narrow = this._narrow;
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

customElements.define("better-assistant-voice-panel", BetterAssistantVoicePanel);
