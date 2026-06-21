"""Normalization helpers: parse RAM/ROM/color, price, slug, variant keys.

These are shared across all source scrapers so the canonical catalog stays
consistent regardless of how each site phrases things.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

# ---------------------------------------------------------------------------
# Storage / RAM-ROM
# ---------------------------------------------------------------------------
_UNIT_TB = re.compile(r"(\d+(?:\.\d+)?)\s*TB", re.I)
_UNIT_GB = re.compile(r"(\d+(?:\.\d+)?)\s*GB", re.I)


def _to_gb(token: str) -> int | None:
    """'256GB' -> 256, '1TB' -> 1024, '512' -> 512."""
    token = token.strip()
    m = _UNIT_TB.search(token)
    if m:
        return int(float(m.group(1)) * 1024)
    m = _UNIT_GB.search(token)
    if m:
        return int(float(m.group(1)))
    if token.isdigit():
        return int(token)
    return None


def parse_ram_rom(label: str) -> tuple[int | None, int | None]:
    """Parse '8/256GB', '8GB/256GB', '8 GB + 256 GB', '12/512' -> (ram, rom).

    By convention the smaller number is RAM, the larger is ROM/storage.
    """
    if not label:
        return None, None
    # split on '/', '+', or whitespace between two size tokens
    parts = re.split(r"[/+]", label)
    if len(parts) >= 2:
        ram = _to_gb(parts[0])
        rom = _to_gb(parts[1])
        if ram and rom and ram > rom:          # guard against reversed order
            ram, rom = rom, ram
        return ram, rom
    # single token -> treat as storage
    one = _to_gb(label)
    return None, one


# A "color" that actually looks like a storage token (e.g. "6/128Gb") is bad
# source data and must not be stored as a color.
_STORAGE_LIKE = re.compile(r"\d+\s*/\s*\d+|\d+\s*(GB|TB)", re.I)


def _looks_like_storage(token: str) -> bool:
    return bool(token and _STORAGE_LIKE.search(token))


def parse_variant_string(s: str) -> tuple[int | None, int | None, str | None]:
    """Parse a combined variant label like '8/256GB | Black' -> (8, 256, 'Black')."""
    if not s:
        return None, None, None
    color = None
    storage = s
    if "|" in s:
        storage, color = (p.strip() for p in s.split("|", 1))
    ram, rom = parse_ram_rom(storage)
    if _looks_like_storage(color):       # reject storage leaked into color slot
        color = None
    return ram, rom, (color or None)


# ---------------------------------------------------------------------------
# Price
# ---------------------------------------------------------------------------
_PRICE_RE = re.compile(r"[\d,]+(?:\.\d+)?")


def parse_price(text: str) -> Decimal | None:
    """'৳48,999' / '48999' / 'Tk 1,23,456' -> Decimal."""
    if text is None:
        return None
    m = _PRICE_RE.search(str(text).replace(" ", ""))
    if not m:
        return None
    try:
        return Decimal(m.group(0).replace(",", ""))
    except InvalidOperation:
        return None


# ---------------------------------------------------------------------------
# Color / slug / variant key
# ---------------------------------------------------------------------------
def normalize_color(color: str | None) -> str | None:
    if not color:
        return None
    c = re.sub(r"\s+", " ", color.strip()).title()
    return c or None


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "item"


def clean_model_display(brand: str | None, model: str) -> str:
    """Human display name: drop a leading brand prefix and the BD '(Official)' tag.

    'Samsung Galaxy A17 4G'      -> 'Galaxy A17 4G'
    'Galaxy A17 5G (Official)'   -> 'Galaxy A17 5G'
    """
    m = model.strip()
    if brand:
        m = re.sub(rf"^{re.escape(brand)}\s+", "", m, flags=re.I)
    # drop the BD "official" marker (with or without parentheses): official and
    # unofficial are the same phone, just different warranty/price (shown per-listing).
    m = re.sub(r"\s*\(?\bofficial\b\)?\s*", " ", m, flags=re.I)
    return re.sub(r"\s+", " ", m).strip() or model.strip()


def normalize_model(brand: str | None, model: str) -> str:
    """Canonical match key. Brand-stripped, lowercase, punctuation-flattened.

    '(Official)' is dropped (BD warranty marker, not a different phone), but
    distinguishing tokens like 4g/5g/pro/max/plus/snapdragon are kept.
    All of 'Galaxy A17 4G', 'Samsung Galaxy A17 4G' -> 'galaxy a17 4g'.
    """
    m = clean_model_display(brand, model).lower()
    m = re.sub(r"[^a-z0-9]+", " ", m)
    return re.sub(r"\s+", " ", m).strip()


# Non-phone products (tablets, laptops, audio, wearables, accessories) that
# sometimes appear in a site's "phone" category and must be excluded.
_NON_PHONE_RE = re.compile(
    r"\b("
    r"tablet|tab\s|\bpad\b|\bbook\b|laptop|notebook|macbook|"
    r"buds|\btws\b|earphone|earbud|headphone|airpod|speaker|soundbar|"
    r"watch|smartwatch|\bband\b|tracker|"
    r"case|cover|glass|protector|tempered|charger|cable|adapter|"
    r"powerbank|power\s*bank|strap|holder|stand|mount|gimbal|"
    r"keyboard|mouse|dock|stylus|pen\b|gear\b"
    r")\b",
    re.I,
)


def is_phone(model_name: str) -> bool:
    """Heuristic: is this a phone (vs tablet/laptop/audio/wearable/accessory)?"""
    return bool(model_name) and not _NON_PHONE_RE.search(model_name)


def model_signature(normalized: str) -> frozenset[str]:
    """Identity-bearing tokens of a normalized model = those containing a digit.

    'galaxy a17 4g' -> {'a17', '4g'};  'galaxy a15 4g' -> {'a15', '4g'}.
    Two models with different signatures are different phones (A17 != A15),
    so they must never be offered as a merge candidate.
    """
    return frozenset(t for t in normalized.split() if any(ch.isdigit() for ch in t))


def variant_key(ram_gb: int | None, rom_gb: int | None, color: str | None) -> str:
    """Stable dedup key for a variant, e.g. '8-256-black'."""
    parts = [
        str(ram_gb) if ram_gb else "x",
        str(rom_gb) if rom_gb else "x",
        slugify(color) if color else "x",
    ]
    return "-".join(parts)
