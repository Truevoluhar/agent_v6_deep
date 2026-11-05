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

### Shell izvajanje

Agent ima omogočeno izvajanje ukazov v namenski mapi `/shell_executions` za vsakega uporabnika. Ukazi, Python skripte, virtualna okolja, nameščeni paketi, začasne datoteke in strežniki se hranijo v tej mapi. Delovni imenik `cwd` je relativna pot znotraj nje. Ukazi tečejo v OS peskovniku, ki dovoljuje zapisovanje samo v to mapo, sistemske runtime datoteke pa so na voljo samo za branje. Ukazi imajo omrežni dostop, zato lahko nameščajo pakete in strežejo aplikacije.

Linux izvajanje zahteva bubblewrap ter podporo runtimea za neprivilegirane user in PID namespace. Če namespace ni mogoče ustvariti, se ukaz zavrne. V Docker Compose je seccomp filter za `agent-api` izklopljen, da bubblewrap lahko ustvari namespace; procesu `agent-api` sta dodani samo `SETUID` in `SETGID`, ki ju potrebuje za preslikavo UID/GID. Bubblewrap pred zagonom ukaza odstrani vse capabilities, vklopljen pa ostaja `no-new-privileges`.

Za Python pakete uporabite virtualno okolje (`python -m venv .venv`) ali `pip install --user`; globalna namestitev paketov v sistemske mape ni dovoljena. Dolgotrajne procese zaženite z `start_background_process`, nato uporabite orodja za pregled izhoda in ustavitev.

### Razmišljanje in izhodni žetoni modela

Vsi klici uporabljajo skupni izklop razmišljanja in zgornjo mejo izhodnih žetonov. Privzeto je razmišljanje izklopljeno, največje število izhodnih žetonov na klic pa je 150.000. Nastavitvi veljata tudi za Bifrost, ki posreduje zahteve v vLLM; neposredni vLLM in Bifrost prejmeta `chat_template_kwargs.enable_thinking=false`, OpenAI pa `reasoning_effort=none`.

V `.env` ju lahko prilagodite:

```dotenv
LLM_THINKING_ENABLED=false
LLM_MAX_OUTPUT_TOKENS=150000
```

`LLM_MAX_OUTPUT_TOKENS` mora biti pozitivno celo število in ne sme presegati omejitve izbranega modela. Omejitev velja tudi za izrecne manjše omejitve, ki jih uporabljata pregled slik in oblikovanje strukturiranih odgovorov.

## Zaščita konteksta

Agent velike rezultate orodij shrani v workspace in modelu vrne predogled s potjo do celotnega rezultata; zunanji rezultati orodij se prestrežejo pri 24.000 znakih, DeepAgents pa ima še svoj prag pri 6.000 ocenjenih tokenih. Pred vsakim klicem modela DeepAgents najprej povzame starejšo zgodovino; dodatni proračunski pregled preveri tudi sistemski poziv, zgodovino in definicije orodij z varnostno rezervo za gostejše tokeniziranje. Privzeta meja konteksta je 128.000 tokenov, povzetek se sproži pri 40 %, modelu pa ostane največ 70 % okna za vhod. Nastavite `AGENT_CONTEXT_WINDOW_TOKENS` glede na dejansko vhodno okno izbranega modela oziroma ponudnika.

Polni rezultati ostanejo dostopni prek vrnjene poti, zato lahko agent z `read_file` pridobi natančne definicije tabel ali druge podatke, ki jih predogled ne vsebuje.

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
