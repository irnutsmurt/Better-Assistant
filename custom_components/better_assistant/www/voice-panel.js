// Better Assistant: the Voice training page in the sidebar.
// Live view of the training session (from the better_assistant/voice_training/subscribe command)
// with Start, Skip and Stop. No build step, no dependencies.

const CSS = `
  :host { display: block; min-height: 100vh; background: var(--primary-background-color);
          color: var(--primary-text-color); font-family: var(--paper-font-body1_-_font-family, inherit); }
  .top { display: flex; align-items: center; height: 56px; padding: 0 4px;
         background: var(--app-header-background-color, var(--primary-color));
         color: var(--app-header-text-color, #fff); font-size: 20px; }
  .top .title { margin-left: 8px; }
  .wrap { max-width: 560px; margin: 0 auto; padding: 24px 16px 48px; }
  .card { background: var(--card-background-color); border-radius: 16px; padding: 24px;
          box-shadow: var(--ha-card-box-shadow, none); border: 1px solid var(--divider-color); }
  .lead { color: var(--secondary-text-color); font-size: 15px; line-height: 1.5; margin: 0 0 20px; }
  .progress { color: var(--secondary-text-color); font-size: 14px; margin-bottom: 6px; }
  .bar { height: 6px; border-radius: 3px; background: var(--divider-color); overflow: hidden; margin-bottom: 22px; }
  .bar > div { height: 100%; background: var(--primary-color); transition: width .3s; }
  .say { font-size: 13px; text-transform: uppercase; letter-spacing: .08em; color: var(--secondary-text-color); }
  .now { font-size: 30px; font-weight: 600; line-height: 1.25; margin: 8px 0 14px; }
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
  .buttons { display: flex; gap: 12px; margin-top: 22px; }
  button { font: inherit; font-size: 16px; border-radius: 24px; padding: 12px 22px; cursor: pointer;
           border: 1px solid var(--divider-color); background: transparent; color: var(--primary-text-color); }
  button.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); border: none;
                   width: 100%; padding: 16px; font-size: 18px; font-weight: 600; }
  button:disabled { opacity: .5; cursor: default; }
  .big { font-size: 26px; font-weight: 600; margin: 0 0 8px; }
  .error { color: var(--error-color, #db4437); margin-top: 14px; }
`;

class BetterAssistantVoicePanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._view = null;
    this._error = "";
    this._busy = false;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._subscribe();
    if (this._menu) { this._menu.hass = hass; }
  }

  set narrow(narrow) { this._narrow = narrow; if (this._menu) this._menu.narrow = narrow; }

  async _subscribe() {
    try {
      this._unsub = await this._hass.connection.subscribeMessage(
        (view) => { this._view = view; this._render(); },
        { type: "better_assistant/voice_training/subscribe" });
    } catch (err) {
      this._error = "Voice training is turned off. Turn it on in Better Assistant's settings.";
      this._render();
    }
  }

  disconnectedCallback() { if (this._unsub) { this._unsub(); this._unsub = null; this._hass = null; } }

  async _act(action) {
    this._busy = true; this._error = ""; this._render();
    try {
      const res = await this._hass.callWS({ type: "better_assistant/voice_training/action", action });
      if (res && res.problem) this._error = res.problem;
    } catch (err) {
      this._error = err.message || String(err);
    }
    this._busy = false; this._render();
  }

  _esc(s) { return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

  _list(v) {
    const marks = { said: "✓", skipped: "–", current: "▶", waiting: "" };
    return `<ul>${v.phrases.map((p) => `<li class="${p.state}"><span class="mark">${marks[p.state]}</span>
      <span>${this._esc(p.text)}</span>${p.state === "skipped" ? '<span class="tag">skipped</span>' : ""}</li>`).join("")}</ul>`;
  }

  _body() {
    const v = this._view;
    if (!v) return `<p class="lead">${this._esc(this._error || "Loading…")}</p>`;
    const busy = this._busy ? "disabled" : "";
    const err = this._error ? `<div class="error">${this._esc(this._error)}</div>` : "";
    if (v.status === "training") {
      const cur = v.phrases.find((p) => p.state === "current");
      const done = v.phrases.filter((p) => p.state === "said" || p.state === "skipped").length;
      return `
        <div class="progress">Phrase ${Math.min(done + 1, v.total)} of ${v.total}</div>
        <div class="bar"><div style="width:${(done / v.total) * 100}%"></div></div>
        <div class="say">After the ding, say</div>
        <div class="now">${this._esc(cur ? cur.text : "")}</div>
        <div class="hint">${this._esc(v.hint || "")}</div>
        <div class="buttons"><button ${busy} data-a="skip">Skip</button><button ${busy} data-a="stop">Stop</button></div>
        ${this._list(v)}${err}`;
    }
    const start = `<button class="primary" ${busy} data-a="start">${v.status === "idle" ? "Start" : "Train again"}</button>`;
    if (v.status === "done" || v.status === "stopped") {
      const n = v.saved || 0;
      return `
        <p class="big">${v.status === "done" ? "All done" : "Stopped"}</p>
        <p class="lead">Saved ${n} recording${n === 1 ? "" : "s"} of ${this._esc(v.name || "your")}'s voice.</p>
        ${start}${this._list(v)}${err}`;
    }
    return `
      <p class="big">Teach Better Assistant your voice</p>
      <p class="lead">We're going to have you repeat some phrases on the screen. When you hear the ding,
        start saying the highlighted phrase to your voice speaker. There are 8, and it takes about a minute.</p>
      ${start}${err}`;
  }

  _render() {
    if (!this.shadowRoot.querySelector(".wrap")) {
      this.shadowRoot.innerHTML = `<style>${CSS}</style>
        <div class="top"><ha-menu-button></ha-menu-button><span class="title">Voice training</span></div>
        <div class="wrap"><div class="card"></div></div>`;
      this._menu = this.shadowRoot.querySelector("ha-menu-button");
      this._menu.hass = this._hass; this._menu.narrow = this._narrow;
      this.shadowRoot.querySelector(".card").addEventListener("click", (ev) => {
        const a = ev.target.closest("button")?.dataset.a;
        if (a) this._act(a);
      });
    }
    this.shadowRoot.querySelector(".card").innerHTML = this._body();
  }

  connectedCallback() { this._render(); }
}

customElements.define("better-assistant-voice-panel", BetterAssistantVoicePanel);
