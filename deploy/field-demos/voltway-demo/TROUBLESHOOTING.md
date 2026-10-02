# Troubleshooting

## SSH to the New Instance

The first step in troubleshooting is usually to ssh to the ec2 instance where the
demo application is running. Start by connecting to the jump box:

```bash
ssh o11y-jumpbox
```

Then ssh to the `voltway` instance from the jump box:

```bash
ssh voltway
```

`k9s` is installed on the instance and is usually the fastest way to watch pods
and read logs.

## Troubleshoot the Application

Start by ensuring both application pods are running:

```bash
kubectl -n voltway get pods
```

You should see one pod each for the API and the web frontend:

```
NAME                            READY   STATUS    RESTARTS   AGE
voltway-api-665d9c4bb7-hppr9    1/1     Running   0          3h
voltway-web-5db58477b5-l92rk    1/1     Running   0          3h
```

To view the application logs:

```bash
kubectl -n voltway logs -l app.kubernetes.io/name=voltway-api
kubectl -n voltway logs -l app.kubernetes.io/name=voltway-web
```

## Isolate the Layer That Is Broken

Work from the inside out. `port-forward` talks straight to the Service, bypassing
both the ingress and Basic Auth, so a working `port-forward` and a failing public
URL narrows the problem to TLS, DNS, or auth:

```bash
kubectl -n voltway port-forward svc/voltway-api 8000:8000 &

curl -s localhost:8000/api/health    # app alive?
curl -s localhost:8000/api/users     # Atlas reachable?
```

Then test through the ingress:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://voltway.splunko11y.com/api/health
# -> 401 expected without credentials

curl -s -u voltway:PASSWORD https://voltway.splunko11y.com/api/health
# -> {"ok":true}
```

## The Chat Returns "Unable to generate response due to API error"

Everything else looks healthy: pods are running, `/api/health` is green, the user
list loads. This is almost always outbound HTTPS to OpenAI failing. Check from
inside the pod:

```bash
kubectl -n voltway exec deploy/voltway-api -- \
  python -c "import urllib.request; urllib.request.urlopen('https://api.openai.com', timeout=10)"
```

A `CERTIFICATE_VERIFY_FAILED` error means the cluster's egress is behind a
TLS-inspecting proxy, and the corporate CA has to be trusted by the pod. The
workaround is documented under **Corporate TLS interception** in the application
repo's `DEPLOY-K8S.md`. An invalid or exhausted OpenAI key produces an
authentication or quota error here instead.

## Every Chat Fails with "401 Invalid credentials"

```
Galileo API returned HTTP status code 401 ... Invalid credentials.
```

The `GALILEO_API_KEY` does not belong to the stack named in
`GALILEO_CONSOLE_URL` and `GALILEO_API_URL`. All three must match the same stack,
which for this demo is `demo.sao.splunkcloud.com`. This is not degraded tracing —
the Galileo client is initialised on the request path, so no agents run at all
and the demo is down. Verify what the pod actually received:

```bash
kubectl -n voltway get configmap voltway-config -o yaml | grep GALILEO
```

Pointing the demo at a different stack requires a new API key issued for that
stack.

## The User List Is Empty or Data Calls Time Out

`/api/health` does not touch MongoDB, so it stays green while every data call
fails. The usual cause is the instance's egress address not being in the Atlas IP
access list — and a rebuilt instance has a new address. Get the address Atlas
sees and add it under **Atlas → Network Access**:

```bash
curl -s https://ifconfig.me
```

The other possibility is a quoted `MONGODB_URI`. Kubernetes passes secret values
through verbatim, so quotes become part of the string and the driver rejects it
with `Invalid URI scheme: URI must begin with 'mongodb://' or 'mongodb+srv://'`.
The application logs show this at startup.

## The Site Returns 404 for Everything

Traefik returns 404, rather than an error, when a route cannot be resolved —
including when the ingress references a middleware that does not exist. Check the
annotation value, which must be `<namespace>-<middleware-name>@kubernetescrd`:

```bash
kubectl -n voltway get ingress voltway -o yaml | grep middlewares
# -> traefik.ingress.kubernetes.io/router.middlewares: voltway-basicauth@kubernetescrd

kubectl -n voltway get middleware
# -> basicauth
```

The `voltway-` prefix is the namespace, not part of the middleware name.

## The Site Returns 500 for Everything

The Basic Auth middleware references the `voltway-basicauth` secret, and Traefik
fails the request if it is missing — which happens when the manifests were
applied before the password was set:

```bash
kubectl -n voltway get secret voltway-basicauth
```

If it is absent, create it and the site recovers without a redeploy:

```bash
deploy/scripts/set-password.sh
```

## The Browser Shows a Certificate Warning or Cannot Connect

Check that cert-manager issued the certificate:

```bash
kubectl -n voltway get certificate
kubectl -n voltway describe certificate voltway-tls
```

`READY` must be `True`. If it is stuck, the usual causes are DNS not yet
propagated for `voltway.splunko11y.com` or the Let's Encrypt HTTP-01 challenge
not reaching the cluster. Look at the challenge resources:

```bash
kubectl get challenges -A
```

Note that cert-manager is installed by the instance's cloud-init on **first boot
only**. If the instance was rebuilt by other means, confirm it is present:

```bash
kubectl get pods -n cert-manager
```

## Pods Stuck in ImagePullBackOff

```bash
kubectl -n voltway describe pod -l app.kubernetes.io/name=voltway-api | tail -20
```

A `denied` or `unauthorized` message means the GitHub Container Registry packages
are still private. Make both `voltway-api` and `voltway-web` public in the source
repo under **Packages → Package settings → Change visibility**, or add an
`imagePullSecret`. The manifests assume public images.

## The Reply Appears All at Once Instead of Streaming

The agent-by-agent reveal is the point of the demo, so losing it matters even
though the answer is still correct. The backend sends `X-Accel-Buffering: no` and
Traefik streams by default, so this indicates something buffering in between.
Confirm the stream is chunked at the ingress:

```bash
curl -N -s -u voltway:PASSWORD \
  -H 'Content-Type: application/json' \
  -d '{"user_query":"Is there any discount on the YPhone 16 Pro Max?","user_id":"u1"}' \
  https://voltway.splunko11y.com/api/chat/stream
```

Events should arrive progressively. If they do here but not in the browser, the
problem is on the client side rather than in the cluster.

## Nothing Appears in the Galileo Console

Traces go to the `volt-assistant` project on `demo.sao.splunkcloud.com`. If chats
succeed but traces are missing, check that the Ops drawer has not repointed the
live target at a different project:

```bash
kubectl -n voltway exec deploy/voltway-api -- cat /data/.galileo_active_target.json
```

That file records the currently selected target. It lives on an `emptyDir`, so it
resets when the pod restarts — which also resets the demo to its default project.
