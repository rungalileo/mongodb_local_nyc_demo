# Voltway — AI Ops Desk (Kubernetes branch)

A customer-support agent for Voltway, a fictional online retailer, built to show
Splunk Agent Observability and Agent Control working against a real LangGraph
agent and a real MongoDB Atlas database.

**The demo is the expired promo.** The agent reads a stale promo cache, proposes
a discount that has already expired, and an LLM-as-judge eval catches it.
Walkthrough: [`ai-ops-desk/EXPIRED_PROMO_DEMO.md`](ai-ops-desk/EXPIRED_PROMO_DEMO.md).

**Integration costs is setup, not a demo.** It backfills evaluator traffic so
that the Console's cost view shows, across several weeks of history, what
LLM-as-judge evaluators cost compared with Luna-based judges — the kind of
long-run comparison you can point at but could never produce live. Run it ahead
of time and the graph is simply there when you need it:
[`ai-ops-desk/integration-cost-demo/README.md`](ai-ops-desk/integration-cost-demo/README.md).

> A naming note: the environment variables, the Python SDK and the on-disk state
> file are all still named `GALILEO_*` / `galileo`. That is the underlying SDK,
> not a separate product — leave those identifiers exactly as they are.

---

## What this branch is

The same application as `promo-hallucination-clarity` (the Railway-hosted demo),
plus everything needed to run it as containers on Kubernetes:

| Added here | Where |
|---|---|
| Dockerfiles for both tiers | `ai-ops-desk/Dockerfile`, `ai-ops-desk-web/Dockerfile` |
| Manifests (namespace, ConfigMap, Deployments, Services, Ingress) | `deploy/k8s/` |
| Password protection (Traefik Basic Auth) | `deploy/k8s/basicauth-middleware.yaml`, `deploy/scripts/set-password.sh` |
| A local k3d overlay to test the real ingress path | `deploy/local-test/` |
| CI that publishes the images to GHCR | `.github/workflows/publish-images.yml` |
| The o11y-field-demos runbook, ready to copy | `deploy/field-demos/` |

This README gets you oriented and running. The full reference, including every
failure mode found while testing, is [`DEPLOY-K8S.md`](DEPLOY-K8S.md).

> **Never merge this branch into `promo-hallucination-clarity`.** Railway
> auto-detects the Dockerfiles, silently switches builders, and the live demo
> starts but receives no traffic. Bring app fixes across with `git cherry-pick`
> instead. Details:
> [Why the Dockerfiles live only on this branch](DEPLOY-K8S.md#why-the-dockerfiles-live-only-on-this-branch).

---

## What you need before you start

| | Why |
|---|---|
| A **MongoDB Atlas** cluster | Must be Atlas, not self-hosted — the refund-policy path uses `$vectorSearch`, which only Atlas provides |
| An OpenAI API key | Runs the agent itself |
| A **Splunk Agent Observability API key for the stack you point at** | Keys are per-stack. A key from a different instance returns `401 Invalid credentials` and takes the whole chat down |
| `kubectl`, and `docker` + `k3d` for a local cluster | `brew install kubectl k3d` |
| `htpasswd` | Hashes the Basic Auth password. macOS ships it; Debian/Ubuntu `apache2-utils`, RHEL/Fedora `httpd-tools` |

This repo is configured against the Splunk Agent Observability demo stack
(`demo.sao.splunkcloud.com`). Issue your key from that Console, not another one.

The default branch is `main`, so check this one out explicitly:

```bash
git clone git@github.com:rungalileo/mongodb_local_nyc_demo.git
cd mongodb_local_nyc_demo
git checkout k8s-deployment
```

---

## Three ways to run it

### A. On a local Kubernetes cluster (recommended first step)

Runs the exact manifests that ship, on k3d — the same technology as the
field-demo instances, with the same Traefik ingress. Condensed from
[Testing locally first](DEPLOY-K8S.md#testing-locally-first):

```bash
k3d cluster create voltway-test --agents 1 \
  --port "8080:80@loadbalancer" --port "8443:443@loadbalancer" \
  --image rancher/k3s:v1.33.4-k3s1

docker build -t voltway-api:local ai-ops-desk
docker build -t voltway-web:local ai-ops-desk-web
k3d image import voltway-api:local voltway-web:local -c voltway-test

kubectl apply -f deploy/k8s/namespace.yaml

# read -rs keeps your keys out of shell history and out of every file
read -rsp 'Atlas connection string: ' MONGODB_URI; echo
read -rsp 'OpenAI API key: ' OPENAI_API_KEY; echo
read -rsp 'Splunk Agent Observability API key: ' GALILEO_API_KEY; echo
kubectl -n voltway create secret generic voltway-secrets \
  --from-literal=MONGODB_URI="$MONGODB_URI" \
  --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY" \
  --from-literal=GALILEO_API_KEY="$GALILEO_API_KEY"

deploy/scripts/set-password.sh             # Basic Auth; prompts for a password
kubectl apply -k deploy/local-test
kubectl -n voltway rollout status deploy/voltway-api
```

Open **<https://localhost:8443>** and accept the self-signed certificate warning.
Use HTTPS, not `http://localhost:8080`: many managed laptops forbid Basic Auth
over plain HTTP, so Chrome shows a bare 401 with no password prompt.

Tear down with `k3d cluster delete voltway-test`.

### B. On the field-demo instance

The target is an o11y-field-demos k3d EC2 instance serving
`voltway.splunko11y.com`. The order matters — each step depends on the one
before:

1. Create the namespace and the `voltway-secrets` Secret, exactly as above.
2. Leave [`deploy/k8s/configmap.yaml`](deploy/k8s/configmap.yaml) as it is
   unless you are changing project (see below) or stack.
3. `deploy/scripts/set-password.sh` — without this Secret, Traefik returns 500
   for every request.
4. `kubectl apply -k deploy/k8s` — use `-k`, not `-f`, so the namespace is
   created before anything that needs it. For a demo you need to rely on, pin
   the image tag first (see [Images](#images)).

Provisioning the instance, TLS, and verification are covered step by step in
[Target environment](DEPLOY-K8S.md#target-environment-o11y-field-demos-k3d-instance)
and [Deploy](DEPLOY-K8S.md#deploy).

### C. Without containers, for app development

Two processes: a FastAPI backend on **8000** and a Next.js frontend on **3000**.
You need Python 3.12 and Node 20+.

```bash
# Backend — install from the lockfile, the same way the image does
cd ai-ops-desk
python3.12 -m venv .venv
.venv/bin/pip install --no-deps -r requirements.lock

# Frontend
cd ../ai-ops-desk-web
npm install
```

On this branch, `pip install -r requirements.txt` fails with
`No matching distribution found for sqlglotc<29.1.0,>=29.0.0`: a package that
file depends on has been deleted from PyPI. The lockfile sidesteps it; see
[Dependency lockfile](DEPLOY-K8S.md#dependency-lockfile).

Configure the backend with `cp env.example .env` and fill in your own
`MONGODB_URI`, `OPENAI_API_KEY` and `GALILEO_API_KEY`. `.env` is gitignored —
never commit it, and never paste a key into a tracked file. For every other
value, copy what's in [`deploy/k8s/configmap.yaml`](deploy/k8s/configmap.yaml):
`env.example` on this branch still has placeholder `gcp-dev` stack URLs, and
those won't work with a demo-stack key.

```bash
cd ai-ops-desk && .venv/bin/uvicorn app.api:app --reload --port 8000   # terminal 1
cd ai-ops-desk-web && npm run dev                                       # terminal 2
```

Open <http://localhost:3000>. `curl localhost:8000/api/health` should return
`{"ok":true}`.

---

## Credentials

All three secrets — the Atlas connection string, the OpenAI key and the Splunk
Agent Observability key — live only in the `voltway-secrets` Kubernetes Secret
(or your local `.env`). Nothing in git holds a real value:
[`deploy/k8s/secret.example.yaml`](deploy/k8s/secret.example.yaml) is a
placeholder template, and both it and the Basic Auth Secret are deliberately
left out of `kustomization.yaml`.

Two rules that cause most first-deploy failures:

- **No quotes around values in Kubernetes.** `.env` quotes values and
  python-dotenv strips them; Kubernetes passes them through verbatim. A quoted
  Atlas string fails with `Invalid URI scheme`. The `read -rsp` approach above
  avoids this — paste the bare value.
- **Never bake `.env` into an image.** The backend loads it with
  `override=True`, so a stray `.env` silently overrides every ConfigMap and
  Secret value. Both `.dockerignore` files exclude it; keep it that way.

---

## Choosing your project and log stream

Traces go to the project and log stream named by `GALILEO_PROJECT` and
`GALILEO_LOG_STREAM`, which on Kubernetes come from the ConfigMap
(`volt-assistant` / `Default` as committed).

### First run: create it from the UI

You don't have to create anything in the Console by hand. Open the **Ops
drawer** in the app and use **Generate demo traffic**: type a **Project name**
(e.g. `my-voltway`), leave **Log stream name** as `Default`, and run it. That
creates the project and log stream, enables the demo evals, attaches the
`promo-proposal-steer` control (disabled), injects a few weeks of promo
conversations, and repoints live chat at the new project.

**Point live traces here** in the Live target section does **not** create
anything — it switches between projects that already exist.

### Making it the default

A UI repoint is a *pin*, written to `/data/.galileo_active_target.json`. While
it exists it overrides the ConfigMap. On Kubernetes, `/data` is an `emptyDir`,
so the pin lasts only as long as the pod: it survives a container restart but
not a pod replacement, and after that the app is back on the ConfigMap value.

So to make a project stick, put it in the ConfigMap and replace the pod:

```bash
# edit GALILEO_PROJECT / GALILEO_LOG_STREAM in deploy/k8s/configmap.yaml, then
kubectl apply -k deploy/k8s
kubectl -n voltway rollout restart deploy/voltway-api
```

The restart is required — environment variables from a ConfigMap are read only
when a pod starts. It also clears the old pin, because the replacement pod gets
a fresh `/data`, so there's no separate cleanup step.

Running locally without containers (option C) it works the same way, except the
pin is the file `ai-ops-desk/.galileo_active_target.json` and survives
restarts: set the default in `.env`, delete that file (or click **Revert to
default**), and restart the backend.

If the pinned project is deleted in the Console, the app clears the pin on the
next startup and falls back to the default rather than logging into a dead
target.

### Confirming it took

**Run test (write · verify · cleanup)** in the Live target section writes a
marker trace, confirms it landed where you expect, probes Agent Control, and
deletes the marker. Use it after any repoint.

---

## Images

`ghcr.io/rungalileo/voltway-api` and `ghcr.io/rungalileo/voltway-web`, built by
[`.github/workflows/publish-images.yml`](.github/workflows/publish-images.yml).

Every push to `k8s-deployment` builds both images, unless the push changes only
Markdown. To rebuild without a push: GitHub → Actions → *Publish container
images* → *Run workflow* → branch `k8s-deployment`. Pushes to
`promo-hallucination-clarity` never build images — that branch has no
Dockerfiles.

Each build publishes three tags: `sha-<full commit hash>`, `k8s-deployment`, and
`latest`. The manifests use `latest`, which is fine while setting up. A running
pod keeps the image it started with, so pick up a new build with:

```bash
kubectl -n voltway rollout restart deploy/voltway-api deploy/voltway-web
```

For anything you need to reproduce — a live demo, an event — pin the exact
build in [`deploy/k8s/kustomization.yaml`](deploy/k8s/kustomization.yaml)
instead, because a `sha-` tag can never change underneath you:

```yaml
images:
  - name: ghcr.io/rungalileo/voltway-api
    newTag: sha-<full commit hash>
  - name: ghcr.io/rungalileo/voltway-web
    newTag: sha-<full commit hash>
```

After the very first build, make both packages public once (repo → Packages →
package → Package settings → Change visibility → Public), or the cluster needs
an `imagePullSecret`.

---

## Two constraints worth knowing

**The backend must stay at one replica.** The Ops drawer's live-target pin and
the integration-cost job both live inside the running process, and chat sessions
are tracked there too. With two replicas, a button press and its status poll can
hit different pods. `api-deployment.yaml` pins `replicas: 1` and
`strategy: Recreate` for this reason; the frontend can scale freely. See
[The backend must stay at 1 replica](DEPLOY-K8S.md#the-backend-must-stay-at-1-replica).

**Streaming must not be buffered.** The chat reveals each agent's answer as it
finishes, over Server-Sent Events. Traefik streams by default — just don't attach
a buffering middleware to this route. See
[Server-Sent Events](DEPLOY-K8S.md#server-sent-events).

---

## When something doesn't work

| Symptom | Cause |
|---|---|
| Every chat fails with `401 ... Invalid credentials` | API key issued for a different stack than `GALILEO_API_URL` in the ConfigMap |
| `Invalid URI scheme` | Quotes around the Atlas string in the Secret |
| Every page returns **500** | The Basic Auth Secret is missing — run `deploy/scripts/set-password.sh` |
| The whole site returns **404** | The middleware annotation on the Ingress is wrong; see [Password protection](DEPLOY-K8S.md#password-protection) |
| Bare 401, no password prompt | Browser refuses Basic Auth over HTTP — use HTTPS |
| `/api/health` is fine but the user list is empty | The cluster's egress IP isn't allowlisted in Atlas |
| `Unable to generate response due to API error` | Corporate TLS interception; see [Corporate TLS interception](DEPLOY-K8S.md#corporate-tls-interception) |
| Public URL won't load, certificate stuck `Pending` | cert-manager or its issuer is missing; see [Ingress and TLS](DEPLOY-K8S.md#ingress-and-tls) |
| ConfigMap changes seem ignored | Pod not restarted, or a `.env` got baked into the image |
| Traces land in the wrong project | A UI pin is overriding the ConfigMap — see above |
| Deployed app is missing a recent fix | The pod predates the build — `rollout restart`, or pin a `sha-` tag (see [Images](#images)) |

`port-forward` goes straight to the Service and skips both the Ingress and Basic
Auth, which is the fastest way to tell an app problem from an ingress or auth
problem:

```bash
kubectl -n voltway port-forward svc/voltway-api 8000:8000
curl localhost:8000/api/health
```

Agent internals, failure toggles and the CLI scenario runner are covered in
[`ai-ops-desk/README.md`](ai-ops-desk/README.md).

---

## Repo layout

```
ai-ops-desk/            FastAPI backend, LangGraph agent, seed scripts, Dockerfile
  app/                  API, agent, observability + Agent Control wiring
  integration-cost-demo/ Cost-view setup and its trace injector
  requirements.lock     What the image actually installs (see DEPLOY-K8S.md)
ai-ops-desk-web/        Next.js frontend (chat UI + Ops drawer), Dockerfile
deploy/
  k8s/                  Manifests — apply with `kubectl apply -k deploy/k8s`
  local-test/           k3d overlay: local images, same Ingress
  scripts/              set-password.sh (Basic Auth)
  field-demos/          voltway-demo runbook, staged for o11y-field-demos
.github/workflows/      Image publishing to GHCR
DEPLOY-K8S.md           Full Kubernetes reference
DEPLOY.md               The older Railway deployment, for comparison
```
