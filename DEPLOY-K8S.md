# Kubernetes Deployment — Voltway Demo

Runs the Voltway storefront demo (Next.js frontend + FastAPI backend) in
Kubernetes from public container images.

For the older Railway deployment, see [DEPLOY.md](DEPLOY.md). That setup runs
Agent Control in **OSS mode** with its own Postgres; this one uses **enterprise
mode** against the hosted Agent Control service, so there is no database to run
and only two workloads.

---

## Architecture

```
                        voltway.splunko11y.com
                                 │
                           ┌─────▼─────┐
                           │  Ingress  │
                           └──┬─────┬──┘
                      /api/*  │     │  /*
                    ┌─────────▼─┐ ┌─▼──────────┐
                    │voltway-api│ │voltway-web │
                    │  :8000    │ │   :3000    │
                    │ FastAPI   │ │  Next.js   │
                    └─────┬─────┘ └────────────┘
                          │ egress
         ┌────────────────┼──────────────────┐
         ▼                ▼                  ▼
   MongoDB Atlas     api.openai.com    Galileo API +
   ($vectorSearch)                     Agent Control
```

Both tiers sit behind **one hostname**. The browser calls `/api/*` on its own
origin and the Ingress forwards it to the backend, which means:

- no CORS to configure,
- no backend hostname baked into the frontend image (so the image is reusable),
- one place to add password protection (Phase 2).

### External dependencies

| Dependency | Required | Notes |
|---|---|---|
| MongoDB Atlas | Yes | Must be **Atlas**, not self-hosted. The policy RAG path uses `$vectorSearch` (`policy_vectors` index), which only Atlas provides. |
| OpenAI API | Yes | LLM calls and embeddings. |
| Galileo API / Console | Yes | Trace logging, evals. |
| Agent Control | Yes | Enterprise/ACE mode; reuses `GALILEO_API_KEY`. |

The cluster needs **outbound internet** to all four. Only the image *build*
needs GitHub access.

---

## Images

Published by [`.github/workflows/publish-images.yml`](.github/workflows/publish-images.yml)
on every push to `k8s-deployment` (doc-only pushes are skipped), or on demand
from Actions → *Publish container images* → *Run workflow*:

- `ghcr.io/rungalileo/voltway-api`
- `ghcr.io/rungalileo/voltway-web`

Tags: `sha-<full commit hash>` (immutable — use this for anything reproducible),
the branch name, and `latest`.

A GitHub workflow only runs on branches that contain its file, so pushes to
`promo-hallucination-clarity` never build images — that branch deliberately has
neither the workflow nor the Dockerfiles (see
[below](#why-the-dockerfiles-live-only-on-this-branch)).

The manifests use `:latest` with `imagePullPolicy: Always`, but an image is only
pulled when a pod starts. After a build, run
`kubectl -n voltway rollout restart deploy/voltway-api deploy/voltway-web` to
pick it up — or pin a `sha-` tag in `kustomization.yaml` and re-apply.

### Why this org, and the one manual step

The images are published under the same owner as this repo, so the automatic
`GITHUB_TOKEN` is enough — there are no PAT secrets to create or rotate, and the
packages stay linked to their source for provenance.

This satisfies the deployment plan, which calls for images from *any* public
container registry. Most other o11y field demos use `ghcr.io/splunk`, but
publishing there from this repo would require a cross-org Personal Access Token
(`GITHUB_TOKEN` can only write packages owned by its own repo's owner) and would
leave the package detached from its source. Since the o11y-field-demos README
points here for the code anyway, serving images from the same org keeps that
consistent.

> **One-time step after the first CI run:** make both packages public
> (repo → Packages → package → Package settings → Change visibility → Public).
> Otherwise the cluster needs an `imagePullSecret`.

### Building locally instead

```bash
docker build -t voltway-api:local ai-ops-desk
docker build -t voltway-web:local ai-ops-desk-web
```

### Why the Dockerfiles live only on this branch

The public demo is hosted on Railway from `promo-hallucination-clarity`, built by
Railpack, which runs `uvicorn ... --port $PORT` and `next start` against the port
Railway injects. Railway auto-detects a Dockerfile in a service root and silently
switches the builder to it. These Dockerfiles bind **8000** and **3000**, so the
service builds, starts, and then receives no traffic — it looks like an
application fault, not a build-configuration change.

> **Before merging this branch into the Railway one**, pin the builder in the
> Railway UI (service → Settings → Build → Builder) or change both `CMD`s to
> honour `$PORT`. A `railway.json` would be the tidier fix, but the builder
> enum must match what Railway actually uses — guessing it is how you get a
> second outage instead of a fix.

---

## Testing locally first

[`deploy/local-test/`](deploy/local-test/kustomization.yaml) is a kustomize
overlay that runs the whole thing on a local k3d cluster. k3d is the same
technology the field-demo instances use, so this exercises the real Traefik
ingress path rather than an approximation. It overrides only the image names and
`imagePullPolicy` — the Ingress, probes, and ConfigMap are the ones that ship.

```bash
brew install k3d kubectl

k3d cluster create voltway-test --agents 1 \
  --port "8080:80@loadbalancer" --port "8443:443@loadbalancer" \
  --image rancher/k3s:v1.33.4-k3s1

docker build -t voltway-api:local ai-ops-desk
docker build -t voltway-web:local ai-ops-desk-web
k3d image import voltway-api:local voltway-web:local -c voltway-test

kubectl apply -f deploy/k8s/namespace.yaml
kubectl -n voltway create secret generic voltway-secrets \
  --from-literal=MONGODB_URI='...' \
  --from-literal=OPENAI_API_KEY='...' \
  --from-literal=GALILEO_API_KEY='...'

# The overlay keeps the Basic Auth middleware, so its Secret must exist too,
# or every request returns 500.
deploy/scripts/set-password.sh

kubectl apply -k deploy/local-test
kubectl -n voltway rollout status deploy/voltway-api
```

The hostname is not overridden, so send the `Host` header to keep the real
Ingress rule under test:

```bash
curl -H 'Host: voltway.splunko11y.com' http://localhost:8080/api/health
curl -H 'Host: voltway.splunko11y.com' http://localhost:8080/api/users
curl -H 'Host: voltway.splunko11y.com' http://localhost:8080/ | grep -o '<title>.*</title>'
```

Tear down with `k3d cluster delete voltway-test`.

Results from this exact setup: both pods Ready in ~13s; `/api/health`,
`/api/users` (live Atlas), `/api/scenarios` and `/` all 200 through the Ingress;
SSE events arriving progressively; and real Galileo traces written to
`console.demo.sao.splunkcloud.com`.

> On a corporate network that intercepts TLS, every OpenAI call fails and the
> chat returns *"Unable to generate response due to API error"* while everything
> else looks healthy — the agents still run, Mongo still works, traces are still
> written. Apply the CA workaround in
> [Corporate TLS interception](#corporate-tls-interception) first. With it
> applied, the demo returns the correct answer: *"Fall Into Savings Sale on the
> YPhone 16 Pro Max, saving you 20% off (USD 200.00)."*

To browse the local cluster rather than curl it, the overlay adds a `localhost`
rule to the Ingress, so `http://localhost:8080` works. Use
**`https://localhost:8443`** instead if Basic Auth is enabled — a managed Chrome
policy of `BasicAuthOverHttpEnabled: false` is common on corporate laptops, and
it makes Chrome return a bare 401 with no password prompt over plain HTTP, even
in incognito and even with credentials in the URL. Over HTTPS the prompt appears
normally; accept the self-signed certificate warning, which is Traefik's default
cert because cert-manager is not installed on a throwaway cluster. This never
affects the deployed instance, which has a real Let's Encrypt certificate.

---

## Target environment: o11y-field-demos k3d instance

The intended host is an EC2 instance provisioned by the `deploy.sh` script in the
[o11y-field-demos](https://github.com/splunk/o11y-field-demos) repo under
`k3d-ec2-instance/`. Those instances come with a k3d cluster, **Traefik**,
cert-manager with a `letsencrypt-prod` ClusterIssuer, Helm, kubectl, and k9s
already installed.

> No instance has been provisioned yet — this section is the plan, written down so
> the manifests can be read in context. Everything from `## Deploy` onwards has
> been verified on a local k3d cluster running the same k3s version and the same
> ingress controller, including Basic Auth.

**1. Provision.** Run `./deploy.sh` from `k3d-ec2-instance/` and choose:

| Prompt | Value |
|---|---|
| Action | Create new instance |
| Public web URL | **Yes** — needed for `voltway.splunko11y.com` |
| Instance name | `voltway` (becomes the subdomain) |
| Let's Encrypt email | `admin@splunk.com` |
| Instance type | `t3.large` |

Answering Yes to the public URL creates the NLB and Route53 record. The instance
name becomes the hostname, so it must be `voltway` to match the Ingress.

**2. Connect.** Instances are only reachable through the jumpbox. Add the private
IP to `~/.ssh/config` *on the jumpbox*, then:

```bash
ssh o11y-jumpbox
ssh voltway
```

**3. Deploy.** Copy `deploy/k8s/` to `/home/ubuntu` and follow the steps below.
`/home/ubuntu` is bind-mounted into the cluster nodes.

**4. Optional — OpenTelemetry Collector.** Only needed if you want Splunk
Observability APM data for the app itself. The Galileo tracing this demo is built
around is independent of it. Install per
[travel-planner-demo-v2](https://github.com/splunk/o11y-field-demos/blob/main/travel-planner-demo-v2/README.md),
which is the closest analog (also an agentic AI demo).

**5. Register the demo.** The `voltway-demo/` folder for o11y-field-demos is
already written and staged in [`deploy/field-demos/`](deploy/field-demos/README.md)
— a `README.md` and `TROUBLESHOOTING.md` in that repo's house style, plus the row
to add to its root README table, pointing back at this repo as the code location.
Copy the folder across rather than writing it from scratch.

---

## Deploy

### 1. Create the namespace

```bash
kubectl apply -f deploy/k8s/namespace.yaml
```

### 2. Create the Secret

Do this imperatively so credentials never land in git.
[`deploy/k8s/secret.example.yaml`](deploy/k8s/secret.example.yaml) is a
placeholder template for reference only.

```bash
# read -rs keeps the values out of your shell history
read -rsp 'Atlas connection string: ' MONGODB_URI; echo
read -rsp 'OpenAI API key: ' OPENAI_API_KEY; echo
read -rsp 'Galileo API key: ' GALILEO_API_KEY; echo

kubectl -n voltway create secret generic voltway-secrets \
  --from-literal=MONGODB_URI="$MONGODB_URI" \
  --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY" \
  --from-literal=GALILEO_API_KEY="$GALILEO_API_KEY"
```

The Atlas string is the SRV one from **Atlas → Connect → Drivers**.

> **Do not quote values inside YAML manifests.** The repo's `.env` wraps values
> in quotes and `python-dotenv` strips them, but Kubernetes passes ConfigMap and
> Secret values through verbatim. A quoted connection string arrives with the
> quotes attached and fails with `Invalid URI scheme: URI must begin with
> 'mongodb://' or 'mongodb+srv://'`. The `read` approach above avoids this
> entirely — paste the bare value with no quotes around it.

### 3. Review the ConfigMap

Edit [`deploy/k8s/configmap.yaml`](deploy/k8s/configmap.yaml) and confirm:

The demo runs against the **`demo.sao.splunkcloud.com`** stack, and the committed
ConfigMap already uses it, matching `ai-ops-desk/.env`:

```yaml
GALILEO_CONSOLE_URL: https://console.demo.sao.splunkcloud.com
GALILEO_API_URL: https://api.demo.sao.splunkcloud.com
```

**Leave these alone.** The two URLs and `GALILEO_API_KEY` must all belong to the
same stack, and a mismatch fails hard rather than quietly: the Galileo client is
initialised on the request path, so every chat returns
`Galileo API returned HTTP status code 401 ... Invalid credentials.` with no
agents running at all. This was hit in testing by pointing the URLs at a
different stack while keeping the existing key. It is not degraded tracing — it
takes the whole demo down. Any stack change requires a new API key issued for
that stack.

`AGENT_CONTROL_URL` points at a **different** host than `GALILEO_API_URL`
(`agent-control.demo-v2.galileocloud.io`). That is intentional and matches the
working config; don't "correct" it to match. If traces log fine but the Ops
drawer shows no controls, this is the value to check.

Two keys are in the ConfigMap but not in `.env`, because they only matter in a
cluster: `ALLOWED_ORIGINS` (set to your public hostname) and
`PROMO_DEMO_STATE_FILE` (must point inside the writable `/data` mount).
`MONGODB_DATABASE` from `.env` is deliberately **omitted** — no code reads it;
`atlas_client.py` hardcodes `client.ai_ops_desk`.

### 4. Set the Basic Auth password

The demo is served on a public hostname, so the Ingress requires HTTP Basic Auth.
Create the credentials before applying, or Traefik will return 500 for every
request (the middleware references a Secret that must exist):

```bash
deploy/scripts/set-password.sh              # user "voltway", prompts for password
deploy/scripts/set-password.sh alice        # pick a different username
```

The script generates a **bcrypt** hash and creates or updates the
`voltway-basicauth` Secret. Re-run it any time to rotate the password; no pod
restart is needed, because the credentials are read by Traefik rather than by the
app.

> The upstream healthcare-assistant example falls back to
> `openssl passwd -apr1` when `htpasswd` is missing. That is APR1/MD5, a broken
> hash, and this script deliberately refuses to use it — it fails with install
> instructions instead. Basic auth is the only thing in front of a public URL, so
> the hash should not be the weak link. macOS already ships `htpasswd`; on
> Debian/Ubuntu it's `apache2-utils`, on RHEL/Fedora `httpd-tools`.

### 5. Apply everything else

```bash
kubectl apply -k deploy/k8s
```

Use `-k`, not `-f deploy/k8s/`: plain `-f` on a directory applies files
alphabetically and would try to create Deployments before the Namespace exists.
Kustomize orders by kind.

### 6. Verify

```bash
kubectl -n voltway rollout status deploy/voltway-api
kubectl -n voltway rollout status deploy/voltway-web

# Backend health. port-forward goes straight to the Service, so these bypass the
# Ingress and need no password -- handy for isolating app problems from ingress
# or auth problems.
kubectl -n voltway port-forward svc/voltway-api 8000:8000 &
curl -s localhost:8000/api/health          # -> {"ok":true}
curl -s localhost:8000/api/users           # -> user list; proves Atlas works
curl -s localhost:8000/api/ops/live_target # -> active Galileo project

# Through the Ingress, which does enforce auth
curl -s -o /dev/null -w '%{http_code}\n' https://voltway.splunko11y.com/api/health
# -> 401
curl -s -u voltway:<password> https://voltway.splunko11y.com/api/health
# -> {"ok":true}

# TLS cert — must reach READY=True before the public URL works
kubectl -n voltway get certificate
```

Then open `https://voltway.splunko11y.com`, enter the credentials at the browser
prompt, and run the YPhone discount question. If the reply streams in
agent-by-agent, SSE is passing through the Ingress correctly.

The field-demo instances have `k9s` installed, which is usually the fastest way
to watch pods and read logs while debugging.

---

## Ingress and TLS

[`deploy/k8s/ingress.yaml`](deploy/k8s/ingress.yaml) targets **Traefik**, which
is what the o11y-field-demos k3d instances ship, and requests a TLS certificate
through the pre-installed cert-manager issuer:

```yaml
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  ingressClassName: traefik
  tls:
    - hosts: [voltway.splunko11y.com]
      secretName: voltway-tls
```

The `letsencrypt-prod` ClusterIssuer is created by cloud-init on the instance's
**first boot only**. If the k3d cluster was ever deleted and recreated,
cert-manager and the issuer are gone and must be reinstalled before this Ingress
will get a cert — otherwise the certificate sits in `Pending` forever. The
reinstall steps are in `k3d-ec2-instance/README.md` in the o11y-field-demos repo.

Check cert issuance with:

```bash
kubectl -n voltway get certificate
kubectl -n voltway describe certificate voltway-tls
```

### Server-Sent Events

`POST /api/chat/stream` emits one SSE event per agent completion. If a proxy
buffers the response, the chat appears to hang and then dumps everything at once,
losing the agent-by-agent reveal the demo depends on.

**No configuration is needed for this**, which was confirmed by measurement
rather than assumed:

| Path under test | Result |
|---|---|
| Traefik Ingress (what ships) | 7 events spread over ~9s — streaming |
| nginx `proxy_buffering on` | streaming |
| nginx `proxy_buffering on` + app hint ignored | streaming |

Two independent reasons it works: Traefik streams by default (buffering is an
opt-in middleware), and the app already sets `X-Accel-Buffering: no` on the
response in `app/api.py`, which is the standard proxy opt-out and is honoured by
nginx.

The practical rule is just: **don't attach a `buffering` Middleware** to this
router. The ingress-nginx annotations are noted in a comment in `ingress.yaml`
as defensive extras; they are not in the manifest because Traefik silently
ignores `nginx.*` annotations, which would imply SSE was handled when it wasn't.

To re-verify after any ingress change, check that events arrive progressively
rather than all at once:

```bash
curl -N -X POST http://localhost:8080/api/chat/stream \
  -H 'Host: voltway.splunko11y.com' -H 'Content-Type: application/json' \
  -d '{"user_query":"Can I get a discount on the YPhone?","user_id":"user_001"}'
```

---

## Password protection

Basic Auth is enforced by a Traefik `Middleware`
([`deploy/k8s/basicauth-middleware.yaml`](deploy/k8s/basicauth-middleware.yaml))
that the Ingress opts into with one annotation:

```yaml
traefik.ingress.kubernetes.io/router.middlewares: voltway-basicauth@kubernetescrd
```

The value format is `<namespace>-<middleware-name>@kubernetescrd`, so the
`voltway-` prefix is the **namespace**, not part of the name. Get this wrong and
Traefik returns 404 for the whole site instead of an auth prompt — a confusing
failure worth recognising.

Four things that follow from auth living at the ingress rather than in the app:

**It covers everything, including `/api`.** Verified: every path returns 401
without credentials and 200 with them. The browser caches the credentials for the
origin after the prompt, so the frontend's `fetch` calls to `/api/*` are
authenticated automatically — no app change was needed.

**SSE still streams.** The middleware authenticates and then gets out of the way;
the chat's events still arrive progressively rather than buffered.

**Health probes are unaffected.** The kubelet talks to the Pod directly, not
through the Ingress, so probes never see basic auth and need no exemption. If
auth were implemented inside the app, `/api/health` would have needed one.

**`port-forward` bypasses it** (see Verify above), which is the quickest way to
tell an app failure apart from an auth or ingress failure.

Rotate with `deploy/scripts/set-password.sh`; Traefik picks up the Secret change
without a restart. The `voltway-basicauth` Secret is intentionally not in
`kustomization.yaml`, so credentials never land in git.

Basic auth transmits the password on every request, which is acceptable here only
because the Ingress terminates TLS. Don't expose this over plain HTTP — and note
that managed browsers often refuse to send Basic credentials over HTTP at all,
which looks like a broken deployment rather than a policy decision (see
[Testing locally first](#testing-locally-first)).

## Operational notes

### The backend must stay at 1 replica

`deploy/k8s/api-deployment.yaml` sets `replicas: 1` and `strategy: Recreate`.
This is a correctness constraint, not a resource decision:

- The Ops drawer's "live target" repointing mutates `os.environ` **inside the
  running process**.
- The integration-cost job keeps progress in **module-level state** plus a
  background thread.

With two replicas, a button press and its follow-up status poll can hit
different pods — the UI reports the wrong progress and traces go to the
wrong project. `Recreate` prevents two pods from briefly overlapping during a
rollout. `voltway-web` is stateless and can be scaled freely.

### Configuration precedence

The backend calls `load_dotenv(override=True)` at import. Both `.dockerignore`
files exclude `.env` precisely because a baked-in `.env` would **silently
override every ConfigMap and Secret value**. If config seems to be ignored,
confirm no `.env` made it into the image.

### The live-target state file

`PROMO_DEMO_STATE_FILE=/data/.galileo_active_target.json` on an `emptyDir`.
Losing it on pod restart is harmless — the app reverts to `GALILEO_PROJECT` from
the ConfigMap, and it self-heals if the pinned project was deleted. Switch
`/data` to a PVC only if the pin must survive pod replacement.

### Atlas IP allowlist

A new cluster has a different egress IP. Add it under Atlas → Network Access, or
`/api/health` will stay green while every data call fails.

### Corporate TLS interception

If the cluster's egress is behind a TLS-inspecting proxy (Zscaler, Cisco Secure
Access, etc.), outbound HTTPS fails with:

```
[SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate
```

The app already calls `truststore.inject_into_ssl()` ([`app/tls_trust.py`](ai-ops-desk/app/tls_trust.py)),
which trusts the OS store — but a container's OS store has only public CAs.

The symptom is confusing because it is **not** a total outage: `/api/health` and
`/api/users` stay green (Atlas uses a public CA), the agent graph runs, and
Galileo traces are written. Only the OpenAI calls fail, so the chat replies
*"Unable to generate response due to API error."* Confirm it from inside the pod:

```bash
kubectl -n voltway exec deploy/voltway-api -- python -c \
  "import socket,ssl; ssl.create_default_context().wrap_socket(
   socket.create_connection(('api.openai.com',443)), server_hostname='api.openai.com')"
# CERTIFICATE_VERIFY_FAILED => interception; a clean exit => not this problem
```

The fix is to give the container a bundle containing **both** the public roots
and the interception CA, then point Python at it. A bundle with only the
corporate CA will break everything else.

```bash
# public roots + the corporate CA in one file
python -c "import certifi,shutil;shutil.copy(certifi.where(),'/tmp/ca.pem')"
security find-certificate -a -c "<YourCorporateCA>" -p \
  /System/Library/Keychains/SystemRootCertificates.keychain >> /tmp/ca.pem

kubectl -n voltway create configmap corporate-ca --from-file=ca.pem=/tmp/ca.pem
```

Then patch the Deployment (this exact patch was applied and verified on k3d —
afterwards the demo returned the correct promo answer):

```yaml
          env:
            - name: SSL_CERT_FILE
              value: /certs/ca.pem
            - name: REQUESTS_CA_BUNDLE
              value: /certs/ca.pem
          volumeMounts:
            - name: corporate-ca
              mountPath: /certs
              readOnly: true
      volumes:
        - name: corporate-ca
          configMap:
            name: corporate-ca
```

Plain AWS egress needs none of this.

### Dependency lockfile

The image installs from [`ai-ops-desk/requirements.lock`](ai-ops-desk/requirements.lock)
with `--no-deps`, which is **required, not an optimisation**:
`agent-control-evaluators` (pulled in by `agent-control-sdk` and
`agent-control-engine`) requires `sqlglot[c]<29.1.0`, and every 29.x release of
the `sqlglotc` accelerator has been removed from PyPI. Any normal resolution of
`requirements.txt` now fails with:

```
ERROR: No matching distribution found for sqlglotc<29.1.0,>=29.0.0
```

The lockfile pins the last known-good closure and omits `sqlglotc`, which is
only an optional tokenizer speed-up (sqlglot has a pure-Python fallback).
`requirements.txt` is kept as the readable statement of intent. To regenerate
from a working virtualenv:

```bash
pip freeze | grep -v '^sqlglotc==' > requirements.lock   # then restore the header
```

`promo-hallucination-clarity` fixes the same problem the other way, by bumping
only `agent-control-evaluators` and `-evaluator-galileo` to the upstream commit
that drops the `sqlglotc` pin (Railpack has no lockfile step to hook). Either
approach works; this branch keeps the lockfile because the image should install a
closure that was actually tested, not whatever resolves on build day.

---

## Seeding data

The demo normally points at an already-seeded Atlas database, so no seed step is
needed. For a fresh database, run these once from `ai-ops-desk/` with
`MONGODB_URI` and `OPENAI_API_KEY` set:

```bash
python setup_products.py && python setup_promos.py       # storefront + promos
python setup_policies.py                                  # policy RAG (needs embeddings)
python setup_orders.py && python setup_refund_requests.py && python setup_tickets.py
```

`setup_policies.py` writes embeddings; the `policy_vectors` Atlas Search index
must exist for the refund path to retrieve anything.

---

## Source

Code lives in the Galileo repo
[`rungalileo/mongodb_local_nyc_demo`](https://github.com/rungalileo/mongodb_local_nyc_demo)
on branch `k8s-deployment`: the app from `promo-hallucination-clarity` (the
Railway demo) plus everything in this document. App fixes are made there first
and cherry-picked here; never merge the two branches. Demo walkthrough:
[`ai-ops-desk/EXPIRED_PROMO_DEMO.md`](ai-ops-desk/EXPIRED_PROMO_DEMO.md).
