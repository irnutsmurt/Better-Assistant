// Better Assistant app (the sidebar page): Home, Alarms & reminders and Settings.
// One module, no build step, no dependencies; colours come from the Home Assistant theme.


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
               ["settings", "Settings", "mdi:cog"]];
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
    if (this._page === "settings") return this._settings(v);
    return this._home(v);
  }

  _render() {
    const root = this.shadowRoot;
    if (!root.querySelector(".wrap")) {
      root.innerHTML = `<style>${APP_CSS}</style>
        <div class="top"><ha-menu-button></ha-menu-button><span class="title">Better Assistant</span></div>
        <nav>${PAGES.map(([k, n, i]) => `<button data-page="${k}"><ha-icon icon="${i}"></ha-icon><span>${n}</span></button>`).join("")}</nav>
        <div class="wrap"><div class="page"></div></div><div class="toastbox"></div>`;
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
