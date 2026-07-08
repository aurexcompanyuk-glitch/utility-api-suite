"""
Utility API Suite — 7 verified API products in one deployment.
Deploy once (Railway / Render / Fly.io), list each product separately
on Zyla API Hub and API.market.

Run locally:  uvicorn main:app --reload
"""

import hashlib
import math
import random
import re
import secrets
import string
import time
import unicodedata
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI(
    title="Utility API Suite",
    version="1.0.0",
    description="7 developer utility APIs: email validation, user-agent parsing, "
                "profanity filtering, password strength, text analysis, "
                "unit conversion, mock data.",
)


@app.get("/", tags=["meta"])
def index():
    return {
        "name": "Utility API Suite",
        "products": [
            "/v1/email/validate",
            "/v1/useragent/parse",
            "/v1/moderation/check",
            "/v1/password/strength",
            "/v1/text/analyze",
            "/v1/convert/units",
            "/v1/mock/person",
        ],
        "docs": "/docs",
    }


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


# ---------------------------------------------------------------------------
# 1. EMAIL VALIDATION API
# ---------------------------------------------------------------------------

DISPOSABLE_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com",
    "temp-mail.org", "yopmail.com", "throwawaymail.com", "getnada.com",
    "maildrop.cc", "sharklasers.com", "trashmail.com", "fakeinbox.com",
    "dispostable.com", "mailnesia.com", "spamgourmet.com", "mytemp.email",
}

ROLE_ACCOUNTS = {
    "admin", "info", "support", "sales", "contact", "help", "noreply",
    "no-reply", "postmaster", "webmaster", "abuse", "billing", "hr", "office",
}

EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$"
)

COMMON_TYPO_DOMAINS = {
    "gmial.com": "gmail.com", "gmal.com": "gmail.com", "gamil.com": "gmail.com",
    "gmail.co": "gmail.com", "hotmial.com": "hotmail.com",
    "hotmal.com": "hotmail.com", "outlok.com": "outlook.com",
    "yaho.com": "yahoo.com", "yahooo.com": "yahoo.com", "iclod.com": "icloud.com",
}


@app.get("/v1/email/validate", tags=["1. Email Validation"])
def validate_email(email: str = Query(..., description="Email address to validate")):
    """Validate email syntax, detect disposable domains, role accounts,
    common typos, and check MX records (if dnspython is installed)."""
    email = email.strip().lower()
    syntax_valid = bool(EMAIL_RE.match(email)) and len(email) <= 254

    local, _, domain = email.partition("@")

    mx_found = None
    if syntax_valid:
        try:
            import dns.resolver  # optional dependency
            try:
                answers = dns.resolver.resolve(domain, "MX", lifetime=3)
                mx_found = len(answers) > 0
            except Exception:
                mx_found = False
        except ImportError:
            mx_found = None  # MX check unavailable in this deployment

    is_disposable = domain in DISPOSABLE_DOMAINS
    is_role = local in ROLE_ACCOUNTS
    suggestion = COMMON_TYPO_DOMAINS.get(domain)

    score = 0
    if syntax_valid:
        score += 40
        if mx_found:
            score += 30
        elif mx_found is None:
            score += 15
        if not is_disposable:
            score += 20
        if not is_role:
            score += 10

    return {
        "email": email,
        "is_valid_syntax": syntax_valid,
        "mx_records_found": mx_found,
        "is_disposable": is_disposable,
        "is_role_account": is_role,
        "did_you_mean": f"{local}@{suggestion}" if suggestion else None,
        "deliverability_score": min(score, 100),
        "verdict": "deliverable" if score >= 70 else "risky" if score >= 40 else "undeliverable",
    }


# ---------------------------------------------------------------------------
# 3. USER-AGENT PARSER API
# ---------------------------------------------------------------------------

UA_BROWSERS = [
    ("Edg/", "Microsoft Edge"), ("OPR/", "Opera"), ("SamsungBrowser/", "Samsung Internet"),
    ("Firefox/", "Firefox"), ("Chrome/", "Chrome"), ("Safari/", "Safari"), ("MSIE", "Internet Explorer"),
]

UA_OS = [
    ("Windows NT 10", "Windows 10/11"), ("Windows NT", "Windows"),
    ("iPhone OS", "iOS"), ("iPad", "iPadOS"), ("Mac OS X", "macOS"),
    ("Android", "Android"), ("CrOS", "ChromeOS"), ("Linux", "Linux"),
]

BOT_SIGNS = ["bot", "crawler", "spider", "curl/", "wget/", "python-requests", "scrapy", "headless"]


@app.get("/v1/useragent/parse", tags=["3. User-Agent Parser"])
def parse_user_agent(ua: str = Query(..., description="User-Agent string")):
    """Parse a User-Agent string into browser, OS, device type, and bot detection."""
    ua_lower = ua.lower()

    browser, browser_version = "Unknown", None
    for token, name in UA_BROWSERS:
        if token.lower() in ua_lower:
            browser = name
            m = re.search(re.escape(token) + r"([\d.]+)", ua)
            browser_version = m.group(1) if m else None
            break

    os_name = next((name for token, name in UA_OS if token.lower() in ua_lower), "Unknown")

    if "ipad" in ua_lower or ("android" in ua_lower and "mobile" not in ua_lower):
        device = "tablet"
    elif any(t in ua_lower for t in ("mobile", "iphone", "android")):
        device = "mobile"
    else:
        device = "desktop"

    is_bot = any(sign in ua_lower for sign in BOT_SIGNS)

    return {
        "user_agent": ua,
        "browser": browser,
        "browser_version": browser_version,
        "os": os_name,
        "device_type": "bot" if is_bot else device,
        "is_bot": is_bot,
    }


# ---------------------------------------------------------------------------
# 4. CONTENT MODERATION / PROFANITY API
# ---------------------------------------------------------------------------

PROFANITY_MILD = {"damn", "hell", "crap", "piss", "sucks"}
PROFANITY_STRONG = {"shit", "fuck", "fucking", "fucked", "bitch", "asshole",
                    "bastard", "dick", "cunt", "wanker", "bollocks", "prick"}

LEET_MAP = str.maketrans("013457@$!", "oieastasi")


class ModerationRequest(BaseModel):
    text: str
    mask_char: str = "*"


@app.post("/v1/moderation/check", tags=["4. Content Moderation"])
def moderate_text(req: ModerationRequest):
    """Detect and censor profanity, including basic leetspeak evasion.
    Returns severity score and a cleaned version of the text."""
    if len(req.text) > 20000:
        raise HTTPException(400, "Text exceeds 20,000 character limit")

    words = re.findall(r"[\w@$!]+", req.text)
    flagged = []
    for w in words:
        normalized = w.lower().translate(LEET_MAP)
        if normalized in PROFANITY_STRONG:
            flagged.append({"word": w, "severity": "strong"})
        elif normalized in PROFANITY_MILD:
            flagged.append({"word": w, "severity": "mild"})

    cleaned = req.text
    for item in flagged:
        w = item["word"]
        cleaned = re.sub(
            rf"\b{re.escape(w)}\b",
            w[0] + req.mask_char * (len(w) - 1),
            cleaned,
        )

    strong = sum(1 for f in flagged if f["severity"] == "strong")
    mild = len(flagged) - strong
    score = min(strong * 30 + mild * 10, 100)

    return {
        "contains_profanity": bool(flagged),
        "severity_score": score,
        "verdict": "blocked" if score >= 60 else "review" if score >= 20 else "clean",
        "flagged_words": flagged,
        "cleaned_text": cleaned,
    }


# ---------------------------------------------------------------------------
# 5. PASSWORD STRENGTH API
# ---------------------------------------------------------------------------

COMMON_PASSWORDS = {
    "password", "123456", "12345678", "qwerty", "abc123", "letmein", "111111",
    "iloveyou", "admin", "welcome", "monkey", "dragon", "master", "login",
    "princess", "sunshine", "football", "baseball", "starwars", "passw0rd",
}


class PasswordRequest(BaseModel):
    password: str


@app.post("/v1/password/strength", tags=["5. Password Strength"])
def password_strength(req: PasswordRequest):
    """Analyze password strength: entropy, character variety, common-password
    check, and estimated crack time. Also returns a suggested strong password."""
    pw = req.password
    if len(pw) > 256:
        raise HTTPException(400, "Password exceeds 256 characters")

    pool = 0
    if re.search(r"[a-z]", pw): pool += 26
    if re.search(r"[A-Z]", pw): pool += 26
    if re.search(r"\d", pw): pool += 10
    if re.search(r"[^a-zA-Z0-9]", pw): pool += 33

    entropy = round(len(pw) * math.log2(pool), 1) if pool else 0.0
    is_common = pw.lower() in COMMON_PASSWORDS

    guesses = 2 ** entropy
    seconds = guesses / 1e10  # 10B guesses/sec (offline GPU attack)
    units = [("years", 31536000), ("days", 86400), ("hours", 3600), ("minutes", 60), ("seconds", 1)]
    crack_time = "instant"
    for unit, div in units:
        if seconds >= div:
            val = seconds / div
            crack_time = f"{val:,.0f} {unit}" if val < 1e15 else "centuries"
            break

    if is_common or entropy < 28:
        rating = "very_weak"
    elif entropy < 40:
        rating = "weak"
    elif entropy < 60:
        rating = "moderate"
    elif entropy < 80:
        rating = "strong"
    else:
        rating = "very_strong"

    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    suggestion = "".join(secrets.choice(alphabet) for _ in range(16))

    return {
        "length": len(pw),
        "entropy_bits": entropy,
        "is_common_password": is_common,
        "estimated_crack_time": "instant" if is_common else crack_time,
        "rating": rating,
        "suggested_password": suggestion,
    }


# ---------------------------------------------------------------------------
# 7. TEXT ANALYSIS API
# ---------------------------------------------------------------------------

class TextRequest(BaseModel):
    text: str


@app.post("/v1/text/analyze", tags=["7. Text Analysis"])
def analyze_text(req: TextRequest):
    """Word count, reading time, readability score, slug, and case conversions
    in one call. Ideal for CMS platforms and writing tools."""
    text = req.text
    if len(text) > 100_000:
        raise HTTPException(400, "Text exceeds 100,000 character limit")

    words = re.findall(r"[a-zA-Z0-9']+", text)
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]

    def syllables(word: str) -> int:
        word = word.lower()
        count = len(re.findall(r"[aeiouy]+", word))
        if word.endswith("e") and count > 1:
            count -= 1
        return max(count, 1)

    total_syllables = sum(syllables(w) for w in words)
    n_words, n_sentences = max(len(words), 1), max(len(sentences), 1)
    flesch = round(206.835 - 1.015 * (n_words / n_sentences) - 84.6 * (total_syllables / n_words), 1)

    slug = unicodedata.normalize("NFKD", text[:80]).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-")

    return {
        "characters": len(text),
        "words": len(words),
        "sentences": len(sentences),
        "avg_word_length": round(sum(len(w) for w in words) / n_words, 2),
        "reading_time_minutes": round(len(words) / 225, 2),
        "flesch_reading_ease": max(min(flesch, 121.2), -100),
        "readability": ("very_easy" if flesch >= 80 else "easy" if flesch >= 60
                        else "moderate" if flesch >= 40 else "difficult"),
        "slug": slug,
        "cases": {
            "upper": text[:200].upper(),
            "lower": text[:200].lower(),
            "title": text[:200].title(),
        },
    }


# ---------------------------------------------------------------------------
# 8. UNIT CONVERTER API
# ---------------------------------------------------------------------------

# Everything normalized to a base unit per category
UNITS = {
    "length": {"mm": 0.001, "cm": 0.01, "m": 1, "km": 1000, "in": 0.0254,
               "ft": 0.3048, "yd": 0.9144, "mi": 1609.344, "nmi": 1852},
    "mass": {"mg": 0.001, "g": 1, "kg": 1000, "t": 1e6, "oz": 28.3495,
             "lb": 453.592, "st": 6350.29},
    "volume": {"ml": 0.001, "l": 1, "m3": 1000, "tsp": 0.00492892,
               "tbsp": 0.0147868, "cup": 0.24, "pt": 0.473176,
               "qt": 0.946353, "gal": 3.78541, "floz": 0.0295735},
    "speed": {"mps": 1, "kph": 0.277778, "mph": 0.44704, "knot": 0.514444},
    "data": {"b": 1, "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12,
             "kib": 1024, "mib": 1024**2, "gib": 1024**3, "tib": 1024**4},
    "area": {"m2": 1, "km2": 1e6, "ft2": 0.092903, "acre": 4046.86, "ha": 10000},
    "energy": {"j": 1, "kj": 1000, "cal": 4.184, "kcal": 4184, "kwh": 3.6e6, "btu": 1055.06},
}


@app.get("/v1/convert/units", tags=["8. Unit Converter"])
def convert_units(
    value: float = Query(...),
    from_unit: str = Query(..., alias="from"),
    to_unit: str = Query(..., alias="to"),
):
    """Convert between 50+ units across length, mass, volume, speed, data,
    area, energy, and temperature."""
    f, t = from_unit.lower(), to_unit.lower()

    # Temperature is affine, handled separately
    temps = {"c", "f", "k"}
    if f in temps and t in temps:
        celsius = {"c": value, "f": (value - 32) * 5 / 9, "k": value - 273.15}[f]
        result = {"c": celsius, "f": celsius * 9 / 5 + 32, "k": celsius + 273.15}[t]
        return {"value": value, "from": f, "to": t, "result": round(result, 6), "category": "temperature"}

    for category, table in UNITS.items():
        if f in table and t in table:
            result = value * table[f] / table[t]
            return {"value": value, "from": f, "to": t, "result": round(result, 8), "category": category}

    raise HTTPException(400, f"Cannot convert '{from_unit}' to '{to_unit}'. "
                             f"Units must be in the same category. See /v1/convert/units/list")


@app.get("/v1/convert/units/list", tags=["8. Unit Converter"])
def list_units():
    return {**{k: list(v) for k, v in UNITS.items()}, "temperature": ["c", "f", "k"]}


# ---------------------------------------------------------------------------
# 10. MOCK DATA GENERATOR API
# ---------------------------------------------------------------------------

FIRST_NAMES = ["James", "Olivia", "Liam", "Emma", "Noah", "Sophia", "Lucas", "Mia",
               "Oscar", "Isabella", "Leo", "Charlotte", "Hugo", "Amelia", "Felix",
               "Chloe", "Marco", "Elena", "Rafael", "Aria", "Kai", "Zara", "Mateo", "Nina"]
LAST_NAMES = ["Smith", "Johnson", "Garcia", "Müller", "Rossi", "Dubois", "Silva",
              "Novak", "Andersen", "Costa", "Laurent", "Weber", "Marino", "Berg",
              "Fontaine", "Ricci", "Larsen", "Moreau", "Klein", "Santos"]
CITIES = [("London", "UK"), ("Paris", "FR"), ("Milan", "IT"), ("Monaco", "MC"),
          ("Geneva", "CH"), ("Madrid", "ES"), ("Berlin", "DE"), ("Amsterdam", "NL"),
          ("Lisbon", "PT"), ("Vienna", "AT"), ("New York", "US"), ("Dubai", "AE")]
STREETS = ["High Street", "King's Road", "Rue de Rivoli", "Via Roma", "Marktgasse",
           "Ocean Drive", "Park Avenue", "Baker Street", "Gran Via", "Kaiserstrasse"]
COMPANIES = ["Nexora", "Vantik", "Solaria Labs", "Bluepeak", "Orbit & Co",
             "Meridian Group", "Astrea", "Northwind", "Helios Partners", "Cobalt Systems"]
JOBS = ["Software Engineer", "Product Manager", "Data Analyst", "Designer",
        "Marketing Lead", "Account Executive", "Operations Manager", "Consultant"]


@app.get("/v1/mock/person", tags=["10. Mock Data Generator"])
def mock_people(
    count: int = Query(1, ge=1, le=100),
    seed: Optional[int] = Query(None, description="Seed for reproducible results"),
):
    """Generate realistic fake user profiles for testing and prototyping.
    Deterministic when a seed is provided."""
    rng = random.Random(seed)
    people = []
    for _ in range(count):
        first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        city, country = rng.choice(CITIES)
        username = f"{first.lower()}.{last.lower()}{rng.randint(1, 99)}"
        uid = hashlib.sha1(f"{username}{rng.random()}".encode()).hexdigest()[:12]
        people.append({
            "id": uid,
            "first_name": first,
            "last_name": last,
            "email": f"{username}@example.com",
            "username": username,
            "phone": f"+{rng.randint(1, 49)} {rng.randint(100, 999)} {rng.randint(100, 999)} {rng.randint(1000, 9999)}",
            "date_of_birth": f"{rng.randint(1960, 2005)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
            "address": {
                "street": f"{rng.randint(1, 200)} {rng.choice(STREETS)}",
                "city": city,
                "country": country,
                "postcode": f"{rng.randint(10000, 99999)}",
            },
            "company": rng.choice(COMPANIES),
            "job_title": rng.choice(JOBS),
            "avatar": f"https://i.pravatar.cc/300?u={uid}",
        })
    return {"count": count, "seed": seed, "results": people}


# ---------------------------------------------------------------------------
# Error handler — clean JSON errors for marketplace consumers
# ---------------------------------------------------------------------------

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code,
                        content={"error": exc.detail, "status": exc.status_code})
