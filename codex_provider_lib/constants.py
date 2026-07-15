VERSION = "0.3.0"
PRIVATE_DIR_MODE = 0o700
SECRET_FILE_MODE = 0o600
MAX_HTTP_BODY_BYTES = 2 * 1024 * 1024

PROVIDER_PREFIX = "model_providers."
PROVIDER_ORDER = [
    "base_url",
    "name",
    "requires_openai_auth",
    "wire_api",
    "supports_websockets",
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
