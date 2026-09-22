from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "PropLens"
    environment: str = "development"
    database_url: str
    secret_key: str = "change-this-secret-later"
    access_token_expire_minutes: int = 10080

    # Scraping — Publi24
    scraping_scheduler_enabled: bool = True
    scrape_publi24_interval_minutes: int = 15
    scrape_publi24_max_pages: int = 20
    scrape_manual_cooldown_minutes: int = 5

    # Scraping — Imobiliare.ro
    scrape_imobiliare_ro_enabled: bool = False
    scrape_imobiliare_ro_authorized: bool = False
    scrape_imobiliare_ro_mode: str = "live"
    scrape_imobiliare_ro_interval_minutes: int = 30
    scrape_imobiliare_ro_max_pages: int = 100
    scrape_imobiliare_ro_request_delay_seconds: float = 2.0
    scrape_imobiliare_ro_max_concurrency: int = 1
    scrape_imobiliare_ro_max_retries: int = 2
    scrape_imobiliare_ro_request_timeout_seconds: int = 30
    scrape_imobiliare_ro_inactive_threshold: int = 3

    # Scraping — Romimo.ro
    scrape_romimo_enabled: bool = False          # activat manual după prima importare verificată
    scrape_romimo_interval_minutes: int = 30
    scrape_romimo_max_pages: int = 50
    romimo_request_delay_seconds: float = 1.5    # delay politicos între requesturi
    romimo_max_retries: int = 2
    romimo_request_timeout_seconds: int = 30

    # Scraping — Storia.ro
    scrape_storia_enabled: bool = False
    scrape_storia_interval_minutes: int = 30
    scrape_storia_max_pages: int = 25
    storia_request_delay_seconds: float = 1.5    # delay politicos între requesturi
    storia_request_timeout_seconds: int = 30

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
