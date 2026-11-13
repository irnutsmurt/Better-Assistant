# Brave Search API for Home Assistant

A conversation agent for Home Assistant's Assist that answers everyday questions out loud, without an
AI model writing the answer.

> **Unofficial community integration.** This project is not made, endorsed or supported by Brave
> Software. It uses the public [Brave Search API](https://brave.com/search/api/) with your own key.

## What it does

Put it behind Home Assistant's own commands in an Assist pipeline. Anything Home Assistant
understands itself (lights, timers, "what time is it") runs locally as usual. Anything left over
comes to this agent, which:

1. **Answers "what did you hear?"** with the last sentence it received.
2. **Runs compound commands** such as "turn off the desk lamp and the porch light then play the
   news". It splits the sentence, carries the verb onto bare device names, checks that *every* part is
   a real Home Assistant command (dry run), and only then runs each part through Home Assistant's own
   agent. If any part isn't a command, nothing runs.
3. **Answers locally, with no search:** spelling ("how do you spell necessary"), arithmetic ("what's
   15 percent of 80"), unit conversions ("how many tablespoons in a cup", "350 Fahrenheit in Celsius"),
   holiday and date questions ("how many days until Thanksgiving"), world clock ("what time is it in
   Tokyo"), coin flips, dice and "pick a number between 1 and 50".
4. **Guards against misheard commands:** only question-shaped sentences are searched ("Sorry, I
   didn't catch that." otherwise), and sentences that start like a command or name one of your
   exposed devices or areas are never sent to the web.
5. **Looks it up on the web** with the Brave Search API "LLM Context" endpoint. The API returns
   passages from real web pages; the integration reads out the single sentence that best matches your
   question and names the site: *"From mayoclinic dot org, ..."*. Medicine, health, pets, food safety,
   gardening, films, people and dictionary questions are steered towards trusted sites for that topic.

## Install (HACS)

1. HACS > three-dot menu > **Custom repositories** > add
   `https://github.com/irnutsmurt/brave-search-api` as type **Integration**.
2. Install **Brave Search API**, then restart Home Assistant.
3. **Settings > Devices & services > Add integration > Brave Search API.**

Manual install: copy `custom_components/brave_search_api` into your `config/custom_components/`
folder and restart.

## Getting an API key (optional)

The key is optional. Without one, everything except web search still works.

1. Sign up at the Brave Search API dashboard (`api-dashboard.search.brave.com`).
2. Subscribe to a plan that includes the **LLM Context** endpoint. Brave has offered a free monthly
   credit; check their current pricing, as plans change.
3. Create a key and paste it in the setup dialog. It is checked with one small request and stored in
   the config entry. It is never logged. To change or remove it later use **Reconfigure** on the
   integration.

The **monthly search cap** (default 300) stops searches for the rest of the month once reached, so
you stay inside your plan. The sensor **Brave searches this month** shows the count, with the cap and
remaining searches as attributes. A dictionary question can use two searches when the first doesn't
contain a real definition.

## Use it in an Assist pipeline

1. **Settings > Voice assistants**, open (or add) a pipeline.
2. Set **Conversation agent** to **Brave Search API**.
3. Turn **Prefer handling commands locally** on. This matters: Home Assistant then runs every command
   it recognises itself, and only unrecognised sentences reach this agent.
4. Pick your speech-to-text and text-to-speech engines as usual.

## Settings page

**Settings > Devices & services > Brave Search API > Configure** opens a menu:

| Section | What's there |
|---|---|
| Web search | On/off, monthly cap, country (2-letter code), say the source site |
| Behaviour | Question-only guard, compound commands on/off, most parts in one compound command (2-4) |
| Voice speakers, Music, Calendar, Reminders & notes, Cameras & outside, Thermostat, TV, Bed, Rooms & lights | Devices found automatically, for features coming in later versions |
| Night mode, Guest mode | Coming in a later version |
| Re-detect devices | Scan again |

### Automatic device detection

You don't match devices by hand. The integration looks at what you already have, using domain,
device class, integration, supported features and area (never names), and pre-fills each section:
voice satellites (and a Music Assistant player on the same device), Music Assistant players, Cast
groups for broadcasts, thermostats, calendars (and the first one that can create events), to-do
lists, people and their phones' notify services, cameras and the Cast TVs that can show them, outdoor
motion/person sensors (Frigate person sensors preferred, indoor rooms skipped), TVs with their remote
and inputs, lights and light switches per room (status LEDs on Zigbee routers and voice satellites
left out), battery sensors (phones and watches tagged as personal), unavailable devices, and Sleep
Number beds.

Detection runs once after Home Assistant starts. Just press Submit to accept a section. If you change
something, only your changes are stored, separately, so **Re-detect devices** refreshes everything
else without undoing your edits.

## "What did you hear?"

The agent remembers the last 5 sentences **it** received (in memory only, cleared on restart) and
answers "what did you hear?" or "what did I say?" with the most recent one. With "prefer handling
commands locally" on, sentences Home Assistant handled itself never reach the agent, so this reflects
only text the agent saw. (Home Assistant's pipeline run history is internal and not a stable API for
custom integrations, so it isn't used.)

## Privacy

- Only the **question text** is sent to the Brave Search API, and only when it gets past the guards
  and isn't answered locally. With no key, nothing is sent at all.
- Nothing else leaves your home: no device names, states, locations, voices or audio. Device
  detection reads your local registries only.
- The search count is kept in Home Assistant's own storage (`.storage`), not in a file you have to
  manage.

## Roadmap

Later versions will use the detected devices for:

- Reminders, alarms and timers with natural phrasing ("remind me tomorrow at 3", "every weekday at 6:45")
- Recipes, read step by step
- Music on any speaker ("play jazz in the kitchen", "play it here")
- Calendar: what's on, and adding events
- Notes and messages between people in the house
- Whole-room on/off ("turn off the living room")
- Cameras and outside: "who's outside?", show a camera on a TV
- Health report: low batteries and unavailable devices
- Guest mode and night mode
- Thermostat, TV (apps and inputs) and bed controls
- Broadcasts to every speaker
- Location reminders ("remind me when I get home")

## Development

The logic lives in `custom_components/brave_search_api/core/` as plain Python with no Home Assistant
imports, so it can be tested on its own:

```bash
python -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/python -m pytest
```

## License

MIT. See [LICENSE](LICENSE).
