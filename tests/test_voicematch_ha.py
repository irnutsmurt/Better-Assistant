"""Voice match inside a bare Home Assistant core: voiceprints rebuilt from clips on disk, who-is-speaking
read by the skills, and the Recordings tab (list, play permissions, "That was...", delete).
The model isn't downloaded here: a fake embedder stands in. Skipped when Home Assistant isn't installed."""
import asyncio
import json
import time
import types

import numpy as np
import pytest

pytest.importorskip("homeassistant")

from homeassistant import bootstrap, config_entries, loader  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402

from custom_components.better_assistant import voice_match as vmf, voice_panel  # noqa: E402
from custom_components.better_assistant.core import voicematch as vm  # noqa: E402
from custom_components.better_assistant.core.voicetrain import wav_bytes  # noqa: E402

rng = np.random.default_rng(3)
D = 192
ROB, LEILA = vm.unit(rng.normal(size=D)), vm.unit(rng.normal(size=D))


@pytest.fixture
async def hass(tmp_path):
    h = HomeAssistant(str(tmp_path))
    loader.async_setup(h)
    h.config_entries = config_entries.ConfigEntries(h, {})
    await bootstrap.async_load_base_functionality(h)
    h.states.async_set("person.rob", "home", {"friendly_name": "Rob", "user_id": "u-rob"})
    h.states.async_set("person.leila", "home", {"friendly_name": "Leila", "user_id": "u-leila"})
    yield h
    await h.async_stop(force=True)


def put(root, label, person, name, center, meta=None):
    """A clip with a cached embedding near `center` (so no model is needed)."""
    folder = root / label / person.split(".")[-1]
    folder.mkdir(parents=True, exist_ok=True)
    wav = folder / f"{name}.wav"
    wav.write_bytes(wav_bytes(b"\0\0" * 16000, 16000))
    wav.with_suffix(".json").write_text(json.dumps({"person": person, "label": label, "transcript": name, **(meta or {})}))
    np.save(wav.with_name(wav.stem + ".emb.npy"), vm.unit(center + rng.normal(0, 0.04, D)))
    return wav


def matcher(hass):
    entry = types.SimpleNamespace(entry_id="e", options={}, runtime_data=None)
    m = vmf.VoiceMatcher(hass, entry)
    m.status = "ready"
    m._strangers = np.array([vm.unit(rng.normal(size=D)) for _ in range(80)], np.float32)
    m._embedder = lambda samples: ROB              # every live request sounds like Rob
    entry.runtime_data = types.SimpleNamespace(matcher=m, trainer=None, skills=None)
    return m


async def test_rebuild_drops_odd_clips_and_identifies(hass):
    root = vmf.voice_dir(hass)
    for i in range(8):
        put(root, "train", "person.rob", f"20261113T1000{i:02d}Z_{i}", ROB)
    put(root, "train", "person.rob", "20261113T100099Z_9", LEILA)            # the TV in Rob's training
    for i in range(6):
        put(root, "train", "person.leila", f"20261113T1100{i:02d}Z_{i}", LEILA)
    put(root, "test", "unknown", "20261113T120000Z_1", ROB)                  # everyday, unconfirmed: not used
    m = matcher(hass)
    await m.async_rebuild()
    by = {p["person"]: p for p in m.prints}
    assert by["person.rob"]["grade"] == "ready" and len(by["person.rob"]["clips"]) == 8
    assert by["person.rob"]["dropped"] == ["train~rob~20261113T100099Z_9"]
    assert len(by["person.leila"]["clips"]) == 6
    assert json.loads((root / "prints.json").read_text())[0]["person"] in ("person.leila", "person.rob")
    match = await m.async_identify(b"\1\0" * 16000, 16000)
    assert match.person == "person.rob" and m.recent() is match
    m._last = (match, time.time() - 60)
    assert m.recent() is None                                                # only for the request it came with


async def test_recordings_tab_permissions_assign_and_delete(hass, monkeypatch):
    root = vmf.voice_dir(hass)
    rob_clip = put(root, "test", "person.rob", "20261113T130000Z_1", ROB, {"match": {"person": "person.rob", "score": 0.6}})
    unknown = put(root, "test", "unknown", "20261113T130100Z_2", LEILA, {"match": {"person": None, "score": 0.2}})
    leila_clip = put(root, "train", "person.leila", "20261113T130200Z_3", LEILA)
    m = matcher(hass)
    entry = types.SimpleNamespace(options={}, runtime_data=types.SimpleNamespace(matcher=m, trainer=object(), skills=object()))

    class Conn:
        def __init__(self, user):
            self.user, self.refresh_token_id, self.out, self.err = user, None, None, None
        def send_result(self, i, r=None): self.out = r
        def send_error(self, i, code, text): self.err = (code, text)
        def async_handle_exception(self, msg, err): self.err = ("exception", repr(err))

    async def done(c):                                    # websocket commands answer from a background task
        for _ in range(200):
            if c.out is not None or c.err is not None:
                return
            await asyncio.sleep(0.01)

    admin = types.SimpleNamespace(id="u-admin", is_admin=True)
    leila = types.SimpleNamespace(id="u-leila", is_admin=False)
    monkeypatch.setattr(voice_panel, "_entry", lambda h: entry)
    monkeypatch.setattr(voice_panel, "async_sign_path", lambda hass, path, exp, refresh_token_id=None: path + "?authSig=x")

    c = Conn(admin)
    voice_panel.ws_clips(hass, c, {"id": 1, "limit": 100})
    await done(c)
    assert c.err is None, c.err
    assert {x["id"] for x in c.out["clips"]} == {"test~rob~20261113T130000Z_1", "test~unknown~20261113T130100Z_2",
                                                "train~leila~20261113T130200Z_3"}
    assert c.out["clips"][0]["url"].startswith("/api/better_assistant/voice_clip/")

    c = Conn(leila)                                       # not an admin: her own clips and unassigned ones
    voice_panel.ws_clips(hass, c, {"id": 2, "limit": 100})
    await done(c)
    assert c.err is None, c.err
    assert {x["id"] for x in c.out["clips"]} == {"test~unknown~20261113T130100Z_2", "train~leila~20261113T130200Z_3"}
    assert [p["person"] for p in c.out["people"]] == ["person.leila"]
    c.out = c.err = None
    voice_panel.ws_clip_action(hass, c, {"id": 3, "action": "assign", "id": "test~unknown~20261113T130100Z_2",
                                         "person": "person.rob"})
    await done(c)
    assert c.err[0] == "unauthorized"                     # can't label someone else's voice

    c = Conn(leila)                                       # "That was me"
    c.out = c.err = None
    voice_panel.ws_clip_action(hass, c, {"id": 4, "action": "assign", "id": "test~unknown~20261113T130100Z_2",
                                         "person": "person.leila"})
    await done(c)
    moved = root / "test" / "leila" / "20261113T130100Z_2.wav"
    assert c.err is None and moved.exists() and not unknown.exists()
    meta = json.loads(moved.with_suffix(".json").read_text())
    assert meta["person"] == meta["confirmed"] == "person.leila"
    assert len({p["person"]: p for p in m.prints}["person.leila"]["clips"]) == 2      # learned from it

    c = Conn(admin)                                       # "Someone else / the TV", then delete
    c.out = c.err = None
    voice_panel.ws_clip_action(hass, c, {"id": 5, "action": "assign", "id": "test~rob~20261113T130000Z_1",
                                         "person": "other"})
    await done(c)
    other = root / "other" / "other" / "20261113T130000Z_1.wav"
    assert other.exists() and not rob_clip.exists()
    c.out = c.err = None
    voice_panel.ws_clip_action(hass, c, {"id": 6, "action": "delete", "id": "other~other~20261113T130000Z_1"})
    await done(c)
    assert not other.exists() and not other.with_suffix(".json").exists()

    c.out = c.err = None
    voice_panel.ws_clip_action(hass, c, {"id": 7, "action": "delete_person", "person": "person.leila"})
    await done(c)
    assert not leila_clip.exists() and not moved.exists()

    assert vmf.clip_path(root, "train~..~x") is None and vmf.clip_path(root, "nope") is None


async def test_skills_use_voice_match_when_no_one_is_signed_in(hass):
    from homeassistant.components.conversation import ConversationInput
    from homeassistant.core import Context
    from custom_components.better_assistant.skills import Skills
    m = matcher(hass)
    skills = Skills.__new__(Skills)
    skills.hass, skills.entry = hass, m.entry
    ui = ConversationInput(text="x", context=Context(), conversation_id="c", device_id="d", satellite_id=None,
                           language="en", agent_id="conversation.x")
    assert skills.speaker_person(ui) is None                                   # two people, nobody recognised
    m._last = (vm.Match("person.leila", 0.6), time.time())
    assert skills.speaker_person(ui) == "person.leila"
    signed_in = ConversationInput(text="x", context=Context(user_id="u-rob"), conversation_id="c", device_id="d",
                                  satellite_id=None, language="en", agent_id="conversation.x")
    assert skills.speaker_person(signed_in) == "person.rob"                    # the app's login still wins
