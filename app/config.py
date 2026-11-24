from dotenv import load_dotenv
import os

load_dotenv()

def _flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./fish_journal.db")
    cors_origins: list[str] = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
    # Auth is ON unless AUTH_DISABLED=true (local development only).
    auth_disabled: bool = _flag("AUTH_DISABLED")
    jwt_secret: str = os.getenv("JWT_SECRET", "")
    access_token_minutes: int = int(os.getenv("ACCESS_TOKEN_MINUTES", "15"))
    refresh_token_days: int = int(os.getenv("REFRESH_TOKEN_DAYS", "30"))
    login_max_attempts: int = int(os.getenv("LOGIN_MAX_ATTEMPTS", "5"))
    login_lock_minutes: int = int(os.getenv("LOGIN_LOCK_MINUTES", "15"))
    enable_docs: bool = _flag("ENABLE_DOCS")


settings = Settings()


def validate_settings():
    """Refuse to start an unprotected or weakly protected server by accident."""
    if settings.auth_disabled:
        return
    if len(settings.jwt_secret) < 32:
        raise RuntimeError(
            "JWT_SECRET must be set to a random string of at least 32 characters "
            "(or set AUTH_DISABLED=true for local development only)."
        )
