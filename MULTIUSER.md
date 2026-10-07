# Večuporabniški zagon

V `.env` nastavite `AUTH_MODE=local` in po potrebi `APP_PUBLIC_URL` na naslov Streamlit aplikacije. Prijavni obrazec je v Streamlit GUI na portu 8501. GUI pošlje poverilnice neposredno API-ju po notranji Docker povezavi in hrani prijavo v svoji seji. Osvežitev strani ustvari novo Streamlit sejo, zato je lahko potrebna ponovna prijava.

Za uporabo GUI-ja v GitHub Codespaces je dovolj odpreti port 8501. Port 8081 ostaja potreben samo za neposreden brskalniški ali API dostop. Neposredna prijava na `/auth/login` še vedno podpira cookie in enkratno kodo za prehod na GUI; za pravilen Codespaces `Origin` mora biti vsebniku `agent-api` podana spremenljivka `CODESPACE_NAME` (Compose jo prevzame iz okolja).

Zaženite `docker compose up -d --build`. Ob prvem zagonu se v PostgreSQL ustvari račun `admin` z geslom `admin123`. Geslo takoj spremenite v skrbniškem vmesniku. Ponovni zagon gesla ne ponastavi. Za prijavo odprite Streamlit na `APP_PUBLIC_URL` ali na posredovanem portu 8501.

Neposredni API odjemalec pokliče `POST /v1/auth/login` z `{"username":"admin","password":"admin123"}` in dobljeni `guid` vključi v query parameter pri vsakem zasebnem klicu obeh API-jev. Uvicorn access log je izključen, ker bi sicer beležil token v URL-ju. Izogibajte se posredniškim strežnikom, ki beležijo query string.

Vsak račun ima trajne podatke v `USER_DATA_ROOT/<user_id>/`. Privzeta kvota workspacea je 1 GiB (`WORKSPACE_QUOTA_BYTES`). Shell, procesni zagon, vgrajeni DeepAgents `execute` in MCP orodja so izključeni. Agent uporablja `FilesystemBackend`, ki podpira datotečna orodja brez izvajanja ukazov. En agent-api worker serializira invokacije posameznega uporabnika; več workerjev zahteva PostgreSQL advisory lock za isti uporabniški cikel.

## Obstoječi podatki

Pred migracijo ustavite agent-api, naredite backup `data/` in PostgreSQL ter izberite lastnika starih skupnih podatkov. Skript `scripts/migrate_legacy_data.py --user-id <UUID> --legacy-root data` pokaže nameravane poti. Po pregledu dodajte `--apply`. Skript zavrne symlinke in prepis neprazne ciljne mape. Stare transkripte in loge arhivira, ne prikazuje kot aktivne pogovore. Starih LangGraph checkpointov ne preseli; za nadaljevanje teh pogovorov je potreben ločen prenos, preverjen na konkretni shemi nameščenega saverja.

## Zunanja prijava

`AUTH_MODE=external` izključi lokalni login in zahteva `AUTH_VERIFY_URL`, `AUTH_LOGIN_URL`, `AUTH_LOGOUT_URL` ter `AUTH_EXTERNAL_PROVIDER`. Verifier mora vrniti stabilen `subject`; administrator predhodno vnese preslikavo v `external_identities`. Enako uporabniško mapo ohrani interni UUID. Ob napaki verifierja API vrne `503`, ob neznani identiteti `403`.

Če lokalni Docker bridge ne omogoča povezave `workspace-api` do imena `postgres`, nastavite `AUTH_DATABASE_URL` v lokalnem `.env` na naslov obstoječega PostgreSQL porta, ki je dosegljiv iz obeh API vsebnikov. To je samo nastavitev povezave; topologije Compose ne spreminja. Privzeti `DATABASE_URL` ostane namenjen konfiguraciji checkpointov agenta.
