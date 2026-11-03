# Audit dei workflow GitHub di CurveMole

Data: **3 novembre 2026**. Branch di lavoro: **`testing`**.
Base esaminata: `bb3c2842db97799c3f23375760be7d83361ee3dc`.

## 1. Ambito e criterio dell'analisi

Sono stati esaminati tutti i **14 workflow** presenti in `.github/workflows`,
gli script collegati in `.github/scripts`, i test della pipeline, il packaging
e le istruzioni operative di `AGENTS.md` e `docs/releasing.md`.
L'analisi comprende eventi, condizioni, dipendenze fra job e workflow riutilizzabili,
permessi, concorrenza, identità del sorgente, trasferimento degli artifact,
pubblicazione dei pacchetti, documentazione, sito e sincronizzazione DOI.

I problemi descritti sono dedotti da percorsi effettivamente presenti nel codice;
quando dipendono da una particolare combinazione di eventi o dalla dimensione del
catalogo, viene indicata la condizione necessaria. Non rappresentano una lista di
incidenti osservati nei log remoti: questa revisione non ha consultato la cronologia
completa delle esecuzioni GitHub né misurato i minuti fatturati.

La revisione e le correzioni sono state svolte localmente su `testing`, senza
eseguire promozioni, deploy, creazioni di release o modifiche a `main`.
La successiva pubblicazione delle correzioni su `testing` è stata autorizzata
separatamente dall'utente, con `[skip release]` per evitare una nuova beta.
Versioni sorgenti stabili,
metadati di citazione e blocchi automatici del changelog sono stati preservati.
I comportamenti che GitHub carica dal branch predefinito, come `workflow_run` e
schedule, diventeranno operativi quando i relativi file raggiungeranno `main`
attraverso una pubblicazione autorizzata.

## 2. Mappa completa dei workflow

| File | Compito | Esito della revisione |
| --- | --- | --- |
| `ci.yml` | Pianifica i controlli delle PR e dei push su `main` | Cancella le PR superate; conserva le esecuzioni su main; evita una seconda pipeline plugin durante una release. |
| `validate.yml` | Lint, actionlint e matrice di test Python/OS | Mantenuto: i controlli esistenti restano necessari e i casi di promozione hanno già un'identità di concorrenza distinta. |
| `testing.yml` | Valida, documenta, costruisce e pubblica beta | Manuale condiviso con i pacchetti; scritture coordinate; timeout e cancellazione espliciti; backfill DOI più leggero. |
| `automatic-release.yml` | Prepara e pubblica una versione stabile | Coda stabile comune, permessi per job, richiamo esplicito dei plugin e lock per il ritorno dei metadati su testing. |
| `promote-testing.yml` | Valida e promuove lo snapshot scelto esplicitamente | Conservata la protezione dell'ancestry e aggiunti timeout ai job di snapshot/promozione. |
| `build-desktop.yml` | Genera icone, wheel/sdist e pacchetti desktop | Snapshot unico, documentazione beta coerente, cache uv, permessi ridotti e output Linux anche per build manuali senza tag. |
| `documentation.yml` | Costruisce il manuale e le eventuali immagini GUI | Mantenuto; il planner lo richiama solo per input pertinenti. Il suo commit controlla ancora che il sorgente sia corrente. |
| `screenshots.yml` | Ingresso manuale per aggiornare le immagini GUI | Mantenuto come scorciatoia: delega alla costruzione unica del manuale. |
| `website.yml` | Verifica i prerequisiti, renderizza e pubblica Pages | Escluse le notifiche originate da PR; mantenuti i gate su release, DOI e sorgente; ricerca release paginata. |
| `website-screenshots.yml` | Ingresso manuale per rigenerare il sito | Mantenuto: richiede il percorso completo Pages, senza una seconda implementazione del rendering. |
| `community-plugins.yml` | Valida plugin su tre OS e pubblica il catalogo | Supporta la chiamata dalla pipeline stabile; include il fingerprint nei controlli sulle modifiche concorrenti. |
| `sync-zenodo-doi.yml` | Ricerca DOI stabili/beta, aggiorna citazioni e richiede Pages | Separata la scrittura su testing; discovery stabile paginata e backfill beta a un solo tentativo. |
| `repair-release-manual.yml` | Ripristina il manuale originale di una release | Mantenuto: usa lo strumento corrente sul contenuto storico e condivide il lock del packaging del tag. |
| `test-linux-candidate.yml` | Produce un AppImage diagnostico per prove | Mantenuto: ha uno scopo distinto dalla pubblicazione stabile, resta cancellabile quando superato. |

## 3. Problemi riscontrati e correzioni

### 3.1 Pipeline stabili concorrenti su branch diversi — priorità alta

**Prima.** `automatic-release.yml` usava
`release-pipeline-${{ github.ref }}`. Una release su `main` e una promozione manuale
da `testing` appartenevano quindi a due gruppi diversi, pur leggendo e aggiornando
lo stesso stato stabile: branch main, scelta della versione e tag.

**Conseguenza.** Le fasi di preparazione potevano sovrapporsi. Il lock
`curvemole-main-write` proteggeva il singolo job di scrittura e gli script
rifiutavano sorgenti superati, ma una delle due pipeline poteva fallire dopo aver
consumato runner e preparato documentazione. Non era una protezione dell'intera
operazione di release.

**Correzione.** Tutte le release stabili usano il gruppo `release-pipeline`, con
`cancel-in-progress: false` e `queue: max`. Restano anche i controlli Git contro
avanzamenti esterni e il lock dei writer di main. La coda non implica ordinamento
assoluto o capacità infinita: GitHub ne documenta i limiti.

### 3.2 Writer di testing privi di un lock comune — priorità alta

**Prima.** Il changelog delle beta, il ritorno dei metadati dopo il rilascio e
la sincronizzazione successiva del DOI potevano scrivere su `testing` senza
coordinarsi fra workflow. Serializzare i soli Testing builds non copriva gli
altri due percorsi.

**Conseguenza.** Due job potevano partire dallo stesso HEAD e preparare commit
diversi. I push normali impedivano la perdita di storia, ma il secondo poteva
fallire per non-fast-forward. Il problema era di affidabilità della pipeline,
non una dimostrazione di sovrascrittura silenziosa.

**Correzione.** I tre writer condividono `curvemole-testing-write`, senza
cancellazione e con coda massima. Nel workflow DOI, la sincronizzazione di testing
è ora un job separato che riceve lo SHA prodotto da `apply`: il lock di main viene
rilasciato prima di acquisire quello di testing. I controlli Git restano necessari
perché i push umani non partecipano ai lock di Actions.

### 3.3 Ricostruzione del manuale per qualsiasi push umano — priorità media

**Prima.** Il planner impostava `documentation=true` per qualsiasi push umano
che non generasse una release. La presenza di `push` nella condizione rendeva
ininfluente il filtro sugli input del manuale.

**Conseguenza.** Anche una correzione del solo README, di CSS del sito o di un
plugin avviava installazione di TeX/Pandoc, compilazione PDF e upload del manuale.
Un cambiamento del solo fitting con `[skip release]` aggiungeva il manuale ai
controlli e all'AppImage diagnostico pur non modificandone gli input.

**Correzione.** La costruzione viene richiesta per input pertinenti del manuale
o per screenshot GUI da aggiornare. I test del planner coprono casi positivi e
negativi: README/plugin isolati non richiedono documentazione; manuale e GUI sì.

### 3.4 Generazione screenshot GUI non verificata sulle PR — priorità media

**Prima.** `screenshots` dipendeva dall'essere un push. Una PR che modificava
la sola GUI non verificava il generatore di screenshot e la successiva
compilazione del manuale; l'eventuale errore poteva emergere più tardi.
Inoltre lo script di installazione del toolchain documentale non era fra gli
input che richiedevano il job documentazione.

**Correzione.** Le modifiche GUI pertinenti richiedono screenshot e manuale
anche su PR, con artifact di verifica. Lo script
`install_document_toolchain.sh` attiva il controllo documentale.
È un aumento intenzionale dei controlli sulle PR GUI, compensato dalla rimozione
delle compilazioni per modifiche estranee al manuale.

### 3.5 Manuale beta scaricabile diverso da quello incorporato — priorità alta

**Prima.** `documents` ricompilava il Markdown corrente in un artifact separato,
mentre `packages` partiva in parallelo e utilizzava i PDF/TeX presenti nel commit.
Quei file potevano precedere il testo corrente. Il manifest della release poteva
essere corretto pur distribuendo una documentazione offline diversa.

**Correzione.** Il packaging beta attende `documents`. Wheel/sdist, Linux,
Windows e macOS scaricano tutti `release-documentation` e installano gli stessi
quattro documenti prima della build. Il comando `install-documents` legge e
valida tutti gli input prima di scrivere: PDF riconoscibile, testo UTF-8 e file
non vuoti. Non cambia CITATION, README o versione del manuale. Le copie vengono
aggiornate soltanto nei checkout temporanei dei job di packaging.

**Compromesso.** La compilazione del manuale entra nel percorso critico prima
dei pacchetti. Il tempo totale può crescere rispetto all'esecuzione parallela,
ma viene eliminata l'incoerenza fra due download della stessa beta e una build
documentale fallita ferma i pacchetti prima di consumare i runner desktop.

### 3.6 Verifica upload beta limitata alla prima pagina — priorità alta

**Prima.** `beta_release.py` cercava il draft appena caricato soltanto nei primi
100 elementi restituiti dall'API. In particolare, riprendere una vecchia beta
dopo molte release più recenti poteva non trovare il draft e fallire prima della
pubblicazione, anche se upload e checksum erano corretti.

**Correzione.** La lettura usa `gh api --paginate --slurp`. Il test simula una
pagina intera di release estranee prima della release cercata e verifica che un
digest errato blocchi comunque la pubblicazione.

### 3.7 Beta frequenti che nascondono le release stabili al discovery DOI — priorità alta

**Prima.** La ricerca periodica dei DOI stabili leggeva soltanto 20 release
e poi scartava le prerelease. Con abbastanza beta recenti, l'insieme delle stabili
da elaborare diventava vuoto anche con DOI stabili ancora da sincronizzare.

**Correzione.** La ricerca procede per pagine da 100 finché trova fino a dieci
release finali pertinenti o raggiunge la fine del catalogo. Il limite operativo
alle dieci stabili recenti resta; una versione esplicita permette di recuperare
una stabile più vecchia. Il test copre una pagina composta interamente da beta.

### 3.8 Stesso limite di pagina nel gate del sito — priorità alta

**Prima.** `website_release.py` cercava la versione stabile corrente soltanto
nella prima pagina di 100 release. Oltre quella soglia il sito poteva rimanere
bloccato con un messaggio di attesa pur avendo già pacchetti e DOI corretti.

**Correzione.** La ricerca prosegue finché trova il tag richiesto o finisce il
catalogo. I test mantengono il controllo del DOI e coprono la stabile nella
seconda pagina, sia quando è pronta sia quando deve ancora attendere il DOI.

### 3.9 Backfill DOI beta ripetitivo — priorità media

**Prima.** Ogni backfill rileggeva Zenodo anche per beta già completate e poteva
ripetere dieci volte la scansione degli archivi mancanti. Il job deteneva nel
frattempo `zenodo-beta-releases`, ritardando sincronizzazioni più recenti.

**Correzione.** Il backfill globale esclude le note che hanno già una riga DOI
versionata riconoscibile. Le invocazioni periodiche o dovute a `[skip release]`
fanno un tentativo; nuove beta e richieste manuali di una versione mantengono
fino a dieci tentativi. La versione esplicita ricontrolla comunque Zenodo e può
correggere un DOI errato: il backfill tratta invece la riga già presente come
completata. Restano i controlli sull'esatta versione e sul tag del repository.

### 3.10 Pubblicazione plugin non collegata alla promozione — priorità alta

**Prima.** La promozione scriveva main con `GITHUB_TOKEN`. Quel push non avvia una
nuova CI su push; `community-plugins.yml` non ha un trigger push autonomo.
Il catalogo poteva quindi restare precedente alla versione stabile appena
promossa. Anche il normale percorso release non richiamava esplicitamente questo
workflow dopo la preparazione della versione.

**Correzione.** Dopo il successo dei pacchetti stabili, Automatic release richiama
il workflow plugin sul commit stabile preparato, con `publish_stable: true`.
L'opzione esiste soltanto per le chiamate riutilizzabili; l'ingresso manuale dei
plugin su testing non acquisisce una nuova opzione di pubblicazione stabile.
La validazione resta su tre OS, senza token di scrittura o credenziali Git
persistenti per il codice dei plugin; il writer pubblico resta un job distinto.

### 3.11 Doppio percorso plugin e filtro fingerprint incompleto — priorità media

**Prima.** CI poteva avviare i plugin mentre delegava una release. Collegare
anche la pipeline stabile senza cambiare CI avrebbe raddoppiato il lavoro.
Inoltre una modifica a `plugin_fingerprint.py` non era elencata né dal planner
plugin né dal controllo che rifiuta una pubblicazione divenuta obsoleta.

**Correzione.** Quando CI delega una release, lascia i plugin alla pipeline
stabile. Negli altri casi conserva il controllo selettivo. Il file fingerprint
è stato aggiunto a entrambi i filtri: una sua modifica richiede validazione e
impedisce di pubblicare un catalogo precedente quando main è avanzato.

### 3.12 Permessi di scrittura estesi ai job di sola costruzione — priorità media

**Prima.** Automatic release assegnava globalmente contents/actions/OIDC/
attestations in scrittura; Build desktop assegnava globalmente contents/OIDC/
attestations. Anche preparazione del manuale, icone e distribuzioni Python
ereditavano privilegi non necessari.

**Correzione.** Il default dei due workflow è `contents: read`. I singoli job
ricevono ciò che usano: commit/tag/pubblicazione contents write, richiesta DOI
actions write, AppImage id-token e attestations write. Il preflight conserva
contents write per poter consultare correttamente i draft autenticati.
I permessi dei chiamanti continuano a permettere le capacità necessarie ai
workflow annidati; non vengono passati segreti alla validazione plugin.

### 3.13 Ref mobile riletto da piattaforme diverse — priorità alta

**Prima.** I checkout dei pacchetti usavano separatamente `inputs.source_ref`
oppure `github.ref`. In una build manuale di un branch, un push fra l'avvio
dei job poteva far costruire versioni del sorgente diverse sulle piattaforme.

**Correzione.** Il preflight risolve il riferimento una volta, pubblica
`source_sha` e tutti i job che costruiscono icone e pacchetti usano quel commit.
Il default diventa `github.sha`, che identifica lo snapshot del lancio.
La beta continua a ricevere lo SHA testato dal chiamante.
I checkout aggiuntivi degli strumenti correnti per macOS e per la finalizzazione
storica restano intenzionali: non sono copie ridondanti dello stesso compito.

### 3.14 Branch che iniziano per v e risultato Linux manuale perso — priorità media

**Prima.** Qualsiasi `source_ref` che iniziasse per `v` entrava nel preflight
delle release, anche un branch come `validation`. Viceversa, in una build
manuale senza tag e senza beta, Linux non caricava né artifact né asset: il
pacchetto costruito andava perso alla fine del runner.

**Correzione.** Soltanto un input esatto `vMAJOR.MINOR.PATCH` entra nel percorso
stabile. Il preflight espone il flag `release`; upload Linux e finalizzazione
usano quel flag. Le build senza tag, manuali o beta, conservano l'AppImage e la
firma come artifact. Gli AppImage stabili continuano a essere caricati
direttamente nel draft, senza una copia Actions superflua.

### 3.15 Notifiche Pages originate anche da PR — priorità media

**Prima.** Il job Pages controllava successo e repository della CI precedente,
ma non il tipo di evento. Una PR con branch sorgente `main` dello stesso
repository poteva soddisfare i filtri di `workflow_run`. In quel contesto
`github.ref` si riferisce al branch predefinito del workflow ricevente: il suo
controllo su main non dimostrava che la CI precedente fosse un push main.

**Conseguenza.** Poteva partire un tentativo di pubblicazione non richiesto dalla
PR. Il checkout rimaneva main e i gate di readiness restavano attivi: il codice
della PR non veniva direttamente distribuito da questo percorso.

**Correzione.** Il ricevente accetta notifiche automatiche da CI su push main
oppure da Automatic release manuale riuscito. Restano il controllo del
repository, il successo, il gate sullo snapshot validato e la verifica di
release/DOI. Il normale workflow CI di una PR non può richiedere il deploy.

### 3.16 Job senza timeout esplicito e cancellazioni incomplete — priorità media

**Prima.** Planner beta, publisher beta, changelog, snapshot/promozione e sync
finale non avevano tutti un timeout locale esplicito. Inoltre `always()` da solo
poteva mantenere attivi changelog o discovery DOI dopo l'annullamento della run.
Le PR aggiornate potevano lasciare in esecuzione job accessori di vecchie revisioni.

**Correzione.** Tutti i job con runner hanno ora un timeout esplicito. Changelog
e DOI beta richiedono anche `!cancelled()`. CI cancella l'intera run PR superata;
su main conserva una coda non cancellabile, perché può contenere pubblicazioni.
Testing builds mantiene la politica esistente: completa la run corrente e
conserva quella pendente più recente, senza costruire ogni commit intermedio.
I test controllano anche i limiti dei job e la coerenza dei lock dei writer.

### 3.17 Cache, conservazione artifact e istruzioni obsolete — priorità bassa

**Prima.** Il packaging disabilitava sistematicamente la cache uv e conservava
l'artifact Linux beta per 30 giorni, contro sette degli altri pacchetti.
La guida descriveva ancora una copia dei manuali beta precompilati e una futura
rimozione dell'eseguibile Windows di transizione già escluso dagli upload.

**Correzione.** La cache uv è abilitata nei job di packaging e icone;
`uv sync --locked` mantiene la risoluzione vincolata. Linux beta/manuale passa
a sette giorni come gli altri pacchetti. La guida descrive il manuale condiviso,
il catalogo plugin dopo la release e le nuove regole di concorrenza.
Non è stata introdotta una cache dell'intero ambiente Python o del toolchain TeX.
Non si attribuiscono risparmi percentuali senza confrontare run GitHub reali.

## 4. Sequenza risultante e verifiche conservate

```text
PR / push main → planner CI → validazione
                           → manuale/screenshot se pertinenti
                           → plugin se pertinenti e senza release delegata
                           → release stabile se richiesta dal percorso main

push testing → piano beta → validazione → documenti → pacchetti
                                                   → pubblicazione beta se abilitata
                                                   → DOI beta e changelog

Automatic release manuale da testing
  → snapshot → validazione del sorgente → promozione esplicita
  → preparazione stabile → commit → validazione del commit preparato
  → draft → pacchetti e verifica checksum → pubblicazione stabile
  → plugin sul commit stabile / DOI / sincronizzazione testing

DOI stabile → applicazione su main → sincronizzazione testing separata
                                → richiesta sito con gate integrato
```

Le due validazioni di una promozione non sono state eliminate: controllano
rispettivamente il commit candidato prima della modifica di main e il commit
preparato con versione, lock file, manuali e immagini definitivi. Anche la
verifica dei checksum remoti dopo l'upload è distinta dalla creazione locale
del manifest. Sono barriere necessarie, non lavoro duplicato.

Restano la matrice dei test (Linux/Windows/macOS e Python aggiuntivi su Linux),
gli smoke test degli eseguibili congelati, attestazione Linux, firma/notarizzazione
macOS quando configurate, preflight contro release già pubblicate, controllo
di collisione dei tag e rifiuto di push obsoleti. Le due build Windows servono
prodotti diversi: installer con bundle e versione portabile. Le scorciatoie
manuali screenshot restano semplici deleghe al percorso comune.

## 5. Verifica locale e limiti

La verifica usa Python 3.14 nell'ambiente locale con le dipendenze GUI già
disponibili, `QT_QPA_PLATFORM=offscreen` e `PYTHONPATH=src`. Sono inclusi i test
su workflow, canali, promozione, aggiornamenti, target, badge, beta DOI/withdrawal,
changelog, documentazione, sito, packaging, citazioni e sincronizzazione Zenodo.
I test Git usano repository temporanei e remoti locali: non modificano i branch
GitHub del progetto.

**Esito:** 209 test superati e un test saltato perché richiede il vero helper
PowerShell Windows. Ruff sull'intera repository, actionlint attraverso il wrapper
del progetto e `git diff --check` superati. I casi aggiunti coprono anche il
classificatore shell dei tag stabili e la risoluzione Git del sorgente condiviso.

Comandi di riferimento:

```bash
python -m ruff check .
python .github/scripts/lint_workflows.py /percorso/actionlint
git diff --check
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m pytest -q \
  tests/test_github_workflows.py tests/test_release_channels.py \
  tests/test_testing_promotion.py tests/test_website_publication.py \
  tests/test_beta_doi.py tests/test_beta_withdrawal.py \
  tests/test_release_target.py tests/test_release_badges.py tests/test_updates.py \
  tests/test_changelog_tools.py tests/test_documentation.py \
  tests/test_community_plugin_validation.py tests/test_packaging.py \
  tests/test_zenodo_sync.py tests/test_citation_metadata.py tests/test_rrid_metadata.py
```

Il wrapper usa actionlint **1.7.12** e convalida separatamente la sintassi
`queue`, ancora ignorata da quella versione del parser. Rimane l'eccezione
specifica per l'etichetta runner `macos-15-intel`; non vengono ignorati tutti
gli errori di actionlint. Nessuna delle due eccezioni è stata ampliata dall'audit.

Le verifiche locali non sostituiscono una run reale sui runner Windows/macOS,
la verifica dei segreti di notarizzazione, le regole del branch/environment,
la disponibilità dei servizi GitHub/Zenodo e un deploy Pages effettivo. Non sono
state ricostruite localmente tutte le distribuzioni desktop né compilati nuovi
manuali stabili: non sono cambiati sorgente o layout del manuale.

## 6. Controlli alla prossima esecuzione autorizzata

1. Su una normale beta o su una prova con `[beta artifacts only]`, verificare
   che documentazione preceda packaging e che il manuale offline corrisponda
   al PDF scaricabile della stessa beta.
2. Verificare tempi reali, hit della cache e volume degli artifact prima di
   quantificare il risparmio. La nuova dipendenza documentale è un compromesso
   di correttezza esplicito.
3. Durante la prossima promozione richiesta dall'utente, verificare il richiamo
   plugin sul commit preparato e la sincronizzazione su testing. Non serve una
   promozione apposita per completare questa revisione locale.
4. Dopo che i file arriveranno sul branch predefinito, verificare che una CI PR
   non esegua Pages e che il backfill orario non ricontrolli i DOI beta completati.
5. Se un DOI beta già scritto è sospetto, richiedere la versione esplicita: il
   backfill ottimizzato non riesamina automaticamente le righe già completate.

## 7. Fonti ufficiali consultate

La semantica dei gruppi e di `queue: max` è verificata nella
[documentazione GitHub sulla concorrenza](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).
Il valore di contesto e i filtri di `workflow_run` sono descritti nel riferimento
[Events that trigger workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run).
L'assenza di nuove run push da scritture con `GITHUB_TOKEN` è documentata in
[Triggering a workflow](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow#triggering-a-workflow-from-a-workflow).
La paginazione e la visibilità dei draft seguono il riferimento
[REST API delle release](https://docs.github.com/en/rest/releases/releases#list-releases).

Queste fonti spiegano il comportamento della piattaforma. Le specifiche
conseguenze per CurveMole sono deduzioni dai workflow e dagli script esaminati,
coperte nei casi riproducibili dai test della repository.
