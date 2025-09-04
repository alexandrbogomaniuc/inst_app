from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from pathlib import Path

class Settings(BaseSettings):
    # define lower-case attributes but read from UPPER env names
    db_url: str = Field(..., alias="DB_URL")
    jwt_signing_key: str = Field(..., alias="JWT_SIGNING_KEY")

    ig_client_id: str = Field(..., alias="IG_CLIENT_ID")
    ig_client_secret: str = Field(..., alias="IG_CLIENT_SECRET")
    ig_redirect_uri: str = Field(..., alias="IG_REDIRECT_URI")

    # optional
    graph_version: str = Field("v20.0", alias="GRAPH_VERSION")
    cors_origins: str | None = Field("*", alias="CORS_ORIGINS")

    model_config = SettingsConfigDict(
        env_file=(str(Path(__file__).resolve().parents[1] / ".env"),
                  str(Path(__file__).resolve().parents[2] / ".env")),
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )

settings = Settings()
print(f"Loaded settings (.env=found) from: {settings.model_config['env_file'][0] if settings.model_config.get('env_file') else 'ENV ONLY'}")
