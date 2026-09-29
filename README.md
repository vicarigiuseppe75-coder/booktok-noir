# BookTok Noir

Generatore a pagamento di poster PNG, clip verticali MP4 e didascalie BookTok. Gli esempi pubblici sono già pronti. Solo gli account registrati con crediti possono generare; l'account proprietario è gratuito.

## Attivazione

1. Crea un progetto Supabase. In **SQL Editor** esegui tutto `database.sql`. In Authentication abilita Email e la conferma email. Copia Project URL e la chiave `anon`/publishable e `service_role`/secret dalle impostazioni API.
2. Apri un account Stripe e recupera la **secret key** (usa prima quella di test). Non serve creare un prodotto: l'app crea Checkout a 2,99 € per 5 crediti. Verifica che l'account Stripe possa ricevere pagamenti prima di usare la chiave live.
3. Carica questa cartella come repository GitHub. Su Streamlit Community Cloud scegli repository, branch e `app.py`. Nelle impostazioni avanzate, aggiungi questi **Secrets** (mai su GitHub):

```toml
SUPABASE_URL = "https://TUO-PROGETTO.supabase.co"
SUPABASE_ANON_KEY = "..."
SUPABASE_SERVICE_KEY = "..."
STRIPE_SECRET_KEY = "sk_test_..."
APP_URL = "https://TUO-NOME.streamlit.app"
OWNER_EMAIL = "tua-email@example.com"
```

4. Nel codice, verifica `BOOK_URL` (edizione italiana del primo libro). Dopo il deploy, sostituisci `APP_URL` con il vero URL pubblico e riavvia l'app. Registrati con `OWNER_EMAIL`, conferma l'email e accedi. Solo quell'identità verificata salta i crediti.
5. Esegui un acquisto di prova con Stripe in modalità test, torna dal Checkout e controlla che compaiano 5 crediti. Passa a `sk_live_...` solo dopo la verifica dei dati commerciali e del funzionamento. Effettua un acquisto reale controllato prima di condividere il link.

## Avvio locale

```bash
python -m pip install -r requirements.txt
mkdir -p .streamlit
# Crea .streamlit/secrets.toml con le chiavi qui sopra (file ignorato da Git).
streamlit run app.py
```

## Note operative

- Il pagamento è con Stripe Checkout. L'app recupera e verifica la sessione Stripe al ritorno e concede crediti una sola volta tramite vincolo univoco nel database. Se il cliente chiude la pagina prima del ritorno, occorre recuperare la sessione Checkout (`cs_...`) dalla dashboard Stripe e inserirla nell'app con lo stesso account. Per automatizzare anche questo caso, aggiungi in futuro un webhook su un endpoint esterno.
- Il progetto Streamlit è ospitabile gratis, ma Stripe applica commissioni e i piani gratuiti dei servizi terzi hanno limiti. Nessuna promessa di guadagni o di hosting gratuito illimitato.
- Il video è un'animazione tipografica originale di quattro secondi, senza musica. L'utente può aggiungere un brano autorizzato dentro TikTok. Il generatore non usa IA generativa né fotografie stock.
- Un credito viene scalato dopo che PNG e MP4 sono stati creati. Se la connessione cade dopo l'addebito, il download potrebbe andare perso: per una versione commerciale più robusta servono un archivio privato dei file e una cronologia degli ordini.
- Proteggi le chiavi nella sezione Secrets; Supabase service key e Stripe secret key non devono essere scritte nel repository. Per assistenza sui pagamenti, confronta l'ID della sessione Checkout nella dashboard Stripe.
