# Staged docs for splunk/o11y-field-demos

These files are written to be copied **as-is** into the
[splunk/o11y-field-demos](https://github.com/splunk/o11y-field-demos) repo. They
live here so they are versioned alongside the manifests they describe, and so
they can be reviewed before anyone has write access to the Splunk org.

They follow the conventions of the existing demo folders in that repo
(`travel-planner-demo-v2`, `splunk-agent-observability-demo`): a `README.md` with
the setup path from provisioning to a working URL, and a `TROUBLESHOOTING.md`
organised by observed symptom.

## How to land them

Copy the folder to the root of a clone of `o11y-field-demos`:

```bash
cp -r deploy/field-demos/voltway-demo /path/to/o11y-field-demos/voltway-demo
```

The relative link to `../k3d-ec2-instance/` in the README resolves correctly once
the folder sits at that repo's root. Links back to the application repo are
absolute, so they work from either location.

> Before copying, check one thing: those absolute links point at `blob/main`, and
> this work is currently on the `promo-hallucination-clarity` branch. They will
> 404 until it merges. Either merge first or temporarily swap `main` for the
> branch name.

Then add a row to the **Demos** table in that repo's root `README.md`:

```
| O11y Cloud | [mongodb_local_nyc_demo](https://github.com/rungalileo/mongodb_local_nyc_demo) | [Voltway Demo Walkthrough](https://github.com/rungalileo/mongodb_local_nyc_demo/blob/main/ai-ops-desk/EXPIRED_PROMO_DEMO.md) | [Setup](./voltway-demo/README.md) / [Troubleshooting](./voltway-demo/TROUBLESHOOTING.md) |
```

The "Datagen" column points at the Galileo repo rather than a folder in
`o11y-field-demos`, which is the same pattern `travel-planner-demo-v2` and
`splunk-agent-observability-demo` already use for applications whose source lives
in another repo.

## Keep these in sync

If `deploy/k8s/` or `DEPLOY-K8S.md` changes in a way that affects the deploy
steps, update `voltway-demo/README.md` here first, then re-copy. The field-demos
README deliberately stays a linear runbook and defers detail to `DEPLOY-K8S.md`,
so most changes should only need a link rather than new prose.
