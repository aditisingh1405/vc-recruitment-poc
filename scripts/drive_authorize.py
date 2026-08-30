"""One-time Drive authorisation for uploads.

Service accounts cannot own Drive files -- they have no storage quota -- so
uploads run as a real Google account instead. This opens the normal consent
screen once and saves a refresh token the server can reuse.

    python scripts/drive_authorize.py

Before running, create an OAuth client in the same Google Cloud project:
  APIs & Services -> Credentials -> Create credentials -> OAuth client ID
  -> Application type: Desktop app -> download the JSON.
Then set DRIVE_OAUTH_CLIENT_FILE in .env to that file, or pass it as the
first argument.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402

from app.config import BASE_DIR, settings  # noqa: E402

SCOPES = ["https://www.googleapis.com/auth/drive"]


def main() -> int:
    client_file = (
        sys.argv[1] if len(sys.argv) > 1 else settings.drive_oauth_client_file
    )
    if not client_file:
        print(
            "No OAuth client file. Create a Desktop-app OAuth client in the "
            "Google Cloud console, download the JSON, then either set "
            "DRIVE_OAUTH_CLIENT_FILE in .env or pass the path as an argument."
        )
        return 1
    if not Path(client_file).is_file():
        print(f"OAuth client file not found: {client_file}")
        return 1

    token_path = Path(
        settings.drive_oauth_token_file
        or BASE_DIR / "credentials" / "drive_token.json"
    )
    token_path.parent.mkdir(parents=True, exist_ok=True)

    flow = InstalledAppFlow.from_client_secrets_file(client_file, SCOPES)
    creds = flow.run_local_server(port=0)
    token_path.write_text(creds.to_json())

    print(f"\nSaved to {token_path}")
    print("Add this to .env, then restart the server:\n")
    print(f"DRIVE_OAUTH_TOKEN_FILE={token_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
