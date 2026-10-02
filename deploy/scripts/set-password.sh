#!/usr/bin/env bash
#
# Set or rotate the Basic Auth credentials guarding the Voltway demo.
#
#   deploy/scripts/set-password.sh                 # user "voltway", prompts
#   deploy/scripts/set-password.sh alice           # prompts for password
#
# Safe to re-run: it updates the Secret in place. Traefik re-reads the Secret,
# so no pod restart is needed -- the credentials are read by the ingress
# controller, not by the app.
set -euo pipefail

NAMESPACE="${NAMESPACE:-voltway}"
SECRET_NAME="voltway-basicauth"
USERNAME="${1:-voltway}"
PASSWORD="${2:-}"

if [[ -z "$PASSWORD" ]]; then
  # -s keeps it off the screen; passing the password as $2 would also leave it
  # in your shell history, so prefer the prompt.
  read -r -s -p "Password for user '$USERNAME': " PASSWORD
  echo
  read -r -s -p "Confirm: " CONFIRM
  echo
  [[ "$PASSWORD" == "$CONFIRM" ]] || { echo "Passwords do not match." >&2; exit 1; }
fi

[[ -n "$PASSWORD" ]] || { echo "Password must not be empty." >&2; exit 1; }

# bcrypt only. The upstream example falls back to `openssl passwd -apr1`, which
# is APR1/MD5 -- a broken hash that should not be protecting a public URL. If
# htpasswd is unavailable we stop rather than silently downgrade.
if ! command -v htpasswd >/dev/null 2>&1; then
  cat >&2 <<'EOF'
error: `htpasswd` not found, and it is required for a bcrypt hash.

  macOS         already ships it at /usr/sbin/htpasswd
  Debian/Ubuntu sudo apt-get install apache2-utils
  RHEL/Fedora   sudo dnf install httpd-tools
EOF
  exit 1
fi

# -n print to stdout, -b password on the command line, -B bcrypt.
HTPASSWD="$(htpasswd -nbB "$USERNAME" "$PASSWORD")"

case "$HTPASSWD" in
  *:\$2y\$*|*:\$2a\$*|*:\$2b\$*) ;;
  *) echo "error: expected a bcrypt hash; refusing to continue." >&2; exit 1 ;;
esac

# --dry-run | apply so this both creates and updates. Plain `create` fails if
# the Secret already exists.
kubectl -n "$NAMESPACE" create secret generic "$SECRET_NAME" \
  --from-literal=users="$HTPASSWD" \
  --dry-run=client -o yaml | kubectl apply -f -

echo
echo "Basic Auth credentials updated in namespace '$NAMESPACE'."
echo "  username: $USERNAME"
echo "  hash:     bcrypt"
echo
echo "The Ingress must reference the middleware for this to take effect:"
echo "  traefik.ingress.kubernetes.io/router.middlewares: ${NAMESPACE}-basicauth@kubernetescrd"
