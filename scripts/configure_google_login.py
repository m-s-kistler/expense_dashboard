"""Import a downloaded Google OAuth web client without printing credentials."""

import argparse
import json
from pathlib import Path
import secrets
from urllib.parse import urlparse


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("client_json", type=Path)
    parser.add_argument("--public-url", required=True, help="Your HTTPS Tailscale Funnel URL")
    parser.add_argument("--email", default="mskistler@gmail.com")
    args = parser.parse_args()
    url = urlparse(args.public_url)
    if (url.scheme != "https" or not url.hostname or not url.hostname.endswith(".ts.net")
            or url.username or url.password or url.port or url.path not in ("", "/") or url.query or url.fragment):
        parser.error("Use the root HTTPS URL supplied by Tailscale, such as https://pc.example.ts.net")
    redirect_uri = f"https://{url.hostname}/oauth2callback"
    client = json.loads(args.client_json.read_text(encoding="utf-8-sig")).get("web", {})
    if not client.get("client_id") or not client.get("client_secret"):
        parser.error("The JSON must contain a Google OAuth Web application client.")
    if redirect_uri not in client.get("redirect_uris", []):
        parser.error(f"Add {redirect_uri} to the client's authorized redirect URIs, then download its JSON again.")
    target = Path(__file__).resolve().parents[1] / ".streamlit" / "secrets.toml"
    if target.exists():
        parser.error("secrets.toml already exists. Update the existing file instead of overwriting other secrets.")
    target.parent.mkdir(exist_ok=True)
    values = {
        "redirect_uri": redirect_uri,
        "cookie_secret": secrets.token_urlsafe(48),
        "client_id": client["client_id"],
        "client_secret": client["client_secret"],
        "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
    }
    content = "[auth]\n" + "\n".join(f"{key} = {json.dumps(value)}" for key, value in values.items())
    content += f"\n\n[access]\nallowed_email = {json.dumps(args.email.strip())}\n"
    with target.open("x", encoding="utf-8") as file:
        file.write(content)
    print(f"Saved local login configuration to {target}. Credentials were not printed.")
    print("Restart the app before enabling Funnel.")


if __name__ == "__main__":
    main()
