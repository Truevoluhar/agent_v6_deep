# Implementacija uporabnikov, prijave in izolacije v agent_v6_deep

Programerska specifikacija, 6. oktober 2026. Posodobljeno glede na zahtevo: brez sprememb obstoječe Docker Compose topologije, oba API-ja ostaneta dostopna navzven, neposredni API klici uporabljajo parameter `guid`.

## 1. Namen in obseg

Implementiraj večuporabniški agentski sistem: prijavljen uporabnik vidi samo svoje pogovore, zgodovino, datoteke, spomin agenta in procese. Vsak uporabnik ima en trajen workspace, ki ga lahko uporablja več njegovih pogovorov. Različni uporabniki nimajo skupnega zapisljivega workspacea. Administrator upravlja račune, vendar tudi administratorjev agent nima dostopa do podatkov drugih uporabnikov.

V prvi različici vse preverjanje prijave deluje lokalno. Samo administrator ustvarja račune. Ob prvi inicializaciji ustvari račun `admin` z geslom `admin123`. Pozneje isti sistem sprejme cookie `guid`, ga preveri pri zunanjem servisu in uporabi potrjeno identiteto. Ločitev podatkov ostane enaka.

To je dokumentacija za izvedbo; spremembe aplikacije še niso implementirane. Dokument temelji na neposrednem pregledu [repozitorija](https://github.com/Truevoluhar/agent_v6_deep), commit `643369d7b688cd140ad51536c75eb90407083d57`. Nove datoteke, poti in pogodbe spodaj so predlogi implementacije.

## 2. Kaj je treba spremeniti v obstoječi kodi

| Obstoječa datoteka / mesto | Trenutno stanje | Zahtevana sprememba |
|---|---|---|
| `agent_api/main.py`, `get_runtime()`, startup | En `app.state.runtime` za vse zahteve | Factory oziroma register runtimeov po internem `user_id`; brez spreminjanja skupne konfiguracije med zahtevami |
| `thread_store_root()`, metadata in JSONL | Skupna mapa `session_root/threads` | Uporabnikov session root in obvezno preverjanje lastništva |
| `post_thread_message()` | Agent se izvede pred `ensure_thread()`; dovoljena implicitna nova seja | Najprej preveri obstoječo lastno sejo; tuje/neobstoječe ID-je zavrni pred izvedbo |
| `agent_api/runtime.py` | Skupni workspace, orodja, procesi, spomin | Vse ustvari z uporabniško konfiguracijo in izvedbenim kontekstom |
| `AgentRuntime.invoke()` | Checkpointer uporablja neposreden `thread_id` | Uporabi notranji ključ `user_id:thread_id` |
| `workspace_api/main.py` | Globalna `WORKSPACE` in `WORKSPACE_ROOT`, brez avtentikacije | Workspace iz potrjenega uporabnika pri vsaki zahtevi |
| `agent_api/processes.py` | Shell v skupnem OS okolju, procesni metapodatki brez lastnika | Lastništvo procesov, validacija ID-jev in eksplicitna politika neizoliranega izvajanja |
| `client/app.py` | Streamlit kliče oba API-ja z `requests`, brez prijave | Prijavni tok, posredovanje `guid`, uporabniško stanje, admin zaslon |
| `docker-compose.yml` | Obstoječe delujoče interno okolje, API-ja objavljena navzven | Ohraniti brez sprememb; avtentikacijo in uporabniški obseg uveljaviti v obeh aplikacijah |

Posebnosti pregleda: `BackgroundProcessManager.start()` trenutno pretvori poti logov skozi `workspace.relative_path()`, čeprav privzeti `RUNS_ROOT=/data/runs` leži zunaj workspacea. Ob spremembi shranjuj relativne poti glede na procesno mapo in jih razrešuj s procesnim shrambevalnikom. Tudi `SKILLS_ROOT=/app/skills` v Compose se uporablja kot virtualna workspace pot pri seedanju; loči izvor skills od virtualne poti `/.agent/skills`.

## 3. Pravila, ki morajo veljati povsod

1. Interni `user_id` je strežniško ustvarjen UUID in se nikoli ne spremeni ob preimenovanju računa ali menjavi avtentikacije.
2. `guid` je prijavni token, ne ID uporabnika in ne ime mape. Dve prijavi istega uporabnika lahko imata različna tokena in uporabljata isti workspace.
3. Uporabnika določi samo preverjena avtentikacija. `user_id` iz URL-ja, JSON-a ali poljubnega headerja ni dokaz identitete.
4. `role` določi strežnik iz lokalnega računa. Skriti admin gumbi niso avtorizacija: admin API vedno preveri vlogo.
5. Lastništvo preveri pred branjem, zagonom agenta, zapisovanjem in ustavljanjem procesov. Za tuj objekt vrni `404`.
6. Admin upravlja račune; admin nima implicitne pravice branja drugih pogovorov ali workspaceov. Brez impersonacije v prvi različici.
7. Orodja agenta nimajo dostopa do auth baze, prijavnih tokenov, gesel ali admin endpointov.
8. Lokalni in zunanji provider vračata isti `CurrentUser`. Vse ostale plasti uporabljajo to identiteto in ne poznajo izvora prijave.

## 4. Predlagana arhitektura

Dodaj skupen Python paket `shared/`, ki ga vključita oba API Docker imagea. V njem naj bodo auth pogodbe, auth dependency, podatkovni dostop, uporabniške poti in pravila avtorizacije. Ne kopiraj auth logike v oba API-ja.

| Nov modul | Odgovornost |
|---|---|
| `shared/auth/models.py` | `CurrentUser`, rezultat preverjanja, auth napake |
| `shared/auth/providers.py` | Vmesnik `AuthProvider`, lokalni in bodoči zunanji adapter |
| `shared/auth/dependencies.py` | `require_user`, `require_admin` |
| `shared/auth/repository.py` | Lokalni računi, seje in povezave zunanjih identitet |
| `shared/user_paths.py` | Izračun preverjenih uporabniških poti |
| `agent_api/auth_routes.py` | Login/logout/me in HTML prijava |
| `agent_api/admin_routes.py` | Upravljanje računov |
| `agent_api/runtime_registry.py` | Runtime po `user_id`, lifecycle in zaklepi |
| `agent_api/thread_store.py` | Seje, transkripti, lastništvo in atomski zapisi |
| `agent_api/execution.py` | Pogodba za izolirano izvajanje ukazov |
| `client/auth.py` | Cookie, prijavni tok in čiščenje stanja |
| `migrations/001_users.sql` | Auth tabele in indeksi |

Loči tri dele: avtentikacijo (kdo je uporabnik), avtorizacijo (kaj sme) in izvajanje (kje agent dejansko dela). Prijave ne preverja LLM; preverja jo FastAPI pred klicem agenta.

**Omejitev izvedbe:** ohrani obstoječi `docker-compose.yml`, objavljene porte, host network, mount-e in servisne URL-je. Ne uvajaj reverse proxyja ali dodatnih servisov kot pogoja za lokalno prijavo. Spremembe aplikacijske kode, Python odvisnosti in po potrebi Dockerfile build vsebine so dovoljene; Compose topologije ne spreminjaj.

## 5. Podatkovni model

Uporabi obstoječi PostgreSQL za račune in prijavne seje, da oba API-ja vidita isto stanje in da prijava preživi ponovni zagon. Za prvo različico lahko gesla hraniš kot navaden tekst, skladno z zahtevo za interno okolje. Zapri to odločitev v lokalni provider; gesel ne vračaj v odgovorih ali logih. Ne hrani jih v workspaceu ali v repozitoriju.

```sql
CREATE TABLE app_users (
    id UUID PRIMARY KEY,
    username TEXT NOT NULL,
    password_plain TEXT,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX app_users_username_ci ON app_users (lower(username));

CREATE TABLE auth_sessions (
    guid TEXT PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES app_users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ
);
CREATE INDEX auth_sessions_user_id ON auth_sessions(user_id);

CREATE TABLE external_identities (
    provider TEXT NOT NULL,
    subject TEXT NOT NULL,
    user_id UUID NOT NULL REFERENCES app_users(id),
    PRIMARY KEY (provider, subject),
    UNIQUE (provider, user_id)
);
```

Prijavno ime obreži in normaliziraj za primerjavo; gesla ne normaliziraj. Role in aktivnost preverjaj ob vsaki zahtevi, ne samo ob izdaji tokena. Za SQL uporabljaj parametrizirane poizvedbe.

Za seje dodaj `owner_user_id` v metapodatke `ThreadInfo` oziroma interno različico tega modela. Tudi procesni metapodatki imajo `owner_user_id`. Fizična lokacija in lastnik morata biti skladna; ob neskladju zavrni dostop. Javni response ne potrebuje absolutnih diskovnih poti ali PID-jev.

## 6. Lokalna prijava in bootstrap administratorja

Bootstrap po migraciji v transakciji ustvari `admin` / `admin123`, samo če račun še ne obstaja. Uporabi UUID in vlogo `admin`. Ponovni zagon ne ponastavi gesla in ne poviša obstoječega običajnega računa z imenom `admin`; nepričakovano stanje naj jasno prekine bootstrap. Zagon več API procesov mora ostati idempotenten zaradi enoličnega indeksa in transakcije. Bootstrap izvaja en migracijski/init korak, ne vsaka zahteva.

Login sprejme username in password, preveri aktivnost ter ustvari naključen nepredvidljiv token, npr. `secrets.token_urlsafe(32)`. V `auth_sessions` shrani povezavo na uporabnika in veljavnost, privzeto 12 ur. Cookie se imenuje točno `guid`.

Cookie: `HttpOnly`, `SameSite=Lax`, `Path=/`, brez eksplicitnega `Domain` za lokalni sistem; `Secure=true` na HTTPS, za lokalni HTTP nastavljiv na false. Nikoli ne sprejmi samo uporabniškega imena ali `guid=admin` kot prijave. GUI cookie ne zapisuj v localStorage. Pri neposrednih API klicih je `guid` query parameter po spodnji pogodbi; iz access logov odstrani njegovo vrednost.

Logout prekliče trenutno auth sejo in izbriše cookie z enakimi atributi Path/Domain. Admin reset gesla in deaktivacija prekličeta vse lokalne seje ciljnega uporabnika. Omogoči več istočasnih prijav istega računa.

Za mutacije iz brskalnika uporabi CSRF token vezan na prijavno sejo ali strežniško preverjen Origin skupaj z zaščito obrazca; `SameSite` sam ni celotna implementacija. To je majhen del prijavnega toka, ne zahteva za kompleksne password hashe.

## 7. Vmesnik za prihodnjo zunanjo avtentikacijo

```python
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

@dataclass(frozen=True)
class CurrentUser:
    user_id: UUID
    username: str
    role: Literal['user', 'admin']

class AuthProvider(Protocol):
    async def resolve_guid(self, guid: str) -> CurrentUser | None:
        """None: token neveljaven; AuthUnavailable: preverjanje ni mogoče."""
        ...
```

`require_user` za vse zasebne `/v1/*` endpoint-e prebere obvezen query parameter `guid`; če manjka, je prazen ali neveljaven, vrne `401`. Cookie na teh endpointih ne nadomesti manjkajočega parametra. Browser HTML login/logout uporabljata cookie `guid`; GUI njegov token pri server-side API klicih posreduje kot query parameter. Provider preveri token in vrne interno identiteto ali zavrnitev. `require_admin` nad tem preveri `role == 'admin'`. Dependency naj se izvede pred ustvarjanjem workspacea, runtimea in procesov.

**Lokalni provider:** token poišče v `auth_sessions`, preveri preklic in potek ter prebere aktiven račun.

**Zunanji provider:** prejeti guid strežniško pošlje konfiguriranemu zunanjemu verifierju. Predlagana pogodba, ki jo je treba uskladiti s prihodnjim servisom:

```http
POST <AUTH_VERIFY_URL>
Content-Type: application/json

{"guid": "<prejeti guid>"}
```

```json
{"authenticated": true, "subject": "stable-external-user-id", "username": "janez"}
```

Verifier mora poleg `true/false` vrniti stabilno identiteto uporabnika ali ponuditi dodaten zaupanja vreden klic za identiteto. Sam odgovor »guid je veljaven« ne pove, kateremu uporabniku pripadajo podatki. Cookie se lahko menja, zato ga ni dovoljeno uporabiti kot stabilen subject.

`(provider, subject)` preslikaj prek `external_identities` v obstoječi interni UUID. Povezave naj pred prehodom vnese administrator; ne povezuj avtomatično samo po enakem username. Veljavna zunanja identiteta brez lokalnega aktivnega računa dobi `403` in navodilo, naj kontaktira administratorja. S tem ostane kreiranje računov izključno administratorsko.

Zunanji servis je avtoriteta za prijavo; lokalna baza za aktivnost in pravice v tej aplikaciji. Ob timeoutu ali neveljavnem odgovoru verifierja vrni `503` in ne dovoli dostopa. Ne preklopi samodejno na lokalna gesla. V prvi zunanji različici preverjaj vsako zahtevo brez cachea; morebitni cache kasneje mora imeti dogovorjeno kratko veljavnost in pravila preklica.

`AUTH_MODE=external` izklopi lokalni login in bootstrap gesla; `/auth/login` preusmeri na `AUTH_LOGIN_URL`, logout pa uporabi pogodbo zunanjega sistema. App ne more sama preklicati zunanje seje brez takega endpointa. Prav tako ne sme izbrisati cookieja druge domene; dogovoriti je treba Path, Domain, dostopnost cookieja in logout. Ne predpostavljaj, da bo cookie drugega spletnega mesta avtomatično prišel na domeno agenta.

## 8. HTTP pogodba

Vsi zasebni `/v1/*` endpointi obeh API-jev sprejmejo **query parameter `guid`**, ne ID-ja uporabnika. Enako velja za GET, POST, PATCH in DELETE ter multipart upload. Ne uvajaj različnih mest za token glede na HTTP metodo. Neposredni API odjemalec token pridobi z lokalnim loginom ali pozneje v zunanjem sistemu in ga priskrbi sam.

```http
GET http://<host>:8081/v1/threads?guid=<token>
POST http://<host>:8081/v1/threads/<thread-id>/messages?guid=<token>
GET http://<host>:8090/v1/files?guid=<token>&path=/uploads
DELETE http://<host>:8090/v1/files/uploads/example.txt?guid=<token>
```

`POST /v1/auth/login` je javna lokalna prijava za API odjemalce in vrne `{ "guid": "<token>", "expires_at": "...", "user": { "user_id": "...", "username": "...", "role": "user" } }`. Neposredni API odjemalec ne potrebuje cookie jar-a. HTML prijava nastavi cookie v brskalniku; v external mode lokalni login ni na voljo. API logout prekliče token iz parametra.

Query parameter omogoča zahtevano neposredno uporabo, zato poskrbi, da access/error/audit logi ne vsebujejo tokena ali celotnega query stringa z njim. Avtentikacijski odgovori naj imajo `Cache-Control: no-store`.

| Endpoint | Dostop | Namen |
|---|---|---|
| `GET /health` | Javno | Minimalni status, brez seznamov orodij ali podrobnosti uporabnikov |
| `GET /auth/login` | Javno | Lokalni HTML obrazec ali preusmeritev na zunanjo prijavo |
| `POST /v1/auth/login` | Javno, local mode | JSON login za API odjemalce, vrne guid in veljavnost, brez gesla v odgovoru |
| `POST /auth/login` | Javno, local mode | Oddaja HTML obrazca, Set-Cookie in `303` na aplikacijo |
| `GET /v1/auth/me` | Prijavljen | `user_id`, username, role, auth mode |
| `POST /v1/auth/logout` | Prijavljen | Odjava API odjemalca |
| `POST /auth/logout` | Prijavljen | Brskalniška odjava in preusmeritev |
| `GET /v1/admin/users` | Admin | Seznam računov brez gesel/tokenov |
| `POST /v1/admin/users` | Admin | Kreiranje uporabnika, `201`; username konflikt `409` |
| `PATCH /v1/admin/users/{user_id}` | Admin | Username, role, aktivnost |
| `POST /v1/admin/users/{user_id}/reset-password` | Admin, local mode | Nastavi novo geslo in prekliče seje |
| `POST /v1/admin/users/{user_id}/revoke-sessions` | Admin | Preklic lokalnih sej |
| Obstoječi `/v1/threads*` | Prijavljen | Samo lastne seje in zgodovina |
| Obstoječi `/v1/files*` v obeh API-jih | Prijavljen | Samo lastni workspace |
| Obstoječi `/v1/processes*` | Prijavljen | Samo lastni procesi in logi |
| `GET /v1/tools` | Prijavljen | Samo uporabniku dovoljena orodja, brez internih skrivnosti |

Ne dodajaj javne registracije. Običajni uporabnik na admin API dobi `403`, neprijavljeni `401`. Manjkajoča ali neveljavna prijava pri API vrne JSON `401`, ne HTML redirecta. UI ob `401` ustavi prikaz podatkov in usmeri na prijavo. Browser login uporablja redirect; API ostane predvidljiv.

Prepreči deaktivacijo ali odvzem vloge zadnjemu aktivnemu adminu v transakciji s primernim zaklepanjem. V prvi različici uporabljaj deaktivacijo namesto fizičnega brisanja računov; podatke ohrani. Opozori pri deaktivaciji lastnega računa.

## 9. Uporabniške poti in zgodovina

Predlagana trajna struktura:

```text
/data/users/<interni-user-uuid>/workspace/
/data/users/<interni-user-uuid>/workspace/.agent/home/
/data/users/<interni-user-uuid>/workspace/.agent/skills/
/data/users/<interni-user-uuid>/sessions/threads/<thread-uuid>.json
/data/users/<interni-user-uuid>/sessions/threads/<thread-uuid>.jsonl
/data/users/<interni-user-uuid>/memory/
/data/users/<interni-user-uuid>/resources/
/data/users/<interni-user-uuid>/runs/processes/<process-uuid>/
```

UUID-je parsaj z `UUID(...)` in ponovno serializiraj pred gradnjo poti. Tudi `thread_id` in `process_id` validiraj; trenutna sestava poti iz stringov brez validacije ni dovolj. Napaka formata je `422`. Username in cookie nikoli ne nastopata v diskovni poti.

`UserPaths.for_user(current_user.user_id)` naj bo edino mesto izračuna teh poti. Konfiguracijo runtimea sestavi z `dataclasses.replace` za zamrznjene dataclass modele; globalna osnovna konfiguracija ostane nespremenljiva. Katalog skills je skupen read-only izvor; kopije, uporabniški memory in home so ločeni. Uporabniški memory mora biti tudi dejansko priključen na DeepAgents memory datoteke, ne samo ustvarjena prazna mapa.

Za pogovore ohrani JSON/JSONL, da sprememba ne zahteva celotnega novega storage sistema. Zapise metadata izvajaj atomsko s temporary file + replace. Lastništvo preveri pred `invoke()`. `POST /v1/threads` je edina pot ustvarjanja nove seje; pošiljanje sporočila v neobstoječo sejo vrne `404`.

LangGraph checkpointer vedno dobi notranji ključ:

```python
checkpoint_thread_id = f"{current_user.user_id}:{validated_thread_id}"
```

Zunanji API uporablja samo običajen UUID pogovora. Vsa branja, izvozi, nadaljevanja in brisanja checkpointov uporabljajo isti ključ in predhodno avtorizacijo. Skupna PostgreSQL baza je dopustna v zaupanja vrednem backendu; izvajalnik shell ukazov nima DB dostopa.

Zamenjaj globalni `THREAD_LOCK` z zaklepi po uporabniku. Za začetek serializiraj celoten cikel invocation + transkript + metadata vseh pogovorov istega uporabnika, ker delijo workspace. Različni uporabniki lahko delajo hkrati. Ob več API workerjih `asyncio.Lock` ni dovolj: uporabi PostgreSQL advisory lock ali distribucijsko vrsto po uporabniku. Za začetno različico je dovoljen en worker, če je omejitev dokumentirana.

## 10. Meja izolacije ob ohranjeni infrastrukturi

V tej izvedbi ohrani obstoječe kontejnarje, mrežo in mount-e. Izolacijo na ravni aplikacije izvedi z uporabniškimi runtime-i, preverjenimi potmi, lastništvom sej/procesov in preverjanjem `guid` pri vsakem endpointu. Ti ukrepi veljajo tudi pri neposrednem zunanjem klicu API-ja; GUI ni varnostna meja.

Pomembna tehnična omejitev: poljuben `bash -lc` v skupnem kontejnerju lahko uporabi absolutno pot in obide Python `WorkspaceManager`. `cwd`, `HOME` in `LocalShellBackend(virtual_mode=True)` zato ne zagotavljajo, da agent nikoli ne more brati tujih podatkov. Ob ohranjeni infrastrukturi ne trdi, da uporabniške mape same predstavljajo popoln sandbox.

Za prvo izvedbo določi eksplicitno politiko: **privzeto izklopi vse neizolirano poljubno izvajanje kode**. To vključuje `/v1/processes` start, custom `run_shell` in background start ter vgrajeni DeepAgents execute in enake zmožnosti podagentov. Onemogočen endpoint lahko ostane objavljen navzven, vendar po avtentikaciji vrne `403` z jasno oznako, da izvajanje ni omogočeno. Odstranitev samo custom shell toolkita ni dovolj, če vgrajeni execute ostane aktiven. Filesystem orodja morajo uporabljati uporabniški backend, ki ne omogoča lokalnega execute.

Če je shell funkcionalnost nujna, pred ponovno vključitvijo implementiraj in preveri OS sandbox znotraj obstoječega izvedbenega okolja, brez sprememb Compose; njegova izvedljivost je odvisna od razpoložljivih kernel funkcij in trenutnih container dovoljenj. To je ločena tehnična naloga, ne obljubljena lastnost lokalne prijave. Ne spreminjaj Compose zaradi sandboxa brez nove uporabnikove zahteve. Ob omogočenem neizoliranem shellu mora dokumentacija jasno povedati, da stroga prepoved poseganja agentov v tuje workspaces ni zagotovljena.

Za datotečne API-je preveri končno pot upload datoteke, ne samo ciljne mape. V list/search/glob/copy/download operacijah ne sledi symlinkom izven dovoljenega workspacea. Prepreči tudi zamenjavo symlinka med preverjanjem in odpiranjem z no-follow oziroma descriptor-based operacijami. Zavrni brisanje workspace korena in zaščitenih runtime map.

Procesni metapodatki imajo lastnika; ID-ji so validirani UUID-ji. Logi se razrešujejo glede na `runs/processes`, ne kot workspace poti. Deaktivacija prepreči nove invokacije, prekliče prijavne seje in ustavi uporabnikovo aktivno delo po definiranem lifecycleu.

## 11. GUI in neposredni API: ločena načina prenosa tokena

Obstoječi Streamlit client ohrani svoje URL-je za agent-api in workspace-api. Oba API-ja ostaneta na trenutnih zunanjih portih. Reverse proxy ni zahtevan.

**GUI:** browser cookie `guid` je vir tokena. Streamlitovi server-side `requests` ne dobijo cookieja samodejno, `Set-Cookie` iz takega requesta pa ne nastavi browser cookieja. Zato GUI login prikaže povezavo oziroma polno navigacijo na HTML prijavo pri agent-api; brskalnik neposredno odda obrazec FastAPI-ju. Ta nastavi cookie in preusmeri na konfiguriran `APP_PUBLIC_URL`, torej obstoječi Streamlit URL. To ne zahteva spremembe Compose.

Za lokalni sistem naj bosta Streamlit in agent-api dostopna prek istega hostname, npr. `http://agent-internal:8501` in `http://agent-internal:8081`. Cookieji niso vezani na port; host-only cookie s `Path=/` je tako na voljo tudi pri ponovni Streamlit povezavi. Različna hostname-a ne delita host-only cookieja: v takem primeru je treba dogovoriti cookie domeno ali UI token bridge, ne predpostaviti samodejnega prenosa. Po login/logout izvedi polno navigacijo oziroma reload; `st.rerun()` sam ne obnovi začetnega request contexta.

V Streamlit preveri podporo `st.context.cookies` za uporabljeno verzijo `streamlit==1.49.1`. Token trenutnega browser contexta posreduj v vseh API helperjih kot `params={'guid': guid, ...}`. Združi ga z obstoječimi parametri `path`, `recursive`, `force` itd.; noben klic ga ne sme izgubiti. Pri uploadu je token še vedno query parameter, datoteka in destination pa ostaneta multipart. Cookieja ne posreduj kot nadomestno avtentikacijo API-ja.

**Neposredni API:** odjemalec uporabi JSON login in dobi token ali ga priskrbi iz zunanjega sistema. Vsak zasebni request vsebuje `?guid=<token>`. Query token vedno preveri backend; njegovo ročno posredovanje ne pomeni, da je uporabnik sam izbral identiteto ali obseg podatkov.

Na začetku GUI renderja pokliči `/v1/auth/me?guid=...`. Če token manjka ali je neveljaven, ne prikazuj zasebnih vsebin in ponudi prijavo. Po menjavi user ID počisti thread selection, messages, browse path, upload in uporabniške cachee. Ne uporabljaj globalnega cookie jar-a ali globalnega tokena med Streamlit uporabniki.

Admin zaslon vsebuje seznam, dodajanje, aktivnost, vloge in lokalni reset gesla. Navadni uporabnik ga ne vidi; backend vsak admin request neodvisno preveri. V external mode lokalna password polja niso na voljo. HTML logout uporablja cookie in zaščito browser obrazca, prekliče prijavo, izbriše cookie in vrne uporabnika v GUI.

## 12. MCP, spomin in drugi stranski kanali

Pregledani runtime uporablja skupen Bifrost MCP API ključ. To ne zagotavlja uporabniške izolacije zunanjih orodij. V prvi različici izklopi MCP orodja, ki lahko berejo/zapisujejo skupne datoteke, pogovore ali druga zasebna sredstva. Ob kasnejši vključitvi mora orodje dobiti strežniško potrjen uporabniški obseg, ki ga ciljna storitev dejansko uveljavlja. Parametra `user_id`, ki ga lahko izbere model, ne štej kot zaščito.

Preglej tudi podagente, exports, attachments, download linke, vektorske zbirke in dolgoročni memory. Vsak zaseben zapis mora imeti isti user scope. Skupni skills in programska koda so dovoljen read-only vir; zasebne vsebine ne smejo postati skupni seed. Auth/admin funkcij ne registriraj kot orodij agenta.

## 13. Konfiguracija in zagon

Predlagane nove nastavitve:

```dotenv
AUTH_MODE=local
AUTH_COOKIE_NAME=guid
AUTH_SESSION_TTL_SECONDS=43200
AUTH_COOKIE_SECURE=false
AUTH_BOOTSTRAP_ADMIN_USERNAME=admin
AUTH_BOOTSTRAP_ADMIN_PASSWORD=admin123
USER_DATA_ROOT=/data/users
APP_PUBLIC_URL=http://localhost:8501
# Pri prehodu na zunanjo prijavo:
# AUTH_MODE=external
# AUTH_VERIFY_URL=https://auth.example/verify
# AUTH_LOGIN_URL=https://auth.example/login
# AUTH_EXTERNAL_PROVIDER=company-sso
# AUTH_VERIFY_TIMEOUT_SECONDS=5
```

`APP_PUBLIC_URL` naj kaže na obstoječi Streamlit URL; reverse proxy ni zahtevan. Redirect target naj bo fiksen ali preverjena relativna pot, ne poljuben URL iz requesta.

Oba API-ja potrebujeta isti auth repository. Dodaj `shared/` v Dockerfile obeh API-jev ter potrebne Python knjižnice, npr. DB driver v workspace API in form parser za login. To ne zahteva spremembe Compose topologije. Ohraniti je treba trenutne mount-e, porte, servisne URL-je in host network. API-ja ostaneta neposredno dostopna navzven in vsak sam preverja guid.

Povezavo workspace-api na obstoječi PostgreSQL konfiguriraj skladno z njegovo trenutno mrežo, povezavo agent-api pa skladno z obstoječim host network. Ne prepisuj delujoče povezave agent-api samo zato, da bi servisa imela identičen hostname baze. Nova konfiguracija naj bo v obstoječi `.env` oziroma aplikacijskih nastavitvah.

`APP_PUBLIC_URL` je dejanski obstoječi Streamlit naslov; HTML login/logout preusmerjata nanj. GUI auth URL naj bo browser-dostopen naslov agent-api, ne Docker servisno ime, ki ga browser ne pozna. Pri zunanji prijavi uskladi domeno cookieja z GUI gostiteljem. CORS ni potreben za server-side Streamlit requests; če dodaš browser API odjemalca, uporabi konkretne dovoljene origine.

## 14. Migracija obstoječih podatkov

1. Ustavi nove invokacije in procese ter naredi backup podatkovnih map in PostgreSQL checkpointov.
2. Inicializiraj uporabniški model in admin račun. Obstoječi podatki nimajo lastnika, zato zahtevaj eksplicitno odločitev operaterja, kateremu uporabniku pripadajo.
3. Stari skupni workspace, session, memory, resources in runs kopiraj v izbrane uporabniške poti. Nikoli jih ne prikazuj vsem novim uporabnikom.
4. Metapodatkom dodaj lastnika; preveri UUID-je, poškodovane datoteke, absolutne log poti in symlinke. Starih PID-jev ne obravnavaj kot veljavnih novih procesnih ročajev.
5. Checkpointe prenesi iz starega `thread_id` na `user_id:thread_id` z namenskim postopkom, preverjenim na dejanski shemi nameščenega saverja. Ohraniti je treba checkpoint writes in reference; preimenovanje ene kolone na slepo ni migracija.
6. Če prenosa checkpointov še ne podpreš, stare transkripte ohrani read-only in odpri nove pogovore; UI naj jasno pove, da stari pogovor ni nadaljevan z istim modelnim stanjem.
7. Preveri dostop z dvema računoma in šele nato odstrani stare aktivne poti. Backup ohrani za rollback.

Prehod na zunanjo prijavo: operater poveže stabilne external subjecte na obstoječe UUID-je, preveri cookie domeno ter pogodbo login/logout, nato nastavi `AUTH_MODE=external`. Lokalni workspacei in checkpoint ključi se ne premikajo. Ne ustvarjaj novih UUID-jev samo zaradi novega auth providerja.

## 15. Vrstni red implementacije

1. Migracije, auth modeli, local provider, idempotenten bootstrap in auth testi brez modelnih klicev.
2. Auth dependency na vseh zasebnih endpointih obeh API-jev, admin backend in HTML login/logout.
3. `UserPaths`, thread store, lastništvo, uporabniški runtime registry in checkpoint ključi.
4. Uporabniški filesystem backend, privzeto onemogočeno neizolirano execute/shell/process start izvajanje in zaprte MCP stranske poti. Shell ponovno omogoči šele po preverjeni izvedbeni izolaciji.
5. HTML browser login na obstoječem agent-api naslovu, Streamlit cookie branje in posredovanje guid kot query parametra, reset UI stanja in admin zaslon.
6. Migracija obstoječih podatkov, celovit test dveh uporabnikov in dokumentiran zagon.
7. Mock external provider in test preklopa, brez dejanskega zunanjega servisa.

Za vsako fazo ohrani obstoječe teste. Končna funkcionalnost ni zaključena pred izolacijo izvrševanja in preverjanjem obeh API-jev.

## 16. Sprejemni testi

| Test | Pričakovan rezultat |
|---|---|
| Prvi in ponovni zagon | `admin/admin123` deluje prvič; poznejši restart ne ponastavi spremenjenega gesla |
| Napačno geslo, potekel/preklican/neznan guid | `401`, brez runtimea, datotek in modelnega klica |
| Uporabnik kliče create/list/reset admin API neposredno | `403`; v UI nima admin zaslona |
| Admin ustvari A in B | Računa in UUID-ja različna; začetni workspacei brez tujih podatkov |
| A in B ustvarita seje in datoteko istega imena | Vsak vidi samo svoje vsebine |
| B pozna A-jev thread UUID | GET/POST messages vrneta `404`; agent se ne zažene |
| B pozna A-jev process UUID | Get/output/stop vrnejo `404`; proces A ostane nespremenjen |
| ID `../...`, encoded traversal, neveljaven UUID | Validacijska napaka; nobeno branje/zapis izven obsega |
| Symlink na tujo ali auth datoteko | Read/list/search/upload/copy/download ne razkrijejo oziroma spremenijo cilja |
| Shell uporabi absolutno pot, Python ali `../` | Ne more brati, zapisati ali brisati workspacea B oziroma auth baze |
| Vgrajeni execute in podagent poskusita isti dostop | Ista izolacija kot custom run_shell |
| Shell poskusi DB, notranji API ali executor B po omrežju | Dostop preprečen tudi brez Python path helperja |
| Hkratna zahteva A in B | Konfiguracija, tool context, logs in checkpointi se ne pomešajo |
| Dva pogovora istega A | Uporabljata A-jev workspace, checkpointa ostaneta ločena |
| Logout A, nato login B v istem browserju | Cookie zamenjan; noben prikaz/cache/prejšnji izbrani thread ne ostane od A |
| Dva brskalnika z različnima uporabnikoma | Cookie forwarding uporablja pravilno identiteto pri vseh klicih obeh API-jev |
| Neposreden klic kateregakoli zasebnega API-ja brez parametra guid | `401`, tudi če request vsebuje cookie |
| API klic z veljavnim parametrom guid brez cookieja | Deluje v obeh API-jih, samo za lastne podatke |
| API login | Vrne guid, ki ga odjemalec lahko uporablja brez cookie jar-a |
| Compose primerjava pred/po implementaciji | Topologija, objavljeni porti in dostopnost obeh API-jev nespremenjeni |
| Deaktivacija A med delom | Novi dostopi zavrnjeni, seje preklicane, delo in procesi ustavljeni po dogovorjenem lifecycleu |
| Poskus odvzema zadnjega admina | Zavrnjeno tudi ob dveh hkratnih admin zahtevah |
| Restart | Lastne seje/datoteke ostanejo; auth stanje je konsistentno |
| Mock external provider, isti subject in nov guid | Isti interni UUID, isti workspace in zgodovina |
| External verifier timeout | `503`, brez lokalnega fallbacka in brez dovoljenega agentovega dela |
| Veljaven neprovisioniran external subject | `403`, brez samodejnega kreiranja računa |

Dodaj enotske teste auth providerja in poti, integracijske teste obeh FastAPI aplikacij ter izvedbene teste dejanskega sandboxa. Mock subprocess testi ne dokazujejo OS izolacije. UI cookie tok preveri z brskalnikom. Teste poljubnega shell izvajanja iz matrike izvajaj samo, če je preverjen sandbox omogočen; privzeto preveri, da so vse neizolirane izvedbene poti izklopljene, tudi vgrajeni execute. Za API/integracijske teste uporabi fake runtime in fake model, da testi ne potrebujejo zunanjih LLM servisov.

## 17. Dodatne koristne funkcije

Vključi preprost administratorski audit: kdo je ustvaril/deaktiviral račun, spremenil vlogo ali resetiral geslo, kdaj in za kateri user ID. Ne beleži gesel, tokenov ali vsebine pogovorov. Dodaj nastavitev kvote workspacea in največjega števila aktivnih procesov na uporabnika, da sodelavci drug drugemu ne zapolnijo diska ali izvajalnega okolja. Za prvo različico je dovolj ročno nastavljena skupna privzeta kvota.

## 18. Besedilo naloge za programerskega agenta

> V repozitoriju agent_v6_deep implementiraj to specifikacijo. Ohrani obstoječi docker-compose.yml, topologijo in navzven dostopna oba API-ja. Lokalna avtentikacija naj uporablja zamenljiv AuthProvider: GUI ima browser cookie guid, vsi zasebni API endpointi pa sprejmejo obvezen query parameter guid. API login vrne guid v JSON, da ga neposredni odjemalec priskrbi sam. Ob prvi inicializaciji ustvari admin/admin123; samo admin upravlja račune. Vsak uporabnik ima stabilen UUID, lastne seje, zgodovino, workspace, memory, checkpoint namespace in procese. Zaščiti agent-api in workspace-api, preverjaj lastništvo pred vsakim posegom ter vrni 404 za tuje objekte. Admin nima samodejnega dostopa do tujih podatkov. Vse poti in tool contexte določa strežnik iz potrjene identitete. Streamlit mora dobiti dejanski browser cookie in njegovo vrednost posredovati kot query parameter guid pri server-side requests; uporabi browser HTML login na obstoječem agent-api naslovu in polno navigacijo po spremembi prijave, brez zahteve za reverse proxy. Brez preverjenega sandboxa privzeto onemogoči poljubno shell izvajanje, vključno z DeepAgents vgrajenim execute in podagenti; cwd in ločene mape niso zadostna izolacija. Za ponovno omogočanje shell funkcij ne spreminjaj Compose brez nove uporabnikove zahteve. Ohraniti je treba obstoječe funkcije z navedeno omejitvijo neizoliranega izvajanja in dodati teste iz sprejemne matrike. Dodaj migracijo starih podatkov, konfiguracijo in navodila za zagon. Bodoči external provider preveri guid pri zunanjem servisu in stabilni subject preslika v obstoječi lokalni UUID; uporabi mock za test, ker dejanska pogodba zunanjega servisa še ni določena. Ne izvajaj samodejnega zunanjega klica v local mode in ne uvajaj javne registracije. Za password hashing v tej interni lokalni različici ni zahteve.
