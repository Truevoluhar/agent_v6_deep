# OpenShift deployment

This folder adds an OpenShift deployment path without changing the existing
Docker Compose development deployment.

## What is included

- Binary `BuildConfig` objects for `agent-api`, `workspace-api`, and `client`.
- OpenShift-specific Dockerfiles under `openshift/dockerfiles/`.
- Deployments, Services, and Routes for the app services.
- PostgreSQL using the OpenShift-friendly SCL PostgreSQL image.
- Persistent storage for PostgreSQL and the shared application data directory.

The application code, existing Dockerfiles, and `docker-compose.yml` remain the
development setup.

## Deploy

From the repository root:

```bash
oc new-project agent-platform
```

Create the runtime secret before applying the deployment. Keep the PostgreSQL
password in `POSTGRESQL_PASSWORD` and `DATABASE_URL` identical:

```bash
oc create secret generic agent-platform-secrets \
  --from-literal=POSTGRESQL_USER=deepagents \
  --from-literal=POSTGRESQL_PASSWORD='<postgres-password>' \
  --from-literal=POSTGRESQL_DATABASE=deepagents \
  --from-literal=DATABASE_URL='postgresql://deepagents:<postgres-password>@postgres:5432/deepagents' \
  --from-literal=AUTH_BOOTSTRAP_ADMIN_PASSWORD='<admin-password>' \
  --from-literal=OPENAI_API_KEY='<openai-api-key>' \
  --from-literal=BIFROST_API_KEY='dummy-key' \
  --from-literal=BIFROST_MCP_API_KEY='dummy-key' \
  --from-literal=VLLM_API_KEY='dummy'
```

`secret.example.yaml` is provided as a template if your deployment process
prefers manifest-managed secrets.

Apply the OpenShift resources:

```bash
oc apply -k openshift
```

Then build the images from the local repository:

```bash
oc start-build agent-api --from-dir=. --follow
oc start-build workspace-api --from-dir=. --follow
oc start-build client --from-dir=. --follow
```

Update the public URLs after the routes exist:

```bash
oc get route client agent-api
oc patch configmap agent-platform-config --type merge \
  -p '{"data":{"APP_PUBLIC_URL":"https://<client-route-host>","AGENT_API_PUBLIC_URL":"https://<agent-api-route-host>"}}'
oc rollout restart deployment/agent-api deployment/client
```

Open the `client` route in a browser.

## Configuration notes

- `ACTIVE_PROVIDER` defaults to `openai` in `configmap.yaml`.
- For Bifrost or vLLM, set `ACTIVE_PROVIDER` and the matching base URL/API key
  values in the config map and secret.
- Optional TLS certificate files can be mounted by creating a secret named
  `agent-platform-certificates`; it is mounted at `/certs` in `agent-api`.
- The shared app data PVC requests `ReadWriteMany` because the three app pods
  all use `/data`. If your cluster does not provide RWX storage, keep the app
  services co-located another way or provide an RWX-capable storage class.
- The services are configured for one replica each. Keep `agent-api` at one
  replica unless the runtime locking/checkpoint behavior is reviewed for
  multi-replica use.

## Development deployment

The existing local deployment is unchanged:

```bash
cp .env.example .env
docker compose up -d --build
```
