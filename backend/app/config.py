"""Central config loaded from environment (.env)."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://tulona:tulona@localhost:5432/tulona"

    scrape_delay_seconds: float = 1.0
    scrape_user_agent: str = (
        "Mozilla/5.0 (compatible; TulonaBot/0.1; +https://tulona.local)"
    )

    # Scheduler (24h clock, local time)
    refresh_hours: str = "12,15,18,21"   # 4x/day price refresh (12pm,3,6,9pm)
    discovery_hour: int = 3              # 1x/day catalog discovery (3am)
    timezone: str = "Asia/Dhaka"

    @property
    def refresh_hour_list(self) -> list[int]:
        return [int(h) for h in self.refresh_hours.split(",") if h.strip()]


settings = Settings()
