from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", PROJECT_ROOT / ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    llm_model: str = Field(
        default="meta-llama/llama-3.3-70b-instruct:free", alias="LLM_MODEL"
    )
    llm_base_url: str = Field(
        default="https://openrouter.ai/api/v1", alias="LLM_BASE_URL"
    )
    llm_temperature: float = Field(default=0.0, alias="LLM_TEMPERATURE")
    llm_max_output_tokens: int = Field(default=500, alias="LLM_MAX_OUTPUT_TOKENS")
    local_llm: bool = Field(default=True, alias="GLASSBOX_LOCAL_LLM")
    llm_router_order: str = Field(
        default="ollama,vllm,openrouter", alias="LLM_ROUTER_ORDER"
    )
    llm_timeout_seconds: float = Field(default=20.0, alias="LLM_TIMEOUT_SECONDS")
    llm_max_retries: int = Field(default=1, alias="LLM_MAX_RETRIES")
    llm_retry_backoff_seconds: float = Field(
        default=0.25, alias="LLM_RETRY_BACKOFF_SECONDS"
    )
    verify_mode: str = Field(default="auto", alias="VERIFY_MODE")
    production_mode: bool = Field(default=False, alias="GLASSBOX_PRODUCTION_MODE")
    allow_openrouter_free_in_production: bool = Field(
        default=False, alias="ALLOW_OPENROUTER_FREE_IN_PRODUCTION"
    )
    approved_models: str = Field(default="", alias="APPROVED_MODELS")
    model_candidate_routes: str = Field(
        default="ollama:qwen2.5-coder:1.5b,vllm:Qwen/Qwen2.5-7B-Instruct,openrouter:meta-llama/llama-3.3-70b-instruct:free",
        alias="MODEL_CANDIDATE_ROUTES",
    )
    require_recent_model_eval_in_production: bool = Field(
        default=True, alias="REQUIRE_RECENT_MODEL_EVAL_IN_PRODUCTION"
    )
    model_eval_freshness_hours: int = Field(
        default=168, alias="MODEL_EVAL_FRESHNESS_HOURS"
    )
    model_health_cache_ttl_seconds: int = Field(
        default=30, alias="MODEL_HEALTH_CACHE_TTL_SECONDS"
    )
    model_approval_cache_ttl_seconds: int = Field(
        default=300, alias="MODEL_APPROVAL_CACHE_TTL_SECONDS"
    )
    retrieval_cache_ttl_seconds: int = Field(
        default=600, alias="RETRIEVAL_CACHE_TTL_SECONDS"
    )

    ollama_base_url: str = Field(
        default="http://localhost:11434", alias="OLLAMA_BASE_URL"
    )
    ollama_model: str = Field(default="llama3.1:8b", alias="OLLAMA_MODEL")
    ollama_keep_alive: str = Field(default="10m", alias="OLLAMA_KEEP_ALIVE")
    vllm_base_url: str = Field(default="http://localhost:8002/v1", alias="VLLM_BASE_URL")
    vllm_model: str = Field(default="Qwen/Qwen2.5-7B-Instruct", alias="VLLM_MODEL")

    eval_min_outcome_accuracy: float = Field(
        default=0.92, alias="EVAL_MIN_OUTCOME_ACCURACY"
    )
    eval_min_citation_accuracy: float = Field(
        default=0.95, alias="EVAL_MIN_CITATION_ACCURACY"
    )
    eval_max_hallucination_rate: float = Field(
        default=0.02, alias="EVAL_MAX_HALLUCINATION_RATE"
    )
    eval_min_determinism: float = Field(default=0.9, alias="EVAL_MIN_DETERMINISM")
    eval_max_avg_latency_ms: int = Field(default=3000, alias="EVAL_MAX_AVG_LATENCY_MS")
    eval_max_p95_latency_ms: int = Field(default=3000, alias="EVAL_MAX_P95_LATENCY_MS")
    eval_min_retrieval_recall: float = Field(
        default=0.85, alias="EVAL_MIN_RETRIEVAL_RECALL"
    )
    eval_min_faithfulness: float = Field(default=0.9, alias="EVAL_MIN_FAITHFULNESS")
    eval_min_golden_claim_score: float = Field(
        default=0.8, alias="EVAL_MIN_GOLDEN_CLAIM_SCORE"
    )
    eval_min_category_score: float = Field(
        default=0.75, alias="EVAL_MIN_CATEGORY_SCORE"
    )
    eval_failure_sample_size: int = Field(default=8, alias="EVAL_FAILURE_SAMPLE_SIZE")
    eval_min_questions_for_production: int = Field(
        default=164, alias="EVAL_MIN_QUESTIONS_FOR_PRODUCTION"
    )
    eval_fast_gate_size: int = Field(default=25, alias="EVAL_FAST_GATE_SIZE")
    eval_min_refusal_correctness: float = Field(
        default=0.95, alias="EVAL_MIN_REFUSAL_CORRECTNESS"
    )
    eval_min_numeric_compliance: float = Field(
        default=0.95, alias="EVAL_MIN_NUMERIC_COMPLIANCE"
    )
    eval_min_prompt_injection_resistance: float = Field(
        default=0.95, alias="EVAL_MIN_PROMPT_INJECTION_RESISTANCE"
    )
    eval_min_advisor_quality: float = Field(
        default=0.90, alias="EVAL_MIN_ADVISOR_QUALITY"
    )
    claim_min_grounding_score: float = Field(
        default=0.45, alias="CLAIM_MIN_GROUNDING_SCORE"
    )
    answer_generation_mode: str = Field(
        default="grounded_generative", alias="ANSWER_GENERATION_MODE"
    )

    embed_model: str = Field(default="BAAI/bge-small-en-v1.5", alias="EMBED_MODEL")
    chroma_dir: str = Field(default="./backend/chroma_store", alias="CHROMA_DIR")
    embedding_backend: str = Field(
        default="hash", alias="GLASSBOX_EMBEDDING_BACKEND"
    )

    database_url: str = Field(
        default="sqlite:///./backend/glassbox_local.db", alias="DATABASE_URL"
    )
    backend_port: int = Field(default=8000, alias="BACKEND_PORT")
    frontend_api_base: str = Field(
        default="http://localhost:8000", alias="FRONTEND_API_BASE"
    )
    rate_limit_per_min: int = Field(default=10, alias="RATE_LIMIT_PER_MIN")
    determinism_runs: int = Field(default=5, alias="DETERMINISM_RUNS")

    aws_region: str = Field(default="ap-south-1", alias="AWS_REGION")
    s3_corpus_bucket: str = Field(default="glassbox-corpus", alias="S3_CORPUS_BUCKET")

    # --- Auth (Phase B) ---
    jwt_signing_key: str = Field(
        default="dev-insecure-jwt-signing-key-change-me", alias="JWT_SIGNING_KEY"
    )
    jwt_active_kid: str = Field(default="dev1", alias="JWT_ACTIVE_KID")
    access_token_ttl_seconds: int = Field(
        default=15 * 60, alias="ACCESS_TOKEN_TTL_SECONDS"
    )
    refresh_token_ttl_days: int = Field(default=14, alias="REFRESH_TOKEN_TTL_DAYS")
    refresh_cookie_name: str = Field(
        default="glassbox_refresh", alias="REFRESH_COOKIE_NAME"
    )
    refresh_cookie_secure: bool = Field(
        default=False, alias="REFRESH_COOKIE_SECURE"
    )
    frontend_origin: str = Field(
        default="http://localhost:3000", alias="FRONTEND_ORIGIN"
    )
    login_max_failed_attempts: int = Field(
        default=5, alias="LOGIN_MAX_FAILED_ATTEMPTS"
    )
    login_lockout_minutes: int = Field(default=15, alias="LOGIN_LOCKOUT_MINUTES")
    invite_token_ttl_hours: int = Field(default=72, alias="INVITE_TOKEN_TTL_HOURS")
    password_reset_ttl_hours: int = Field(
        default=1, alias="PASSWORD_RESET_TTL_HOURS"
    )
    dev_mail_dir: str = Field(default="/tmp/glassbox-mail", alias="DEV_MAIL_DIR")

    # --- Phase E hardening ---
    app_encryption_key: str = Field(
        default="dev-insecure-encryption-key-change-me-32b!!",
        alias="APP_ENCRYPTION_KEY",
    )
    app_encryption_kid: str = Field(default="dev1", alias="APP_ENCRYPTION_KID")
    cookie_secret: str = Field(
        default="dev-insecure-cookie-secret-change-me", alias="COOKIE_SECRET"
    )
    # Rate-limit tiers (per minute) per (user_id || ip, route_class).
    rate_limit_auth_per_min: int = Field(default=10, alias="RATE_LIMIT_AUTH_PER_MIN")
    rate_limit_ask_per_min: int = Field(default=60, alias="RATE_LIMIT_ASK_PER_MIN")
    rate_limit_default_per_min: int = Field(
        default=120, alias="RATE_LIMIT_DEFAULT_PER_MIN"
    )
    # Body-size caps (bytes) per route class.
    body_max_bytes_ask: int = Field(default=256 * 1024, alias="BODY_MAX_BYTES_ASK")
    body_max_bytes_default: int = Field(
        default=1024 * 1024, alias="BODY_MAX_BYTES_DEFAULT"
    )
    # CSP — minimal but lets the frontend talk to its own origin + API.
    content_security_policy: str = Field(
        default=(
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'"
        ),
        alias="CONTENT_SECURITY_POLICY",
    )
    hsts_max_age_seconds: int = Field(default=63_072_000, alias="HSTS_MAX_AGE_SECONDS")
    structlog_redact_keys: str = Field(
        default="password,new_password,token,refresh_token,access_token,byo_key,api_key,authorization,cookie,mfa_code",
        alias="STRUCTLOG_REDACT_KEYS",
    )

    @property
    def resolved_chroma_dir(self) -> Path:
        path = Path(self.chroma_dir)
        if path.is_absolute():
            return path
        return PROJECT_ROOT / path

    @property
    def resolved_database_url(self) -> str:
        if not self.database_url.startswith("sqlite:///./"):
            return self.database_url
        relative = self.database_url.replace("sqlite:///./", "", 1)
        return f"sqlite:///{PROJECT_ROOT / relative}"

    @property
    def router_providers(self) -> list[str]:
        return [item.strip().lower() for item in self.llm_router_order.split(",") if item.strip()]

    @property
    def approved_model_ids(self) -> set[str]:
        return {item.strip() for item in self.approved_models.split(",") if item.strip()}

    @property
    def candidate_route_ids(self) -> list[str]:
        return [item.strip() for item in self.model_candidate_routes.split(",") if item.strip()]

    @property
    def redact_key_set(self) -> set[str]:
        return {k.strip().lower() for k in self.structlog_redact_keys.split(",") if k.strip()}


# Dev defaults that must never appear in production. Kept in sync by hand with
# the Field(default=...) values above — if you rotate a default, update this
# map too or the production-mode guard will stop catching it.
_DEFAULT_SECRETS: dict[str, str] = {
    "JWT_SIGNING_KEY": "dev-insecure-jwt-signing-key-change-me",
    "APP_ENCRYPTION_KEY": "dev-insecure-encryption-key-change-me-32b!!",
    "COOKIE_SECRET": "dev-insecure-cookie-secret-change-me",
}


class InsecureProductionSecretsError(RuntimeError):
    """Raised at boot when ``GLASSBOX_PRODUCTION_MODE=1`` is set but one or
    more required secrets is still the development default. Booting in that
    state would let an attacker forge JWTs or decrypt BYO keys with values
    that live in the public source tree."""


def assert_secrets_safe_for_mode(settings: "Settings") -> None:
    """Refuse to boot in production with any dev-default secret in place.

    No-op when ``production_mode`` is false. Always inspects every secret so
    the operator sees the full list of offenders in one shot, not one per
    boot attempt.
    """
    if not settings.production_mode:
        return
    current = {
        "JWT_SIGNING_KEY": settings.jwt_signing_key,
        "APP_ENCRYPTION_KEY": settings.app_encryption_key,
        "COOKIE_SECRET": settings.cookie_secret,
    }
    offenders = [name for name, value in current.items() if value == _DEFAULT_SECRETS[name]]
    if not offenders:
        return
    raise InsecureProductionSecretsError(
        "Refusing to start in production mode: the following secrets are still "
        "their development defaults: "
        + ", ".join(offenders)
        + ". Run `python backend/scripts/init_secrets.py >> .env` and restart."
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
