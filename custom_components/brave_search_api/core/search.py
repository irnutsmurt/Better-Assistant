"""Answers a spoken question from the Brave Search API "LLM Context" endpoint. No AI writes the
answer: the API returns the most relevant passages from real web pages, and this module picks the
sentence that best matches the question and names the site it came from. The question text is the
only thing ever sent.

Pure Python (aiohttp session passed in), no Home Assistant imports.
"""
from __future__ import annotations

import asyncio
import html
import re
import urllib.parse
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

from .router import goggle, route

URL = "https://api.search.brave.com/res/v1/llm/context"
MAX_CHARS = 240                      # about 15 seconds of speech
TIMEOUT = aiohttp.ClientTimeout(total=30)
STOP = set("a an the of to in on for and or is are was were be what whats what's how much many "
           "does do did can could should would when where who which why it its i me my you your "
           "tell look up search find about day per definition define meaning mean means".split())


class InvalidAuth(Exception):
    """The API key was refused (HTTP 401/403)."""


class CannotConnect(Exception):
    """The API could not be reached or answered with an error."""


def clean(t):
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)          # [label](url) -> label
    t = re.sub(r"https?://\S+|\[\d+\]", "", t)
    t = re.sub(r"[*_`#>|]+", "", t)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"(^|[.!?]\s+)(key takeaways|summary|overview|in short|tl;?dr|answer)\s*:\s*", r"\1", t, flags=re.I)
    t = re.sub(r"(^|\s)[-•]\s+", " ", t)                     # list dashes
    return re.sub(r"\s+([.,;:!?])", r"\1", t).strip()


def words(t):
    return {w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w   # peppers ~ pepper
            for w in re.findall(r"[a-z0-9]+", t.lower()) if w not in STOP and len(w) > 1}


PROMO = re.compile(r"(learn|read|click|discover|find out|see|check out|sign up|subscribe|explore|get)\b", re.I)
BOILER = re.compile(r"synonyms|antonyms|thesaurus|hypernyms|and much more|related words|usage examples|senior member|"
                    r"community answer|expert.verified|enter your search|cookie|all rights reserved|"
                    r"while all (?:these|of these|the) words|share a common meaning|can be used", re.I)
# Sentences that lean on the one before them ("Other dogs can eat grapes…") mislead when read alone.
DEPENDENT = re.compile(r"(other|others|some|however|but|also|this|these|that|those|they|it|its|he|she|his|her|"
                       r"in addition|additionally|meanwhile|still|yet|so|and|or|unlike|instead|similarly|likewise|"
                       r"in contrast|on the other hand|for example|for instance|such as)\b", re.I)
SMALL = set("a an and as at by for in of on or the to vs with is are".split())


def drop_heading(s):
    """Strip a page heading glued to the front of a sentence ("Official Height In Feet The official
    height is..."): a run of 4+ Title Case words followed by another capitalised word."""
    w = s.split()
    n = 0
    for x in w:
        if x[:1].isupper() or x.lower() in SMALL:
            n += 1
        else:
            break
    return " ".join(w[n - 2:]) if n >= 6 and n < len(w) else s


def best_answer(q, data, sites=(), lists_ok=False):
    """Score every sentence of the top results by overlap with the question's words and read the
    single best one (plus the next if the first is very short), from the highest-ranked page."""
    qw = words(q)
    m = re.search(r"(?:definition (?:of|for)|meaning of|define|what (?:is|are|does)|what's|whats)\s+(?:an? |the )?(.+?)(?:\s+mean)?\W*$", q, re.I)
    term = m and re.sub(r"^(?:the )?(?:definition (?:of|for)|meaning of|define)\s+(?:an? |the )?", "", m.group(1).strip(), flags=re.I)
    term = re.escape(term) if term else None
    best = None
    for rank, item in enumerate((data.get("grounding") or {}).get("generic") or []):
        for snip in item.get("snippets") or []:
            sents = [drop_heading(s) for part in snip.split("\n") for s in re.split(r"(?<=[.!?])\s+", clean(part))]
            sents = [s.strip(" \"'“”‘’") for s in sents]
            sents = [s for s in sents if 25 <= len(s) <= 300 and not s.endswith(("?", ":")) and not PROMO.match(s)
                     and not BOILER.search(s) and not re.search(r"[^\x00-\u024f\u2000-\u206f]", s)
                     and not re.search(r"[{}\[\]]|\":|@type|https?:", s)]                 # page metadata / JSON
            for i, s in enumerate(sents):
                d = term and re.search(term + r"\s+(is|are|refers to|means|describes)\b", s, re.I)
                if d and len(s[d.end():].split()) < 4:   # "plant matter is." is not a definition
                    d = None
                if d:                                     # a real definition: start it at the term
                    art = re.search(r"\b(?:an?|the)\s+$", s[:d.start()], re.I)   # (keeping "A"/"The"),
                    s = sents[i] = s[art.start() if art else d.start():]          # prefer short ones
                score = len(qw & words(s)) + (0.5 if re.search(r"\d", s) else 0) - rank * 0.3 - len(s) / 400
                if DEPENDENT.match(s):
                    score -= 3                            # needs the previous sentence to make sense
                if not lists_ok and not re.search(r"[.!]$", s):
                    score -= 1.5                          # no full stop: usually a heading or a list
                if i == 0:
                    score += 0.5                          # a passage's opening line is usually the summary
                if any(site in item.get("url", "") for site in sites):
                    score += 1                            # preferred site for this kind of question
                if d:
                    score += 3 - len(s) / 300
                if best is None or score > best[0]:
                    best = (score, sents, i, item.get("url", ""))
    if not best or best[0] < 1:
        return "", ""
    _, sents, i, url = best
    out = sents[i]
    if len(out) < 60 and i + 1 < len(sents) and len(out) + len(sents[i + 1]) < MAX_CHARS:
        out += " " + sents[i + 1]
    if len(out) > MAX_CHARS:
        out = out[:MAX_CHARS].rsplit(" ", 1)[0] + "…"
    host = (data.get("sources") or {}).get(url, {}).get("hostname") or urllib.parse.urlparse(url).netloc
    return out, host.lower().removeprefix("www.")


# First words that are safe to lowercase after "From site dot com, ...". Anything else (Mount Everest,
# NASA, New York, a person's name) keeps its capital.
STARTERS = set("the a an it its this these those there they you your yes no all most many some symptoms common "
               "people dogs cats each every in on at for when while if during after before because according "
               "generally typically usually unlike like words".split())


def lower_first(answer, term=None):
    """Lowercase the first letter only when the first word is an ordinary sentence-starter or the
    defined term itself (and isn't followed by another capitalised word)."""
    m = re.match(r"([A-Za-z']+)(\s+(\S+))?", answer)
    if not m:
        return answer
    first, nxt = m.group(1), m.group(3) or ""
    if first.isupper() and len(first) > 1 or first == "I":
        return answer
    is_term = bool(term) and first.lower() == term.split()[0].lower()
    if first.lower() not in STARTERS and not is_term:
        return answer
    if nxt[:1].isupper() and not is_term and first.lower() not in ("the", "a", "an", "in", "on", "at", "for",
                                                                  "according", "unlike", "like", "when",
                                                                  "during", "after", "before", "if", "while"):
        return answer                                 # "Dogs Trust ..." style names
    return answer[:1].lower() + answer[1:]


def spoken(answer, host, term=None):
    """'From webmd dot com, the maximum daily dose is...'"""
    site = re.sub(r"\.(com|org|gov|net|edu|co\.uk)$", lambda m: " dot " + m.group(1).replace(".", " dot "), host)
    if not site:
        return answer
    return f"From {site}, {lower_first(answer, term)}"


SYN_HEAD = re.compile(r"(?:synonyms?|similar words|other words|another word)(?:\s*(?:&|and)\s*similar words)?"
                      r"(?:\s+(?:for|of|to))?(?:\s+['\"]?[\w-]+['\"]?)?\s*[:\-–—•·|]\s*(?P<list>[^.\n]+)", re.I)


def _syn_words(text, word):
    out = []
    for w in re.split(r"\s*(?:,|;|•|·|\||/|\n)\s*", text):
        w = re.sub(r"[\[\]*_`()\"]", "", w).strip(" .'-")
        if not re.fullmatch(r"[a-z][a-z-]*(?: [a-z][a-z-]*)?", w) or w in ("and", "or", "more", "see more"):
            continue
        w = re.sub(r"^(?:and|or) ", "", w)
        if word and w == word.lower() or w in out:
            continue
        out.append(w)
    return out


def synonym_list(q, data):
    """(words, host) from the first real synonym list in the snippets, or ([], "")."""
    m = re.search(r"(?:for|of|means?|to)\s+['\"]?([\w-]+)['\"]?\W*$", q, re.I)
    word = m.group(1).lower() if m else None
    for item in (data.get("grounding") or {}).get("generic") or []:
        url = item.get("url", "")
        host = (data.get("sources") or {}).get(url, {}).get("hostname") or urllib.parse.urlparse(url).netloc
        for snip in item.get("snippets") or []:
            raw = html.unescape(re.sub(r"<[^>]+>", " ", snip))
            raw = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", raw)
            found = []
            for h in SYN_HEAD.finditer(raw):              # "Synonyms for happy: glad, cheerful, ..."
                found = _syn_words(h.group("list"), word)
                if len(found) >= 2:
                    break
            if len(found) < 2:                            # a bare run of 4+ single words
                for run in re.finditer(r"(?:^|\n|:)\s*((?:[a-z][a-z-]*\s*(?:,|•|·|;)\s*){3,}[a-z][a-z-]*)", raw):
                    found = _syn_words(run.group(1), word)
                    if len(found) >= 3:
                        break
            if len(found) >= 2:
                return found[:5], host.lower().removeprefix("www.")
    return [], ""


def say_synonyms(word, found):
    found = found[:5]
    if len(found) == 1:
        return f"Another word for {word} is {found[0]}."
    return f"Words for {word} include {', '.join(found[:-1])}{',' if len(found) > 2 else ''} and {found[-1]}."


def dictionary_word(q):
    """The word or phrase in 'define X', 'definition of X', 'meaning of X', 'what does X mean'."""
    m = (re.search(r"\b(?:define|definition (?:of|for)|meaning of)\s+(?:the (?:word |term )?)?(?:an? )?(.+?)\W*$", q, re.I)
         or re.search(r"\bwhat does (?:the (?:word |term )?)?(.+?) mean\W*$", q, re.I))
    w = m and m.group(1).strip(" '\"")
    return w if w and len(w.split()) <= 3 else None


def merriam_webster(word, data):
    """'ubiquitous means existing or being everywhere at the same time, constantly encountered,
    widespread.' - only from the entry page for that exact word, else None."""
    slug = urllib.parse.quote(word.lower())
    for item in (data.get("grounding") or {}).get("generic") or []:
        path = urllib.parse.urlparse(item.get("url", "")).path.rstrip("/")
        if path.lower() not in (f"/dictionary/{slug}", f"/simple/{slug}"):
            continue
        for snip in item.get("snippets") or []:
            m = re.search(r"The (?:simple )?(?:meaning|definition) of [^.]+? is (.+?)(?:\.\s|\.$|\n)", snip, re.I)
            if m:
                d = re.sub(r"\s+:\s+", ", ", m.group(1)).strip(" .")
                return f"{word} means {d}." if len(d) <= MAX_CHARS else None
    return None


async def fetch_context(session: aiohttp.ClientSession, key: str, q: str, country: str = "us",
                        sites=(), count: int = 5) -> dict[str, Any]:
    """One LLM Context request. Raises InvalidAuth / CannotConnect."""
    params = {"q": q[:400], "country": country or "us", "search_lang": "en", "count": count,
              "maximum_number_of_urls": count, "maximum_number_of_tokens": 2048,
              "maximum_number_of_tokens_per_url": 512, "context_threshold_mode": "balanced",
              "safesearch": "moderate"}
    if sites:
        params["goggles"] = goggle(sites)               # boost the preferred sites; others still count
    headers = {"Accept": "application/json", "X-Subscription-Token": key}
    try:
        async with session.get(URL, params=params, headers=headers, timeout=TIMEOUT) as resp:
            if resp.status in (401, 403):
                raise InvalidAuth
            if resp.status == 422:                        # Brave reports a bad key as 422
                try:
                    err = ((await resp.json(content_type=None)) or {}).get("error") or {}
                except ValueError:
                    err = {}
                if "TOKEN" in str(err.get("code", "")).upper() or \
                        (err.get("meta") or {}).get("component") == "authentication":
                    raise InvalidAuth
                raise CannotConnect("HTTP 422")
            if resp.status != 200:
                raise CannotConnect(f"HTTP {resp.status}")
            return await resp.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
        raise CannotConnect(type(err).__name__) from err


async def validate_key(session: aiohttp.ClientSession, key: str) -> None:
    """Cheapest possible check that the key works (one small request)."""
    await fetch_context(session, key, "weather", count=1)


def compose(q: str, data: dict, kind: str | None, sites=(), word: str | None = None,
            speak_source: bool = True) -> tuple[str, bool]:
    """Spoken answer from one LLM Context payload: (answer, is_real_definition)."""
    if word:
        mw = merriam_webster(word, data)
        if mw:
            return ("From merriam-webster dot com, " + mw if speak_source else mw[:1].upper() + mw[1:]), True
    if kind == "synonym":                             # a real list beats any sentence
        found, host = synonym_list(q, data)
        m = re.search(r"(?:for|of|means?|to)\s+['\"]?([\w-]+)['\"]?\W*$", q, re.I)
        if found and m:
            text = say_synonyms(m.group(1), found)
            return (spoken(text, host) if speak_source else text), False
    answer, src = best_answer(q, data, sites, lists_ok=kind == "synonym")
    is_def = bool(word and re.match(r"(?:(?:an?|the)\s+)?" + re.escape(word) + r"\s+(is|are|refers to|means|describes)\b", answer, re.I))
    if kind == "synonym" and answer and not re.search(r"[.,;]", answer):
        m = re.search(r"(?:for|of|means?)\s+['\"]?([\w-]+)['\"]?\W*$", q, re.I)
        listed = [w for w in answer.split() if w.isalpha() and w.islower()][:6]
        if m and len(listed) >= 3:
            answer = f"Words for {m.group(1)} include {', '.join(listed[:-1])}, and {listed[-1]}."
    if not answer:
        return "", False
    term = word or _question_term(q)
    return (spoken(answer, src, term) if speak_source else answer), is_def


def _question_term(q):
    """'what is a black hole' -> 'black hole' (for keeping or lowering the first word)."""
    m = re.search(r"(?:what (?:is|are|does)|what's|whats|define|meaning of)\s+(?:an? |the )?([\w' -]+?)(?:\s+mean)?\W*$", q, re.I)
    return m.group(1) if m else None


async def answer(session: aiohttp.ClientSession, key: str, q: str,
                 take_slot: Callable[[], Awaitable[bool]], country: str = "us",
                 speak_source: bool = True) -> dict[str, Any]:
    """{"ok": True, "answer": ..., "route": ...} or {"ok": False, "reason": "cap"|"auth"|"error"|"empty"}.

    `take_slot` is awaited before every request and must return False once the monthly cap is used."""
    q = q.strip()
    if not await take_slot():
        return {"ok": False, "reason": "cap"}
    kind, sites = route(q)
    word = dictionary_word(q) if kind == "definition" else None
    try:
        data = await fetch_context(session, key, word + " definition" if word else q, country, sites)
    except InvalidAuth:
        return {"ok": False, "reason": "auth"}
    except CannotConnect:
        return {"ok": False, "reason": "error"}
    text, is_def = compose(q, data, kind, sites, word, speak_source)
    if word and not is_def and await take_slot():
        try:                                              # no real definition there: one plain search
            data2 = await fetch_context(session, key, q, country)
        except (InvalidAuth, CannotConnect):
            data2 = None
        if data2:
            text2, _ = compose(q, data2, None, (), None, speak_source)
            text = text2 or text
    return {"ok": True, "answer": text, "route": kind} if text else {"ok": False, "reason": "empty"}
