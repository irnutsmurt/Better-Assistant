"""Question router: answers spelling, math, unit and date questions locally (no search), and picks
preferred sites for the rest. Each route's sites are passed to the Brave Search API as a Goggle that
boosts them, so it is still one search and other sites can answer when the preferred ones can't.

Pure Python, no Home Assistant imports."""
from __future__ import annotations

import datetime
import math
import re

# ---------------------------------------------------------------- site routes
MED = (r"pain|ache|aches|fever|cough|rash|disease|infection|syndrome|cancer|diabetes|flu|virus|allerg\w*|"
       r"headache|migraine|nausea|vomit\w*|diarrh\w*|blood pressure|cholesterol|asthma|arthritis|strep|"
       r"covid|pneumonia|bronchitis|sinus\w*|shingles|measles|stroke|heart attack|concussion|anemia|"
       r"insomnia|dehydration|sunburn|gout|eczema|acne|ulcer|kidney stones?|uti|cold sores?|pink eye|"
       r"high blood sugar|low blood sugar|tonsillitis|ear infection|food poisoning")
DRUG = (r"tylenol|acetaminophen|ibuprofen|advil|motrin|aleve|naproxen|aspirin|benadryl|zyrtec|claritin|"
        r"allegra|sudafed|mucinex|nyquil|dayquil|pepto|imodium|melatonin|prednisone|amoxicillin|"
        r"antibiotics?|metformin|lisinopril|omeprazole|prilosec|gabapentin|xanax|zoloft|adderall|"
        r"insulin|antihistamines?|medications?|medicines?|meds|pills?|prescriptions?|vitamin \w+|supplements?")
PET = r"dogs?|pupp(?:y|ies)|cats?|kittens?|pets?"
MEAT = (r"chicken|pork|beef|turkey|steak|fish|salmon|tuna|shrimp|ground \w+|burgers?|hamburgers?|eggs?|"
        r"ham|lamb|meat|poultry|sausage|bacon|leftovers|rice|casserole|roast")
PLANT = (r"peppers?|tomato(?:es)?|plants?|seeds?|seedlings?|garden|lawn|grass|trees?|shrubs?|roses?|"
         r"bushes|hostas?|tulips?|bulbs|herbs?|basil|lettuce|cucumbers?|squash|zucchini|strawberr\w+|"
         r"potato(?:es)?|onions?|garlic|carrots?|beans|peas|corn|hydrangeas?|succulents?|houseplants?|orchids?")

ROUTES = [
    # (name, test, preferred sites)
    ("synonym", r"\b(another|other|different) words? for\b|\bsynonyms? (for|of)\b|\bwhat'?s a word (for|that means)\b|"
                r"\bthesaurus\b", ["merriam-webster.com", "thesaurus.com"]),
    ("definition", r"\bdefine\b|\bdefinition (of|for)\b|\bmeaning of (the word |the term )?(?!life\b|it\b|this\b|that\b)\w|\bwhat does (the word |the term )?[\w' -]{2,40} mean\b",
     ["merriam-webster.com", "britannica.com"]),
    ("pets", rf"(?<!hot )\b({PET})\b.*\b(eat|eats|have|drink|chew|lick|toxic|poisonous|safe|allowed)\b|"
             rf"\b(toxic|poisonous|safe|bad|okay|ok)\b.*\b(for|to)\s+(my\s+|a\s+)?(?<!hot )({PET})\b",
     ["aspca.org", "akc.org", "vcahospitals.com", "petmd.com"]),
    ("drugs", rf"\b({DRUG})\b.*\b(dose|dosage|how much|how many|max\w*|take|taking|side effects?|interact\w*|mix|"
              rf"with|safe|overdose|every|often|kids?|children|pregnan\w*|alcohol|expire\w*|for)\b|"
              rf"\b(dose|dosage|side effects?|interact\w*|overdose)\b.*\b({DRUG}|\w+(?:ine|ol|en|ide|cin|pril|statin|zole))\b|"
              rf"\bcan i (take|mix|give)\b.*\b(with|and|together)\b.*\b({DRUG})\b|"
              rf"\b(how (often|much|many|long)|when can i|can i|is it (safe|okay|ok|bad) to)\b.*\b(take|give|have|use|drink)\b.*\b({DRUG})\b|"
              rf"\b(alcohol|drinking|beer|wine)\b.*\b({DRUG})\b|\b({DRUG})\b.*\b(alcohol|drinking|beer|wine)\b",
     ["drugs.com", "medlineplus.gov", "mayoclinic.org"]),
    ("health", rf"\bsymptoms? of\b|\bsigns of (a |an )?({MED})\b|"
               rf"\b(what causes|cause of|causes of|treat|treatment for|cure for|remedy for|remedies for|"
               rf"get rid of|is .* contagious|how long does .* last|how long is .* contagious|"
               rf"when should i see a doctor)\b.*\b({MED})s?\b|\b({MED})s?\b.*\b(contagious|symptoms?|treatment|last)\b",
     ["mayoclinic.org", "medlineplus.gov", "clevelandclinic.org", "cdc.gov"]),
    ("food_safety", rf"^(?=.*\btemp(erature)?s?\b)(?=.*\b({MEAT})\b)(?=.*\b(cook|cooked|done|safe)\b)|"
                    rf"\b(cook|cooked)\b.*\b({MEAT})\b.*\b(temp(erature)?|degrees|safe|done)\b|"
                    rf"\bhow long (are|is|do|does|can|will)\b.*\b({MEAT}|food)\b.*\b(good|last|keep|safe|fridge|refrigerat\w*|freezer|counter|out)\b|"
                    rf"\b(safe|ok|okay)\b.*\b(eat|to eat)\b.*\b(raw|undercooked|pink|expired|left out|after)\b|"
                    rf"\b(thaw|defrost)\w*\b.*\b({MEAT})\b",
     ["foodsafety.gov", "fsis.usda.gov", "usda.gov"]),
    ("garden", rf"\b(when|how|how often|how much|how deep|how far apart|where|what)\b.*\b(plant|grow|growing|water|"
               rf"prune|fertiliz\w*|harvest|transplant|repot|start|sow|mulch|overwinter)\b.*\b({PLANT})\b|"
               rf"\b({PLANT})\b.*\b(turning yellow|yellow leaves|wilting|drooping|need|needs|like)\b",
     ["extension.umn.edu", "extension.psu.edu", "almanac.com", "gardening.cals.cornell.edu", "rhs.org.uk"]),
    ("movies", r"\bwho (plays|played|stars|starred|voices|voiced|directed|sings|sang|wrote the song)\b|\bcast of\b|"
               r"\bhow many (seasons|episodes)\b|\b(when|what year) did .* (come out|release|premiere|air)\b|"
               r"\bwho was in\b|\bwho is the (actor|actress|voice)\b",
     ["wikipedia.org", "imdb.com"]),
    ("people_history", r"\bwho (was|is|were) (?!at\b|in\b|on\b|home\b|here\b|there\b|calling\b|playing\b|that\b|this\b|"
                       r"it\b|my\b|your\b|you\b|the best\b|winning\b)[\w.' -]{3,}|"
                       r"\b(when|where|what year) (was|were|did) .* (born|die|died|invented|founded|built|discovered|"
                       r"start|started|end|ended|sign|signed|happen|happened|elected|become|became|sink|sank|crash|crashed|fall|fell)\b|"
                       r"\bhow old (is|was) (?!my\b|your\b|the house\b|it\b)[A-Z]|\bwho (invented|discovered|founded|wrote|painted|won)\b",
     ["wikipedia.org", "britannica.com"]),
]
ROUTES = [(n, re.compile(p, re.I), s) for n, p, s in ROUTES]


def route(q):
    q = q.strip()
    for name, rx, sites in ROUTES:
        if rx.search(q):
            return name, sites
    return None, []


def goggle(sites):
    return "\n".join(f"$boost=3,site={s}" for s in sites)


# ---------------------------------------------------------------- local answers
NUM_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen twenty".split())}
NUM_WORDS.update({"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
                  "ninety": 90, "hundred": 100, "a": 1, "an": 1, "half": 0.5, "a half": 0.5, "quarter": 0.25})
NUM = r"(\d[\d,]*(?:\.\d+)?|\.\d+|(?:%s)(?:[ -](?:%s))?)" % (("|".join(sorted(NUM_WORDS, key=len, reverse=True)),) * 2)


def num(t):
    t = t.lower().replace(",", "").strip()
    try:
        return float(t)
    except ValueError:
        parts = re.split(r"[ -]", t)
        if len(parts) == 2 and parts[0] in NUM_WORDS and parts[1] in NUM_WORDS and NUM_WORDS[parts[0]] >= 20:
            return NUM_WORDS[parts[0]] + NUM_WORDS[parts[1]]
        return NUM_WORDS.get(t)


def fmt(x):
    if x is None:
        return None
    if abs(x - round(x)) < 1e-9:
        return f"{int(round(x)):,}"
    s = f"{x:,.4f}".rstrip("0").rstrip(".")
    return s if abs(x) >= 0.001 else f"{x:.2g}"


def spell(q):
    m = (re.match(r"^(?:how (?:do|would|should) (?:you|i|we) spell|can you spell|spell|what'?s the spelling of|"
                  r"what is the spelling of)\s+(?:the word\s+)?['\"]?([a-z][a-z' -]{0,30}?)['\"]?\W*$", q, re.I)
         or re.match(r"^how (?:is|are) (?:the word\s+)?['\"]?([a-z][a-z' -]{0,30}?)['\"]? spelled\W*$", q, re.I))
    if not m:
        return None
    w = m.group(1).strip()
    if len(w.split()) > 2 or w.split()[0].lower() in ("it", "that", "this", "check", "a", "out", "me", "my", "your", "the"):
        return None
    letters = ", ".join(c.upper() if c.isalpha() else ("space" if c == " " else c) for c in w)
    return f"{w} is spelled {letters}."


OPS = {"plus": "+", "add": "+", "and": "+", "minus": "-", "less": "-", "times": "*", "multiplied by": "*",
       "x": "*", "divided by": "/", "over": "/", "to the power of": "**"}


def calc(q):
    t = q.lower().strip(" ?.!")
    t = re.sub(r"^(what(?:'s| is)|whats|how much is|calculate|compute|what do you get (?:for|if you multiply))\s+", "", t)
    m = re.fullmatch(rf"{NUM}\s*(?:percent|%)\s+of\s+{NUM}", t)
    if m:
        a, b = num(m.group(1)), num(m.group(2))
        return f"{fmt(a)} percent of {fmt(b)} is {fmt(a / 100 * b)}." if None not in (a, b) else None
    m = re.fullmatch(rf"(?:the\s+)?square root of\s+{NUM}", t)
    if m and num(m.group(1)) is not None:
        return f"The square root of {fmt(num(m.group(1)))} is {fmt(math.sqrt(num(m.group(1))))}."
    m = re.fullmatch(rf"{NUM}\s+(squared|cubed)", t)
    if m and num(m.group(1)) is not None:
        a = num(m.group(1))
        return f"{fmt(a)} {m.group(2)} is {fmt(a ** (2 if m.group(2) == 'squared' else 3))}."
    m = re.fullmatch(rf"{NUM}\s*(plus|minus|times|multiplied by|x|\*|divided by|over|/|\+|-|to the power of)\s*{NUM}", t)
    if not m:
        return None
    a, b = num(m.group(1)), num(m.group(3))
    op = OPS.get(m.group(2), m.group(2))
    if None in (a, b) or (op == "/" and b == 0) or (op == "**" and abs(b) > 20):
        return None
    r = {"+": lambda: a + b, "-": lambda: a - b, "*": lambda: a * b, "/": lambda: a / b, "**": lambda: a ** b}[op]()
    word = {"+": "plus", "-": "minus", "*": "times", "/": "divided by", "**": "to the power of"}[op]
    return f"{fmt(a)} {word} {fmt(b)} is {fmt(r)}."


# unit -> (kind, factor to base). base: ml, g, m
UNITS = {}
for names, kind, f in [
    ("teaspoon teaspoons tsp", "vol", 4.92892), ("tablespoon tablespoons tbsp", "vol", 14.7868),
    ("fluid ounce fluid ounces fl oz", "vol", 29.5735), ("cup cups", "vol", 236.588), ("pint pints", "vol", 473.176),
    ("quart quarts", "vol", 946.353), ("gallon gallons", "vol", 3785.41), ("milliliter milliliters ml millilitre millilitres", "vol", 1),
    ("liter liters litre litres", "vol", 1000),
    ("ounce ounces oz", "mass", 28.3495), ("pound pounds lb lbs", "mass", 453.592), ("gram grams g", "mass", 1),
    ("kilogram kilograms kilo kilos kg", "mass", 1000), ("stone", "mass", 6350.29),
    ("inch inches", "len", 0.0254), ("foot feet ft", "len", 0.3048), ("yard yards", "len", 0.9144),
    ("mile miles", "len", 1609.344), ("millimeter millimeters mm", "len", 0.001), ("centimeter centimeters cm", "len", 0.01),
    ("meter meters metre metres", "len", 1), ("kilometer kilometers km kilometre kilometres", "len", 1000),
]:
    for n in [names] if names.startswith("fluid") else names.split():
        UNITS[n] = (kind, f)
UNITS.update({"fluid ounce": ("vol", 29.5735), "fluid ounces": ("vol", 29.5735), "fl oz": ("vol", 29.5735)})
UNIT = "(" + "|".join(sorted((re.escape(u) for u in UNITS), key=len, reverse=True)) + ")"
TEMP = r"(degrees? )?(fahrenheit|celsius|centigrade|f|c)"


def unit(name, other_kind=None):
    k, f = UNITS[name]
    if name in ("ounce", "ounces", "oz") and other_kind == "vol":      # "ounces in a cup" = fluid ounces
        return "vol", 29.5735
    return k, f


def plural(u, n):
    if n == 1 or u.endswith("s") or u == "feet" or u in ("ft", "oz", "ml", "g", "kg", "km", "cm", "mm", "tsp", "tbsp", "lb", "lbs", "fl oz"):
        return u
    return {"foot": "feet", "inch": "inches"}.get(u, u + "s")


def convert(q):
    t = q.lower().strip(" ?.!")
    t = re.sub(r"^(what(?:'s| is)|whats|convert|how much is|tell me)\s+", "", t)
    # temperature
    m = re.fullmatch(rf"{NUM}\s*{TEMP}\s+(?:in|to|into|in degrees)\s+{TEMP}", t)
    if m:
        v, src, dst = num(m.group(1)), m.group(3)[0], m.group(5)[0]
        if v is None or src == dst or src not in "fc" or dst not in "fc":
            return None
        r = (v - 32) * 5 / 9 if src == "f" else v * 9 / 5 + 32
        name = {"f": "Fahrenheit", "c": "Celsius"}
        return f"{fmt(v)} degrees {name[src]} is {fmt(round(r, 1))} degrees {name[dst]}."
    # "how many X in/are in (a|N) Y"
    m = re.fullmatch(rf"how many {UNIT} (?:are )?(?:in|per|make up|make|go into|are there in|in one)\s+(?:a |an |one )?(?:{NUM} )?{UNIT}", t) \
        or re.fullmatch(rf"how many {UNIT} (?:are there )?in\s+(?:a |an |one )?(?:{NUM} )?{UNIT}", t)
    if m:
        dst_u, n_txt, src_u = m.group(1), m.group(2), m.group(3)
        n = num(n_txt) if n_txt else 1
    else:
        m = re.fullmatch(rf"{NUM}\s+{UNIT}\s+(?:in|to|into|is how many|equals how many|in how many)\s+{UNIT}", t)
        if not m:
            return None
        n, src_u, dst_u = num(m.group(1)), m.group(2), m.group(3)
    if n is None or src_u == dst_u:
        return None
    sk, sf = unit(src_u, UNITS[dst_u][0])
    dk, df = unit(dst_u, sk)
    sk, sf = unit(src_u, dk)
    if sk != dk:
        return None
    r = n * sf / df
    r = round(r, 2) if r >= 1 else round(r, 3)
    name = lambda u, k, x: ("fluid " if k == "vol" and u in ("ounce", "ounces", "oz") else "") + plural(u, x)
    if m.re.pattern.startswith("how many"):
        if n == 1:
            return f"There {'is' if r == 1 else 'are'} {fmt(r)} {name(dst_u, dk, r)} in a {name(src_u, sk, 1).removesuffix('s') if src_u.endswith('s') and src_u not in ('lbs',) else name(src_u, sk, 1)}."
        amount = n_txt if n_txt and not n_txt[0].isdigit() else fmt(n)
        return f"There {'is' if r == 1 else 'are'} {fmt(r)} {name(dst_u, dk, r)} in {'a ' if amount in ('quarter', 'half') else ''}{amount} {name(src_u, sk, n if n >= 1 else 1)}."
    return f"{fmt(n)} {name(src_u, sk, n)} is {fmt(r)} {name(dst_u, dk, r)}."


MONTHS = {m: i + 1 for i, m in enumerate("january february march april may june july august september october november december".split())}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
MONTHS["sept"] = 9


def nth_weekday(y, mo, wd, n):
    d = datetime.date(y, mo, 1)
    d += datetime.timedelta(days=(wd - d.weekday()) % 7)
    if n > 0:
        return d + datetime.timedelta(weeks=n - 1)
    last = datetime.date(y + (mo == 12), mo % 12 + 1, 1) - datetime.timedelta(days=1)
    return last - datetime.timedelta(days=(last.weekday() - wd) % 7)


def easter(y):
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    j, k = c // 4, c % 4
    m = (a + 11 * h) // 319
    r = (2 * e + 2 * j - k - h + m + 32) % 7
    n = (h - m + r + 90) // 25
    return datetime.date(y, n, (h - m + r + n + 19) % 32)


HOLIDAYS = {
    r"christmas eve": lambda y: datetime.date(y, 12, 24), r"christmas|xmas": lambda y: datetime.date(y, 12, 25),
    r"new year'?s eve": lambda y: datetime.date(y, 12, 31), r"new year'?s( day)?|the new year": lambda y: datetime.date(y, 1, 1),
    r"halloween": lambda y: datetime.date(y, 10, 31), r"valentine'?s( day)?": lambda y: datetime.date(y, 2, 14),
    r"(the )?(4th|fourth) of july|independence day|july (4th|fourth)": lambda y: datetime.date(y, 7, 4),
    r"thanksgiving": lambda y: nth_weekday(y, 11, 3, 4), r"easter": easter,
    r"memorial day": lambda y: nth_weekday(y, 5, 0, -1), r"labor day": lambda y: nth_weekday(y, 9, 0, 1),
    r"mother'?s day": lambda y: nth_weekday(y, 5, 6, 2), r"father'?s day": lambda y: nth_weekday(y, 6, 6, 3),
    r"st\.? patrick'?s day|saint patrick'?s day": lambda y: datetime.date(y, 3, 17),
    r"veterans day": lambda y: datetime.date(y, 11, 11), r"groundhog day": lambda y: datetime.date(y, 2, 2),
}


def parse_day(t, today, future=True):
    t = t.strip(" ?.!").removeprefix("the ").strip()
    for rx, fn in HOLIDAYS.items():
        if re.fullmatch(rx, t):
            d = fn(today.year)
            if future and d < today:
                d = fn(today.year + 1)
            elif not future and d > today:
                d = fn(today.year - 1)
            return d
    m = (re.fullmatch(r"([a-z]+)\.? (\d{1,2})(?:st|nd|rd|th)?(?:,? (\d{4}))?", t)
         or re.fullmatch(r"(?:the )?(\d{1,2})(?:st|nd|rd|th)? of ([a-z]+)(?:,? (\d{4}))?", t))
    if not m:
        return None
    a, b, y = m.groups()
    mon, day = (a, b) if a.isalpha() else (b, a)
    if mon not in MONTHS:
        return None
    try:
        d = datetime.date(int(y) if y else today.year, MONTHS[mon], int(day))
    except ValueError:
        return None
    if not y and future and d < today:
        d = d.replace(year=d.year + 1)
    if not y and not future and d > today:
        d = d.replace(year=d.year - 1)
    return d


def when(d, today=None):
    today = today or datetime.date.today()
    return d.strftime("%A, %B ") + str(d.day) + (f", {d.year}" if d.year != today.year else "")


def dates(q, today=None):
    today = today or datetime.date.today()
    t = q.lower().strip(" ?.!")
    m = re.fullmatch(r"how many (days|weeks|sleeps) (?:is it |are there |left )?(?:until|till|til|before|to|'til) (.+?)(?: is| are)?", t) \
        or re.fullmatch(r"how (?:long|many days) (?:is it |are there )?(?:until|till|til|before) (.+?)(?: is)?()", t)
    if m:
        unit_, target = (m.group(1), m.group(2)) if m.lastindex == 2 and m.group(1) in ("days", "weeks", "sleeps") else ("days", m.group(1))
        d = parse_day(target, today, True)
        if not d:
            return None
        n = (d - today).days
        name = target.strip().removeprefix("the ")
        if n == 0:
            return f"{name[:1].upper() + name[1:]} is today!"
        if unit_ == "weeks":
            return f"{name[:1].upper() + name[1:]} is {fmt(round(n / 7, 1))} weeks away, on {when(d, today)}."
        return f"{name[:1].upper() + name[1:]} is {n} day{'s' * (n != 1)} away, on {when(d, today)}."
    m = re.fullmatch(r"how many days (?:has it been |ago was |since )?(?:since )?(.+?)(?: was)?", t)
    if m and "since" in t:
        d = parse_day(m.group(1), today, False)
        if not d:
            return None
        n = (today - d).days
        return f"It has been {n} day{'s' * (n != 1)} since {when(d, today)}."
    m = re.fullmatch(r"what day (?:of the week )?(?:is|was|will be|does|did) (.+?)(?: (?:fall on|land on|on|be|this year|next year))*", t)
    if m:
        target = m.group(1).strip()
        if target in ("it", "today", "tomorrow", "yesterday", "it today"):
            return None                                   # Home Assistant answers these itself
        d = parse_day(target, today, "was" not in t and "did" not in t)
        return f"{target[:1].upper() + target[1:]} is on {when(d, today)}." if d else None
    return None


def tidy(a):
    a = re.sub(r"\b(" + "|".join(m for m in MONTHS if len(m) > 4) + r"|july|june|march|april)\b",
               lambda m: m.group(1).capitalize(), a)
    return a[:1].upper() + a[1:]


def local_answer(q, today=None):
    """Spoken answer for spelling, arithmetic, unit and date questions, or None to search instead."""
    q = re.sub(r"^\W+|^(please|hey|so|um|uh|okay|ok)\W+|\W*\bplease\b\W*$", "", q.strip(), flags=re.I).strip()
    for fn in (spell, calc, convert, lambda x: dates(x, today)):
        try:
            a = fn(q)
        except Exception:
            a = None
        if a:
            return tidy(a)
    return None
