# Gradnja splošne platforme DeepAgents z Docker Compose

**Referenčna implementacija:** `deepagents-platform`
**Cilj:** zanesljiv agentski sistem z zamenljivimi ponudniki za analizo datotek, ustvarjanje artefaktov, pregled kode, obrambni varnostni pregled, ustvarjanje Draw.io diagramov, večkoračno raziskovalno delo in splošne inženirske naloge.
**Izvajanje:** Docker Compose
**LLM zaledja:** javni OpenAI ali zasebni OpenAI-združljiv vLLM
**Osnova DeepAgents:** `deepagents==0.7.15`

## 1. Cilji in omejitve zasnove

Platforma ima tri logične dele:

1. **Storitev DeepAgents workflowa** upravlja orkestracijo, modelne klice, middleware, veščine, načrtovanje, podagente, checkpointe in orodja za shell oziroma datotečni sistem.
2. **Trajni podatki in agentov workspace** hranijo datoteke, artefakte in trajno stanje grafa. Referenčna izvedba uporablja Docker volume za workspace in PostgreSQL za LangGraph checkpointe.
3. **Odjemalec za klepet** je ločen UI, ki upravlja seje, nalaganje datotek in brskanje po workspaceu, ne da bi izvajal agentov runtime v procesu UI-ja.

Ključno arhitekturno pravilo je, da je vsebnik agenta zamenljiv. Ponovna gradnja ali zamenjava `agent-api` ne sme izbrisati uporabniških datotek ali stanja pogovorov.

Sistem potrebuje tudi abstrakcijo ponudnika. Aplikacijska koda ne sme biti odvisna od tega, ali model teče pri OpenAI ali na zasebnem vLLM endpointu. Oba sta predstavljena kot OpenAI-združljiva klepetalna modela, izbrana s konfiguracijo.

## 2. Zakaj DeepAgents ustreza tej arhitekturi

DeepAgents je agentski okvir na LangGraphu z vgrajenim načrtovanjem, datotečnimi orodji, podagenti, veščinami, upravljanjem konteksta, kavlji za trajni spomin in zamenljivimi zaledji. Primeren je za dolgotrajne večkoračne agentske tokove in je neodvisen od ponudnika, če izbrani model podpira klicanje orodij.

Ločiti je treba dve vrsti trajnosti:

- **Trajnost grafa in checkpointov** hrani stanje pogovora, prekinitve, nadaljevanje in stanje agentskega grafa.
- **Trajnost datotečnega sistema in spomina** hrani datoteke, artefakte, trajna navodila, projektni kontekst in gradivo za predajo med nadrejenimi agenti in podagenti.

Ne predpostavljajte, da trajno stanje klepeta samodejno pomeni trajne datoteke workspacea ali obratno.

## 3. Referenčna arhitektura

```text
Browser / User -> client :8501 -> agent-api :8081
                         \-> workspace-api :8090
agent-api -> PostgreSQL checkpointi
agent-api in workspace-api -> trajni workspace
agent-api -> OpenAI API ali zasebni vLLM /v1 endpoint
```

Storitve Docker Compose:

- `postgres`: trajna baza checkpointov.
- `workspace-api`: majhna storitev za nadzorovano nalaganje, seznam, prenos in brisanje datotek.
- `agent-api`: izvajalna storitev DeepAgents.
- `client`: samostojni klepetalni in datotečni UI.

Trajni volumni oziroma mape:

- `postgres_data`: podatkovna mapa PostgreSQL.
- `data/agent_workspace`: trajni agentov workspace.

Datoteke ne smejo živeti samo v sliki vsebnika ali v zapisljivi plasti vsebnika.

## 4. Struktura repozitorija

```text
deepagents-platform/
├── docker-compose.yml
├── .env.example
├── Makefile
├── README.md
├── MANUAL.md
├── config/
│   └── providers.yaml
├── agent_api/
├── workspace_api/
├── client/
├── skills/
├── workspace_seed/
└── tests/
```

## 5. Konfiguracija ponudnikov

Nastavitve ponudnikov so v `config/providers.yaml`. Skrivnosti se ne smejo zapisovati neposredno v YAML; `.env` ali secret manager priskrbi vrednosti. Nalagalnik podpira razširjanje `${NAME}` in `${NAME:-default}`, zato lahko zamenjate ponudnika brez vpisovanja modelne konfiguracije v Python.

Primer preklopa na vLLM v `.env`:

```dotenv
ACTIVE_PROVIDER=vllm
VLLM_BASE_URL=http://your-vllm-host:8000/v1
VLLM_API_KEY=dummy-or-real-key
```

Nato ponovno zgradite ali zaženite `agent-api`:

```bash
docker compose up -d --build agent-api
```

Spremembe workflow kode niso potrebne.

## 6. Nastavitev OpenAI

Ustvarite `.env` iz primera:

```bash
cp .env.example .env
```

Nastavite:

```dotenv
ACTIVE_PROVIDER=openai
OPENAI_API_KEY=your-real-key
```

Ime modela pustite v `config/providers.yaml`. V produkciji skrivnosti vbrizgajte s sistemom za upravljanje skrivnosti, ne s commitano `.env` datoteko.

## 7. Nastavitev zasebnega vLLM

vLLM ponuja OpenAI-združljive endpointe, zato se lahko uporabi isti razred odjemalca `ChatOpenAI` z drugim `base_url`, `api_key` in `model`.

Agentska obremenitev potrebuje zanesljivo **klicanje orodij**, ne samo običajne generacije besedila. vLLM konfigurirajte temu primerno:

```bash
vllm serve <your-tool-capable-model> \
  --host 0.0.0.0 \
  --port 8000 \
  --enable-auto-tool-choice \
  --tool-call-parser <parser-for-your-model> \
  --tool-strict-level function
```

Parser je odvisen od modela. Preverite priporočila dokumentacije vLLM za izbrani model.

Pomembne zahteve:

1. Model mora dejansko dobro uporabljati strukturirana orodja.
2. `--enable-auto-tool-choice` je potreben za samodejno izbiro orodij.
3. `--tool-call-parser` mora ustrezati protokolu modela.
4. Strogo uveljavljanje klicev orodij uporabite, kadar ga parser in model podpirata.
5. Testirajte več zaporednih klicev orodij, ne samo enega odgovora `/v1/chat/completions`.
6. `VLLM_API_KEY` sam ni popolna varnostna meja; zasebni vLLM postavite za proxy, požarni zid, VPN ali service mesh.

## 8. Storitev DeepAgents workflowa

Storitev sestavi model, checkpointer, datotečno zaledje, spominsko datoteko, veščine in agentski graf. Shell okolje agenta ne sme samodejno podedovati vseh skrivnosti procesa. Če naloga res potrebuje poverilnice, jih posredujte ozko in začasno skozi namensko orodje ali nadzorovan ovoj.

## 9. Trajni workspace

`data/agent_workspace` je trajna mapa, ki jo uporabljata `agent-api` in `workspace-api`. Vsak uporabniški workspace vsebuje tudi `/shell_executions`, ki je edina mapa, v kateri lahko agent izvaja shell ukaze.

Priporočena konvencija:

```text
/workspace/
├── uploads/
├── projects/
├── analysis/
├── diagrams/
├── exports/
├── shell_executions/
└── .agent/
    ├── AGENTS.md
    ├── home/
    └── runs/
```

Nadrejeni agenti in podagenti naj za velike datoteke in trajne rezultate uporabljajo poti v datotečnem sistemu. Podagenti imajo ločena kontekstna okna; skupni workspace je zanesljiv most.

V workspace ne shranjujte `.env`, zasebnih SSH ključev, oblačnih poverilnic, produkcijskih kubeconfigov ali nepovezanih gostiteljskih datotek.

## 10. PostgreSQL checkpointi

Agent uporablja `PostgresSaver`. Vsak klepet dobi stabilen `thread_id`; isti `thread_id` nadaljuje pogovor, nov pa začne svež klepet. Za horizontalno skaliranje zamenjajte sinhroni checkpointer z asinhronim PostgreSQL checkpointerjem in connection poolom ter šele nato preverite več API workerjev.

## 11. Odjemalec za klepet

Odjemalec je ločen od runtimea. Njegove naloge so ustvarjanje in ponovna uporaba `thread_id`, pošiljanje sporočil v `agent-api`, nalaganje datotek prek `workspace-api`, brskanje po workspaceu ter prikaz poti in rezultatov.

Začetni UI uporablja Streamlit, ker ohrani primer majhen. Pozneje ga je mogoče zamenjati z React, Next.js, Vue, Svelte ali namiznim odjemalcem brez spremembe agentskega jedra.

## 12. Veščine

Splošni agent ne sme imeti enega ogromnega sistemskega poziva. Stabilno vedenjsko jedro naj bo kratko, nalogam prilagojena navodila pa naj živijo v veščinah.

Začetne veščine:

- **file-analysis**: ciljni pregled datotek, varna obdelava velikih vhodov in izpeljani artefakti.
- **drawio**: urejevalni XML diagrams.net in razlaga v Markdownu.
- **code-review**: pravilnost, vzdržljivost, testi, zmogljivost in tveganje API-ja.
- **security-review**: pooblaščen obrambni pregled ranljivosti in sanacija.

Nove veščine dodajajte kot imenike pod `skills/`; to je lažje testirati in razvijati kot nenehno širiti monolitni sistemski poziv.

## 13. Ustvarjanje Draw.io artefaktov

Agent lahko neposredno ustvari `.drawio` datoteke, ker Draw.io uporablja XML. Veščina naj zapiše `diagram.drawio`, preveri pravilnost XML-ja, zapiše spremljevalni `diagram.md` z opisom vozlišč in tokov ter po potrebi izvozi SVG ali PNG, če je renderer nameščen.

## 14. Pregled kode

Robusten pregled kode naj pregleda repozitorij, zazna jezike in build sistem, prebere projektna navodila, pregleda diff ali zahtevani obseg, varno zažene obstoječe teste, ciljno pregleda izvorno kodo in izda ugotovitve z dokazi. Popravke naj pripravi ločeno, razen če uporabnik zahteva neposredno urejanje.

## 15. Obrambno iskanje ranljivosti

Za pregled ranljivosti lahko utrjena slika po potrebi vključuje `ripgrep`, `git`, jezikovne package managerje, `semgrep`, `trivy`, `grype`, `syft`, `pip-audit`, `npm audit` ali `govulncheck`. Ne nameščajte vseh skenerjev brez razloga.

Dobra varnostna ugotovitev vsebuje lokacijo, prizadeto kodo ali verzijo, dokaz, vpliv, zanesljivost, sanacijo in način preverjanja. Surov izpis skenerja ni samodejno potrjena ranljivost.

## 16. Varnostni model

Shell ukazi tečejo v ločenem bubblewrap mount in PID namespaceu na Linuxu oziroma v macOS sandbox profilu pri lokalnem razvoju. V namespace je priklopljen samo uporabniški `/shell_executions` za zapisovanje; aplikacijski podatki in druge mape niso vidni ukazu. Sistemske izvajalne datoteke so na voljo samo za branje. Če operacijski sistem ali runtime ne omogoča peskovnika, se shell ukaz zavrne.

Compose postavitev vključuje ne-root uporabnike, odstranjene Linux capabilities, `no-new-privileges`, eksplicitno priklopljen trajni workspace, read-only konfiguracijo in veščine ter izolirano bazo na notranjem omrežju.

Za več uporabnikov ali nezaupanja vredne vhode uporabite dejansko izolacijo izvajanja: namenski vsebnik, Kubernetes Job/Pod, Firecracker microVM ali upravljan sandbox na nalogo oziroma najemnika. To je arhitekturna meja, ne težava poziva.

## 17. Zanesljivost

Uporabite timeoute za modele, shell, HTTP prenose, odjemalske zahteve in preklic dolgih zagonov. Omejite agentsko rekurzijo. Vmesne rezultate zapisujte v workspace, da so zagoni pregledni in nadaljivi. Mutacijska orodja naj bodo idempotentna, kadar je izvedljivo.

Ponudnik naj pred omogočanjem opravi sprejemni nabor: preprost odgovor, en klic orodja, več zaporednih klicev, branje in pisanje datotek, shell ukaz, dolg večkoračni načrt, okrevanje po napaki orodja, nadaljevanje po restartu in veljaven Draw.io XML artefakt.

## 18. Opazljivost

V produkciji beležite ID zahteve, ID niti, ID zagona, model in ponudnika, latenco modela, ime in trajanje orodja, izhodni status, porabo tokenov oziroma strošek, ustvarjene artefakte, razred napake in število ponovitev. Nikoli ne beležite API ključev, authorization headerjev ali celotnih izpisov okolja s skrivnostmi.

LangSmith je uporaben za LangGraph oziroma DeepAgents sledenje, vendar naj bo neobvezen. OpenTelemetry je dobra nevtralna dopolnitev.

## 19. Človek v zanki

Za močne operacije dodajte potrditvene korake: destruktivno brisanje, `git push`, zunanje zapisovanje po omrežju, objava paketov, deployment ukazi, mutacije baze in spremembe izven dovoljenega projekta. DeepAgents podpira prekinitvene vzorce s človekom v zanki.

## 20. Zagon referenčnega sklada

```bash
cd deepagents-platform
cp .env.example .env
docker compose up -d --build
curl http://localhost:8081/health
curl http://localhost:8090/health
```

Odprite `http://localhost:8501`. Za test trajnosti naložite datoteko, ustvarite poročilo, zabeležite `thread_id`, ponovno zaženite storitve in preverite, da datoteke ter stanje pogovora ostanejo.

## 21. Dimni testi ponudnika

Najprej preverite endpoint:

```bash
curl "$BASE_URL/models" \
  -H "Authorization: Bearer $API_KEY"
```

Nato preizkusite osnovni klepet in klicanje orodij z minimalno shemo orodja. Pri vLLM to ponovite po vsaki menjavi modela, parserja ali chat templatea.

## 22. Produkcijska evolucija

1. **En uporabnik oziroma zaupanja vredno okolje:** trenutni scaffold, PostgreSQL checkpointer, Streamlit in shell v vsebniku.
2. **Ekipna raba:** avtentikacija, uporabniški workspace namespacei, tabela metapodatkov niti, streaming, preklic zagonov, kvote, politike odobritev in audit dnevniki.
3. **Nezaupanja vredni najemniki:** izolirani sandboxi, omejeno datotečno/object storage okolje, network policy, CPU/RAM/PID kvote, TTL in broker skrivnosti.
4. **Visoka razpoložljivost:** async PostgreSQL pool, več stateless `agent-api` replik, queue/worker model, Redis/NATS/Kafka, object storage, backupi in retention policy.

## 23. Priporočena kasnejša delitev storitev

Zrela notranja platforma se lahko razvije v `web-client`, `api-gateway`, `identity-service`, `conversation-service`, `agent-orchestrator`, `sandbox-manager`, `artifact-service`, `postgres`, `object-storage`, opazovalni sklad in opcijsko iskalno storitev. Ne začnite z vsemi, če jih še ne potrebujete.

## 24. Filozofija konfiguracije

Ločite tri plasti: javno konfiguracijo ob deploymentu, skrivnosti in trajni agentski oziroma projektni spomin. `config/providers.yaml` hrani model, osnovni URL, timeoute, retryje in navodila. `.env` ali secret manager hrani API ključe, žetone in gesla. `/workspace/.agent/AGENTS.md` hrani dogovorjena projektna navodila. Plasti ne mešajte.

## 25. Znane omejitve začetnika

MVP nima pretočnih odgovorov, obdeluje eno sinhrono invokacijo na proces, nima popolne avtorizacije za produkcijski internetni obseg, nima namenske sandbox storitve, nima queueja za ozadje, nima prvega razreda predogleda artefaktov, nima object storagea za zelo velike datoteke in nima registra zmožnosti ponudnikov prek OpenAI-združljivih endpointov.

## 26. Stanje testov

Izvorno drevo je bilo statično preverjeno s Python `compileall`. Polnega živega Docker Compose testa ni bilo mogoče izvesti tam, kjer je bil paket ustvarjen, ker Docker CLI oziroma daemon ni bil na voljo. Pravega klica ponudnika ni bilo mogoče izvesti brez uporabne `.env` oziroma `OPENAI_API_KEY` vrednosti.

## 27. Prvi priporočeni koraki po kloniranju

1. V lokalni `.env` ali secret manager vnesite pravi ključ ponudnika.
2. Potrdite ime modela OpenAI ali izberite vLLM model z dobrim klicanjem orodij.
3. Zaženite sprejemni nabor ponudnika.
4. Dodajte SSE ali WebSocket streaming.
5. Pred izpostavitvijo izven zasebnega omrežja dodajte avtentikacijo.
6. Pri javni izpostavitvi dodajte omejitve CPU-ja, pomnilnika, trajanja in števila sočasnih shell procesov.
7. Dodajajte nalogam prilagojena orodja in veščine namesto neskončnega širjenja sistemskega poziva.
8. Dodajte integracijske teste, ki restartajo storitve in preverijo trajnost checkpointov ter workspacea.
9. Vzpostavite backup PostgreSQL in workspacea oziroma object storagea.

## 28. Primarni viri

- DeepAgents repozitorij: https://github.com/langchain-ai/deepagents
- Arhitektura DeepAgents: https://github.com/langchain-ai/deepagents/blob/main/libs/ARCHITECTURE.md
- Varnostne opombe lokalnega shell zaledja: https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/deepagents/backends/local_shell.py
- Dokumentacija trajnosti LangGraph: https://docs.langchain.com/oss/python/langgraph/add-memory
- vLLM OpenAI-združljiv strežnik: https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/
- vLLM klicanje orodij: https://docs.vllm.ai/en/latest/features/tool_calling/
