"""Create a Galileo organization via the platform REST API.

The Galileo Python SDK (this build) does not expose organization creation, but
the platform API does: ``POST /organizations`` with body ``{"name": ...}``.
This script reuses the SDK's own authenticated ``ApiClient`` — same ``GALILEO_*``
env config and OS trust store the rest of the app uses — so it authenticates
exactly like the running service.

Usage (from the ai-ops-desk dir, with the venv):
    .venv/bin/python create_org.py "Voltway"

Requires GALILEO_API_KEY (+ GALILEO_CONSOLE_URL / GALILEO_API_URL) in the
environment or .env. The API key's user must have permission to create orgs on
the target stack; otherwise the API returns 401/403.
"""

import sys

from dotenv import load_dotenv

# .env is authoritative over stale shell exports (mirrors app/api.py).
load_dotenv(override=True)

# Trust the OS cert store before any HTTPS client is built (corporate TLS
# interception). Safe no-op elsewhere.
import app.tls_trust  # noqa: F401,E402

from galileo.config import GalileoPythonConfig  # noqa: E402
from galileo_core.constants.request_method import RequestMethod  # noqa: E402


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "Voltway"

    config = GalileoPythonConfig.get()
    client = config.api_client

    print(f"→ Creating organization {name!r} on {config.api_url} ...")
    try:
        org = client.request(RequestMethod.POST, "/organizations", json={"name": name})
    except Exception as e:  # surface the raw API error (e.g. 403 no permission)
        print(f"✗ Failed to create organization: {type(e).__name__}: {e}")
        return 1

    print("✓ Created organization:")
    print(org)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
