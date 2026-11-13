"""Music requests: what kind of thing to play, and news requests that belong to the built-ins.
Pure Python, no Home Assistant imports."""
from __future__ import annotations

import re
from dataclasses import dataclass

NEWS = re.compile(r"\b(news|headlines|newscast|news ?cast|news briefing|flash briefing|podcasts?|weather report)\b",
                  re.I)


@dataclass
class MusicRequest:
    name: str
    media_type: str | None = None       # artist | album | playlist | track | radio | None (search everything)
    radio: bool = False


def is_news(query: str) -> bool:
    """'play the news', 'play the BBC headlines', 'play my podcast': not music."""
    return bool(NEWS.search(query))


def parse_music_query(query: str) -> MusicRequest | None:
    """'music by Queen' -> artist; 'my workout playlist' -> playlist; 'the album Abbey Road' -> album;
    'music like Adele' / 'Adele radio' -> radio of that artist; anything else -> search."""
    q = re.sub(r"\s+", " ", query.strip(" .,!?"))
    q = re.sub(r"^(?:me |us |some )", "", q, flags=re.I)
    if not q:
        return None
    patterns = [
        (r"^(?:(?:some |the )?(?:music|songs|tracks) )?(?:by|from) (?:the artist )?(.+)$", "artist", False),
        (r"^(?:my |the |our )?(.+?) playlist$", "playlist", False),
        (r"^(?:the )?playlist (?:called |named )?(.+)$", "playlist", False),
        (r"^(?:the )?album (?:called |named )?(.+)$", "album", False),
        (r"^(?:the )?(.+?) album$", "album", False),
        (r"^(?:(?:some )?(?:music|songs) )?(?:like|similar to|that sounds like) (.+)$", "artist", True),
        (r"^(.+?) radio$", "artist", True),
        (r"^(?:the )?song (?:called |named )?(.+)$", "track", False),
    ]
    for pattern, kind, radio in patterns:
        m = re.match(pattern, q, re.I)
        if m and m.group(1).strip():
            return MusicRequest(m.group(1).strip(), kind, radio)
    if re.fullmatch(r"(?:some )?(?:music|songs|something)", q, re.I):
        return MusicRequest("", None, False)          # "play some music": resume / random
    return MusicRequest(q, None, False)


def say_now_playing(title: str | None, artist: str | None, player: str) -> str:
    if not title:
        return f"Nothing is playing on the {player.lower()}."
    return f"This is {title}" + (f" by {artist}" if artist else "") + "."
