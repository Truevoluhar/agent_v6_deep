# deepagents-platform

Splošna platforma DeepAgents z Docker Compose, vidno trajno mapo `data/`, PostgreSQL checkpointi, API-jem za upravljanje datotek in samostojnim Streamlit odjemalcem.

## Storitve

- `agent-api` na `:8081`: izvajalno okolje DeepAgents workflowa.
- `workspace-api` na `:8090`: varen API za nalaganje, seznam, prenos in brisanje datotek v skupnem workspaceu.
- `client` na `:8501`: preprost klepetalni in datotečni uporabniški vmesnik.
- `postgres`: shramba LangGraph checkpointov.

## Hitri zagon

```bash
cp .env.example .env
docker compose up -d --build
```

Preverjanje zdravja:

```bash
curl http://localhost:8081/health
curl http://localhost:8090/health
```

Odprite `http://localhost:8501`.

## Menjava ponudnika

Uredite `.env`:

```dotenv
ACTIVE_PROVIDER=openai
OPENAI_API_KEY=your-real-key
```

Ali:

```dotenv
ACTIVE_PROVIDER=vllm
VLLM_BASE_URL=http://your-vllm-host:8000/v1
VLLM_API_KEY=dummy
```

Ali:

```dotenv
ACTIVE_PROVIDER=bifrost
BIFROST_BASE_URL=http://your-bifrost-host:8080/openai
BIFROST_MODEL=openai/gpt-4o-mini
BIFROST_API_KEY=dummy-key
```

OpenAI ne potrebuje certifikatnih datotek ali posebnih TLS nastavitev.

Bifrost v opisani lokalni oziroma zasebni postavitvi prav tako ne potrebuje dodatnih certifikatnih nastavitev. OpenAI-združljivega odjemalca usmerite na osnovni URL prehoda `/openai`, ključe nadrejenih ponudnikov pa hranite v Bifrostu.

Za zasebne vLLM TLS ali mTLS prehode shranite certifikate v lokalno mapo `certs/` in v `.env` nastavite možnosti za vLLM:

```dotenv
VLLM_TLS_VERIFY=true
VLLM_CA_FILE=/certs/internal-ca.pem
VLLM_CLIENT_CERT_FILE=/certs/client.pem
VLLM_CLIENT_KEY_FILE=/certs/client.key
```

`VLLM_TLS_VERIFY=false` nastavite samo, kadar namerno izklopite preverjanje certifikatov.

Definicije ponudnikov so v [config/providers.yaml](config/providers.yaml).

## Strukturirani odgovori

V klepetalnem vmesniku izberite **JSON Schema** in uredite shemo odgovora. API sprejme shemo za posamezno sporočilo:

```json
{
  "message": "Povzemi poročilo",
  "response_schema": {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
    "additionalProperties": false
  }
}
```

Agent to pošlje konfiguriranemu OpenAI-združljivemu ponudniku v strogem načinu JSON Schema. Strogi način zahteva, da je vsaka lastnost objekta navedena v `required` in da je `additionalProperties` nastavljen na `false`. Upoštevanje sheme je odvisno od modela oziroma ponudnika; zavrnitve in nepopolni odgovori se lahko od sheme razlikujejo.

## Vid in anonimizacija PDF

Agent lahko pregleda slike JPEG, PNG, WebP, GIF, BMP in TIFF ter strani PDF. Datoteko naložite v workspace z `POST /v1/files`, nato vrnjeno pot vključite v zahtevo klepetalnega API-ja:

```json
{
  "message": "Opiši dokument in zakrij osebne podatke.",
  "attachments": ["/uploads/potrdilo.pdf"]
}
```

GUI sprejme več slikovnih ali PDF priponk pri enem sporočilu. Agent lahko pregleda tudi datoteke, ki so že v workspaceu, če uporabnik navede njihove poti. Pri skeniranih PDF-jih strani izriše za vision model. Slike strani in pozivi se pošljejo konfiguriranemu modelnemu endpointu, zato uporabite endpoint, ki je odobren za obdelovane dokumente. Za anonimizacijo prosite agenta, naj zakrije osebne podatke; uporabi `redact_pdf_personal_data` in nov PDF zapiše pod `/exports/`, izvorna datoteka pa ostane nespremenjena.

Anonimiziran izhod je rasteriziran, zato se prvotna besedilna plast in skrita vsebina PDF-ja ne preneseta v rezultat. Agent shranjene strani preveri z OCR in drugim vision pregledom. Če je preverjanje negotovo ali najde možne osebne podatke, izhoda ne označi kot dokončanega. Samodejno prepoznavanje slik ne more zagotoviti popolne zaznave, zato rezultat pred zunanjo objavo preglejte. Rasterizirani PDF nima iskalne besedilne plasti.

## Trajnost podatkov

Trajni podatki živijo v lokalni mapi repozitorija `data/`:

```text
data/
  agent_workspace/   Datoteke workspacea, vidne agentu
  session/           Metapodatki niti in prepisi
  memory/            Rezerviran trajni spomin
  resources/         Skupni viri
  runs/              Dnevniki procesov in artefakti zagonov
```

Agentov workspace je `data/agent_workspace/`. Ponovna gradnja ali ponovni zagon storitev ne izbriše vsebine `data/`. PostgreSQL ostane trajen prek lastnega Docker volumna.

## Struktura

```text
config/           Konfiguracija ponudnikov
agent_api/        Storitev FastAPI za DeepAgents
workspace_api/    Storitev FastAPI za workspace
client/           Streamlit UI
data/             Vidni trajni podatkovni koren
skills/           Začetne veščine DeepAgents
workspace_seed/   Začetni AGENTS.md spomin
tests/            Testi nalagalnika konfiguracije
```

## Večuporabniški dostop

Lokalna prijava, uporabniški workspacei, administracija računov in obvezna `guid` query avtentikacija so opisani v [MULTIUSER.md](MULTIUSER.md). Začetni račun je `admin` / `admin123`; po prvi prijavi spremenite geslo. Izvajanje shell ukazov in skupna MCP orodja so izključena, ker ta Compose postavitev nima preverjenega izvajalnega sandboxa.

## Opombe

- Aplikacija ne podpira pretočnih odgovorov.
- Uporabite enega `agent-api` workerja; zaklepi invokacij so lokalni procesu.
