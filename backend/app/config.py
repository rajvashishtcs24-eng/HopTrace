"""
Application configuration.

Settings are read from environment variables (and from a .env file when
python-dotenv is present).  Defaults are safe for local development.
Never put real credentials here; use a .env file that is git-ignored.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- API ---
    app_version: str = "0.1.0"

    # --- CORS ---
    # Comma-separated list of allowed origins for CORS.
    # Default: only the local Vite dev server used by Member 3 (frontend).
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # --- Topology provider ---
    # "simulated"  – use the built-in SimulatedTopologyProvider (no Neo4j needed)
    # "neo4j"      – use the Neo4jTopologyProvider (Member 1's implementation)
    topology_provider: str = "simulated"

    # --- Dependency analysis adapter ---
    # "unavailable" – default honest behavior when Member 1's engine is not connected (returns 503)
    # "simulated"   – simulated dependency mapping for demos/testbed
    # "neo4j"       – Member 1's Neo4j dependency engine
    dependency_adapter: str = "unavailable"

    # Neo4j connection (only used when topology_provider == "neo4j")
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # --- SQLite Database ---
    sqlite_db_path: str = "hoptrace.db"
    seed_demo_subscribers: bool = True
    seed_demo_incidents: bool = True


settings = Settings()
