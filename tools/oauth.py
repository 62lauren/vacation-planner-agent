import json
import os
import tempfile
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TOKEN_PATH = Path("token.json")
CREDENTIALS_PATH = Path("credentials.json")


def load_credentials() -> Credentials | None:
    # Prefer env var (Railway), fall back to file (local dev)
    token_json = os.environ.get("GOOGLE_TOKEN_JSON")
    if token_json:
        creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
    elif TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    else:
        return None

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save(creds)
    return creds if creds and creds.valid else None


def build_auth_flow(redirect_uri: str) -> Flow:
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(creds_json)
            tmp = f.name
        flow = Flow.from_client_secrets_file(tmp, scopes=SCOPES, redirect_uri=redirect_uri)
        os.unlink(tmp)
        return flow
    return Flow.from_client_secrets_file(str(CREDENTIALS_PATH), scopes=SCOPES, redirect_uri=redirect_uri)


def exchange_code(flow: Flow, code: str) -> Credentials:
    flow.fetch_token(code=code)
    creds = flow.credentials
    _save(creds)
    return creds


def _save(creds: Credentials) -> None:
    TOKEN_PATH.write_text(creds.to_json())
