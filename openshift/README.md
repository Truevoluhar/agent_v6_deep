# Namestitev na OpenShift

Ta mapa dodaja pot za namestitev na OpenShift, ne da bi spreminjala obstoječo razvojno postavitev z Docker Compose.

## Kaj je vključeno

- Binarni `BuildConfig` objekti za `agent-api`, `workspace-api` in `client`.
- OpenShift Dockerfile datoteke v `openshift/dockerfiles/`.
- Deploymenti, Service-i in Route-i za aplikacijske storitve.
- PostgreSQL z OpenShift-prijazno SCL PostgreSQL sliko.
- Trajna shramba za PostgreSQL in skupno aplikacijsko mapo podatkov.

Aplikacijska koda, obstoječi Dockerfile-i in `docker-compose.yml` ostanejo razvojna postavitev.

## Namestitev

Iz korena repozitorija:

```bash
oc new-project agent-platform
```

Pred uporabo ustvarite runtime secret. Geslo v `POSTGRESQL_PASSWORD` in v `DATABASE_URL` mora biti enako:

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

`secret.example.yaml` je predloga, če vaš proces raje upravlja skrivnosti z manifesti.

Uporabite OpenShift vire:

```bash
oc apply -k openshift
```

Nato zgradite slike iz lokalnega repozitorija:

```bash
oc start-build agent-api --from-dir=. --follow
oc start-build workspace-api --from-dir=. --follow
oc start-build client --from-dir=. --follow
```

Po ustvarjanju route-ov nastavite javna URL-ja:

```bash
oc get route client agent-api
oc patch configmap agent-platform-config --type merge \
  -p '{"data":{"APP_PUBLIC_URL":"https://<client-route-host>","AGENT_API_PUBLIC_URL":"https://<agent-api-route-host>"}}'
oc rollout restart deployment/agent-api deployment/client
```

V brskalniku odprite route `client`.

## Konfiguracijske opombe

- `ACTIVE_PROVIDER` je v `configmap.yaml` privzeto `openai`.
- Za Bifrost ali vLLM nastavite `ACTIVE_PROVIDER` ter pripadajoči osnovni URL in API ključ v config mapu oziroma secretu.
- Shell izvajanje uporablja bubblewrap in zahteva, da varnostna politika gruče dovoli neprivilegirane user in PID namespace. Če tega ne dovoli, se shell ukaz varno zavrne; podatkovni dostop brez peskovnika ni omogočen.
- Neobvezne TLS certifikate lahko priklopite s secretom `agent-platform-certificates`; v `agent-api` je na voljo v `/certs`.
- Skupni PVC aplikacije zahteva `ReadWriteMany`, ker vse tri aplikacijske pod-e uporabljajo `/data`. Če gruča nima RWX shrambe, zagotovite RWX storage class ali drugo ustrezno souporabo podatkov.
- Storitve so nastavljene na eno repliko. `agent-api` naj ostane pri eni repliki, dokler runtime zaklepanje in checkpoint vedenje nista pregledana za več replik.

## Razvojna postavitev

Obstoječa lokalna postavitev ostane nespremenjena:

```bash
cp .env.example .env
docker compose up -d --build
```
