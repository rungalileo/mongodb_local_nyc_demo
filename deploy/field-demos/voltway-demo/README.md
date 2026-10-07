# Voltway Agent Observability Demo

The steps below can be used to deploy the Voltway demo application. It is an
agentic e-scooter support desk — a Next.js frontend and a FastAPI backend running
a multi-agent workflow over MongoDB Atlas — instrumented with Splunk Agent
Observability (Galileo).

The demo shows an agent confidently telling a customer about a discount that
expired, then the same question answered correctly once the promo data is fixed,
with the hallucination and the fix both visible in the traces.

We'll deploy the application on a k3d cluster running on a single EC2 instance,
reachable at https://voltway.splunko11y.com and protected by HTTP Basic Auth.

The application code and all Kubernetes manifests live in the Galileo repo
[rungalileo/mongodb_local_nyc_demo](https://github.com/rungalileo/mongodb_local_nyc_demo),
which is public. Container images are published from that repo to
`ghcr.io/rungalileo/voltway-api` and `ghcr.io/rungalileo/voltway-web`.

## Prerequisites

Gather these before provisioning, since the application cannot start without all
three:

* A **MongoDB Atlas** connection string for an already-seeded `ai_ops_desk`
  database. The repo's `DEPLOY-K8S.md` covers seeding a fresh one.
* An **OpenAI API key**. All agents use OpenAI directly; there is no Azure or
  gateway in front of it.
* A **Galileo API key issued for the `demo.sao.splunkcloud.com` stack**. The key
  and the console/API URLs must belong to the same stack — a mismatch returns
  `401 Invalid credentials` on every chat and no agents run at all.

## Provision an EC2 Instance

Use the interactive deployment script in the [k3d-ec2-instance](../k3d-ec2-instance/)
folder to provision an EC2 instance. Start by launching the script:

```bash
./deploy.sh
```

Select the following options when prompted:

* Create new Instance
* Choose `Yes` when asked whether a public URL is required
* Enter `voltway` as the instance name
* Select `t3.large` as the instance type

The name becomes the subdomain, so it must be exactly `voltway` to get
`https://voltway.splunko11y.com`. Answering `Yes` is what creates the network
load balancer, the Route 53 record, and the Let's Encrypt certificate, so no
manual DNS work is needed afterwards.

## SSH to the New Instance

First, ssh to the jump box:

```bash
ssh o11y-jumpbox
```

Then add the new instance to the `~/.ssh/config` file on o11y-jumpbox, using the
private IP that `deploy.sh` printed:

```
Host voltway
  Hostname 10.0.x.x
  User ubuntu
  IdentityFile ~/.ssh/o11ydemodublin.pem
```

Then we can ssh to the new instance from the jump box:

```bash
ssh voltway
```

## Allowlist the Instance in MongoDB Atlas

Atlas rejects connections from unknown addresses, and this failure is easy to
misread: `/api/health` stays green while every data call fails. Get the egress
address of the new instance:

```bash
curl -s https://ifconfig.me
```

If the instance has no public IP, this returns the public address of the NAT
gateway used by its subnet, which is the address Atlas sees. Add it under
**Atlas → Network Access → IP Access List**.

## Clone the GitHub Repo

```bash
git clone https://github.com/rungalileo/mongodb_local_nyc_demo.git
cd ~/mongodb_local_nyc_demo
```

## Create the Namespace

```bash
kubectl apply -f deploy/k8s/namespace.yaml
```

## Create the Application Secret

Create the secret imperatively so credentials never land in git. `read -rs`
prompts for each value without echoing it and without recording it in your shell
history:

```bash
read -rsp 'Atlas connection string: ' MONGODB_URI; echo
read -rsp 'OpenAI API key: ' OPENAI_API_KEY; echo
read -rsp 'Galileo API key: ' GALILEO_API_KEY; echo

kubectl -n voltway create secret generic voltway-secrets \
  --from-literal=MONGODB_URI="$MONGODB_URI" \
  --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY" \
  --from-literal=GALILEO_API_KEY="$GALILEO_API_KEY"
```

The Atlas value is the SRV connection string from **Atlas → Connect → Drivers**.
Paste it bare, with no surrounding quotes.

Non-sensitive configuration is already committed as a ConfigMap in
`deploy/k8s/configmap.yaml` — Galileo URLs, project name, Agent Control settings
and the allowed origin. Review it, but it should not need editing for this
hostname.

> Do not add quotes around values in the YAML manifests. `python-dotenv` strips
> quotes from `.env`, but Kubernetes passes ConfigMap and Secret values through
> verbatim, so a quoted connection string arrives with its quotes attached and
> fails with `Invalid URI scheme`.

## Create the Application Password

The demo is served on a public URL, so the ingress enforces HTTP Basic Auth. Set
the password **before** applying the manifests — the Traefik middleware
references a secret that must already exist:

```bash
deploy/scripts/set-password.sh              # user "voltway", prompts for password
deploy/scripts/set-password.sh alice        # pick a different username
```

The script writes a bcrypt hash into the `voltway-basicauth` secret. Re-run it
any time to rotate the password; Traefik picks up the change without restarting
any pods.

## Install the Application

```bash
kubectl apply -k deploy/k8s
```

Use `-k`, not `-f deploy/k8s/`. Applying the directory with `-f` processes files
alphabetically and tries to create Deployments before the Namespace exists;
kustomize orders resources by kind.

Ensure both application pods are running:

```bash
kubectl -n voltway get pods
```

You should see one pod each for the API and the web frontend:

```
NAME                            READY   STATUS    RESTARTS   AGE
voltway-api-665d9c4bb7-hppr9    1/1     Running   0          2m
voltway-web-5db58477b5-l92rk    1/1     Running   0          2m
```

The API runs a single replica by design. Its "live target" repointing mutates
the process environment in place, so a second pod would answer status polls with
stale state.

Then confirm the TLS certificate has been issued, which gates the public URL:

```bash
kubectl -n voltway get certificate
```

Wait for `READY` to become `True`. This takes a couple of minutes on a new
instance.

## Test the Application

The application is accessible at:

https://voltway.splunko11y.com

Enter the Basic Auth credentials at the browser prompt. Then ask the demo
question — *"Is there any discount on the YPhone 16 Pro Max?"* — and watch the
reply build up agent by agent. Progressive output confirms server-sent events are
passing through the ingress rather than being buffered.

Traces appear in the `volt-assistant` project at
https://console.demo.sao.splunkcloud.com.

To check the backend without going through the ingress or Basic Auth, use
`port-forward`. This is the quickest way to tell an application problem apart
from an ingress or auth problem:

```bash
kubectl -n voltway port-forward svc/voltway-api 8000:8000 &

curl -s localhost:8000/api/health            # -> {"ok":true}
curl -s localhost:8000/api/users             # -> user list; proves Atlas works
curl -s localhost:8000/api/ops/live_target   # -> active Galileo project
```

## Stop the Application

```bash
kubectl delete -k deploy/k8s
```

The namespace, and with it both secrets, is removed. To keep the manifests but
scale the demo down between events:

```bash
kubectl -n voltway scale deploy voltway-api voltway-web --replicas=0
```

## Further Documentation

[DEPLOY-K8S.md](https://github.com/rungalileo/mongodb_local_nyc_demo/blob/main/DEPLOY-K8S.md)
in the application repo is the authoritative reference: manifest-by-manifest
detail, how to build and test the whole stack on a local k3d cluster first, and
the operational constraints behind the single replica.

The demo walkthrough and talk track are in
[ai-ops-desk/EXPIRED_PROMO_DEMO.md](https://github.com/rungalileo/mongodb_local_nyc_demo/blob/main/ai-ops-desk/EXPIRED_PROMO_DEMO.md).
