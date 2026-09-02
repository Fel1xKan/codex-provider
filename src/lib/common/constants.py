VERSION = "1.4.1"
PRIVATE_DIR_MODE = 0o700
SECRET_FILE_MODE = 0o600
DEFAULT_FILE_MODE = 0o644
MAX_HTTP_BODY_BYTES = 2 * 1024 * 1024

PROVIDER_PREFIX = "model_providers."
RUNTIME_PROVIDER_ID = "codex-provider"
OFFICIAL_MODEL_PROVIDER_ID = "openai"
MODE_API = "api"
MODE_OFFICIAL = "official"
FAST_MODE_FIELD = "fast_mode"
FAST_MODE_SERVICE_TIER = "priority"
HTTP_HEADERS_FIELD = "http_headers"
PROVIDER_ORDER = [
    "base_url",
    "name",
    "mode",
    "requires_openai_auth",
    "wire_api",
    "supports_websockets",
    FAST_MODE_FIELD,
    HTTP_HEADERS_FIELD,
]
SENSITIVE_KEY_PARTS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
}
