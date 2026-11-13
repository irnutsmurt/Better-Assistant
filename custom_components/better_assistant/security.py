"""Optional voice passphrase for opening locks, garage doors and gates, and for ending guest mode.

The passphrase lives in the config entry options and is never logged or spoken. With the door toggle
on, the doors stay hidden from Assist (Home Assistant's own "open the garage door" would otherwise
skip this agent), and the integration's own phrases open them after a passphrase check: either in
one go ("open the garage door, passphrase …") or by asking for it on the speaker."""
from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.core import callback

from .const import OPT_SECURITY
from .core.security import Attempts, matches, normalize, say_not_heard, say_oneshot_help, say_wait, say_wrong

_LOGGER = logging.getLogger(__name__)
PENDING_SECONDS = 60
SECURITY_DEFAULTS = {"passphrase": "", "require_doors": True, "require_guest": True, "owner": None}


class SecuritySkills:
    """Mixed into Skills."""

    # ------------------------------------------------------------ settings
    def security(self) -> dict[str, Any]:
        return {**SECURITY_DEFAULTS, **(self.entry.options.get(OPT_SECURITY) or {})}

    def _secret(self) -> str:
        return str(self.security().get("passphrase") or "")

    def doors_need_passphrase(self) -> bool:
        return bool(self._secret()) and bool(self.security()["require_doors"])

    def guest_needs_passphrase(self) -> bool:
        return bool(self._secret()) and bool(self.security()["require_guest"])

    @callback
    def apply_door_hiding(self) -> None:
        """Keep the protected doors hidden from Assist while voice opening needs the passphrase."""
        doors = self.protected_doors()
        if self.doors_need_passphrase():
            self.hide_from_assist(doors, "voice_lock")
            self.unhide_from_assist("voice_lock", keep=set(doors))
        else:
            self.unhide_from_assist("voice_lock")

    def door_names(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for eid in self.protected_doors():
            for name in self._names_for(eid):
                out[name] = eid
                for suffix in (" lock", " door lock"):
                    if name.endswith(suffix) and len(name) > len(suffix) + 2:
                        out.setdefault(name[: -len(suffix)], eid)
        return out

    # ------------------------------------------------------------ attempts and pending questions
    def _attempts(self) -> Attempts:
        return Attempts.from_dict(self.store.data.get("security_attempts"))

    def _save_attempts(self, attempts: Attempts) -> None:
        self.store.data["security_attempts"] = attempts.to_dict()
        self.store.changed()

    def _pending(self) -> dict:
        if not hasattr(self, "_pending_questions"):
            self._pending_questions: dict[str, dict] = {}
        return self._pending_questions

    def _speaker_key(self, user_input) -> str | None:
        return self.satellite_for(user_input) if (user_input.device_id or getattr(user_input, "satellite_id", None)) \
            else None

    def has_pending(self, user_input) -> bool:
        key = self._speaker_key(user_input)
        p = self._pending().get(key or "")
        return bool(p) and p["until"] > time.time()

    async def answer_pending(self, text: str, user_input) -> str:
        """The reply to "What's the passphrase?" on the same speaker."""
        key = self._speaker_key(user_input) or ""
        pending = self._pending().pop(key, None)
        if not pending:
            return ""
        if not normalize(text):
            return say_not_heard(self._what_stays(pending["action"]))
        return await self._check(text, pending["action"])

    # ------------------------------------------------------------ the check
    def _what_stays(self, action: tuple) -> str:
        if action[0] == "guest":
            return "guest mode stays on"
        name = self._friendly(action[1]).lower()
        return f"the {name} stays {'locked' if action[1].startswith('lock.') else 'closed'}"

    async def _owner_notice(self, message: str) -> None:
        owner = self.security().get("owner")
        if owner:
            await self.notify(owner, "Voice passphrase", message)

    async def _check(self, phrase: str, action: tuple) -> str:
        attempts = self._attempts()
        now = time.time()
        if (wait := attempts.locked_for(now)):
            return say_wait(wait)
        what = "end guest mode" if action[0] == "guest" else f"open the {self._friendly(action[1]).lower()}"
        if matches(phrase, self._secret()):
            attempts.succeeded()
            self._save_attempts(attempts)
            await self._owner_notice(f"Passphrase accepted to {what}.")
            return await self._do(action)
        lock = attempts.failed(now)
        self._save_attempts(attempts)
        await self._owner_notice(f"Wrong passphrase given to {what}." +
                                 (f" Voice unlocking paused for {lock} seconds." if lock else ""))
        return say_wrong(self._what_stays(action), lock)

    async def _do(self, action: tuple) -> str:
        if action[0] == "guest":
            await self.set_guest(False)
            return "Guest mode is off."
        eid = action[1]
        name = self._friendly(eid).lower()
        if eid.startswith("lock."):
            await self._call("lock", "unlock", {"entity_id": eid})
            return f"Okay, unlocking the {name}."
        await self._call("cover", "open_cover", {"entity_id": eid})
        return f"Okay, opening the {name}."

    async def _ask_or_explain(self, action: tuple, user_input, command: str) -> str:
        key = self._speaker_key(user_input)
        if not key:                                            # app or typed chat: no follow-up turn
            return say_oneshot_help(command)
        self._pending()[key] = {"action": action, "until": time.time() + PENDING_SECONDS}
        self.followup = True                                   # keep listening for the answer
        return "What's the passphrase to end guest mode?" if action[0] == "guest" else \
            f"What's the passphrase to open the {self._friendly(action[1]).lower()}?"

    # ------------------------------------------------------------ intents
    async def _h_door_open(self, slots, user_input) -> str:
        eid = slots.get("door")
        if eid not in self.protected_doors():
            return "I don't know that door."
        action = ("door", eid)
        if not self.doors_need_passphrase():
            return await self._do(action)
        if slots.get("passphrase") is not None:
            return await self._check(slots["passphrase"], action)
        if (wait := self._attempts().locked_for(time.time())):
            return say_wait(wait)
        return await self._ask_or_explain(action, user_input, f"open the {self._friendly(eid).lower()}")

    async def _h_door_close(self, slots, user_input) -> str:
        eid = slots.get("door")
        if eid not in self.protected_doors():
            return "I don't know that door."
        name = self._friendly(eid).lower()
        if eid.startswith("lock."):
            await self._call("lock", "lock", {"entity_id": eid})
            return f"Okay, locking the {name}."
        await self._call("cover", "close_cover", {"entity_id": eid})
        return f"Okay, closing the {name}."

    async def _h_door_status(self, slots, user_input) -> str:
        eid = slots.get("door")
        st = self.hass.states.get(eid or "")
        if not st:
            return "I don't know that door."
        return f"The {self._friendly(eid).lower()} is {st.state.replace('_', ' ')}."

    async def _h_guest_off(self, slots, user_input) -> str:
        if not self.guest_on():
            return "Guest mode is already off."
        if not self.guest_needs_passphrase():
            await self.set_guest(False)
            return "Guest mode is off."
        if slots.get("passphrase") is not None:
            return await self._check(slots["passphrase"], ("guest",))
        if (wait := self._attempts().locked_for(time.time())):
            return say_wait(wait)
        return await self._ask_or_explain(("guest",), user_input, "turn off guest mode")
