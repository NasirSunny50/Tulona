"""Shared scraped-data structures (source-agnostic)."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class ScrapedVariant:
    raw_label: str                 # e.g. "8/256GB | Black" or "8/256GB"
    ram_gb: int | None = None
    rom_gb: int | None = None
    color: str | None = None
    price: Decimal | None = None
    currency: str = "BDT"
    warranty: str | None = None
    in_stock: bool | None = None


@dataclass
class ScrapedProduct:
    source_slug: str
    url: str
    model_name: str
    brand: str | None = None
    source_product_id: str | None = None
    category_path: list[str] = field(default_factory=list)  # breadcrumb names
    image_url: str | None = None
    spec: dict = field(default_factory=dict)
    variants: list[ScrapedVariant] = field(default_factory=list)
