"""Delete a Galileo organization via the platform REST API.

Companion to create_org.py — the SDK doesn't wrap org deletion, so this calls
``DELETE /organizations/{id}`` using the SDK's authenticated ApiClient.

Usage (from the ai-ops-desk dir, with the venv):
    .venv/bin/python delete_org.py <organization_id>
"""

import sys

from dotenv import load_dotenv

load_dotenv(override=True)

import app.tls_trust  # noqa: F401,E402

from galileo.config import GalileoPythonConfig  # noqa: E402
from galileo_core.constants.request_method import RequestMethod  # noqa: E402


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: python delete_org.py <organization_id> <confirm_slug>")
        return 2
    org_id = sys.argv[1]
    confirm_slug = sys.argv[2]

    config = GalileoPythonConfig.get()
    client = config.api_client

    print(f"→ Deleting organization {org_id} (slug={confirm_slug}) on {config.api_url} ...")
    try:
        result = client.request(
            RequestMethod.DELETE,
            f"/organizations/{org_id}",
            params={"confirm_slug": confirm_slug},
        )
    except Exception as e:
        print(f"✗ Failed to delete organization: {type(e).__name__}: {e}")
        return 1

    print("✓ Delete request succeeded:")
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
