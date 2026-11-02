# CurveMole — correzioni del secondo audit, 2 novembre 2026

Sono stati affrontati **tutti i 14 rilievi** del secondo audit, con modifiche locali su `testing`, test di regressione e aggiornamento della documentazione pertinente. Le modifiche già presenti prima di questo intervento sono state mantenute; il precedente rapporto `audit-fixes-2026-11-02.md` resta distinto da questo documento.

Non sono stati eseguiti commit, push, pubblicazioni o promozioni a `main`. La versione sorgente e i metadati stabili restano invariati. Il manuale locale descrive ora anche queste correzioni, conservando la versione di riferimento stabile prevista dalle regole del progetto.

Le priorità P1/P2/P3 sono quelle dell'audit: indicavano l'urgenza proposta, non una frequenza misurata negli utenti reali.

## Risultati verificati

| Misura | Prima | Dopo |
|---|---:|---:|
| Deviazione standard bootstrap con sigma | 2,3594320614 | 2,3594320614 |
| Deviazione standard bootstrap con pesi equivalenti | 15,3650918499 | **2,3594320614** |
| FWHM iniziale della Gaussiana su griglia irregolare | 23,5533628022 | **0,2355336280** |
| FWHM analitica della stessa Gaussiana | 0,2354820045 | 0,2354820045 |
| Memoria del Jacobiano di prova, 20.000 × 40 | 6.400.000 byte | **320.004 byte** |
| Picco Python per hash di un file da 32 MiB | circa 33,55 MB | **circa 2,23 MB** |

Il bootstrap è stato ripetuto con **200 repliche per rappresentazione**, stesso seed 1729: entrambe le versioni completano 200 repliche senza fallimenti e restituiscono lo stesso intervallo 95%, `[-2,9646955017; 5,3234567474]`. Non ho confrontato solo un intervallo approssimativamente simile: nella prova sono uguali anche le deviazioni standard dei campioni.

La larghezza del picco conserva il normale errore di interpolazione del segnale campionato, circa **0,022%** in questo esempio, eliminando l'errore sistematico di un fattore 100. La riduzione di memoria del Jacobiano è circa **20 volte** per la struttura di prova; non è una garanzia per qualsiasi modello globale. Il confronto degli hash riguarda allocazioni tracciate in Python, non l'intera memoria di un runner o la cache del sistema operativo.

## R01 — P1 — Importazione automatica e Undo

**Problema.** Un lotto con una serie in conflitto poteva essere aggiunto parzialmente. Il successivo Undo eliminava per identificativo anche una serie precedente al lotto.

**Modifica.** In [FolderImportController.commit](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/gui/folder_import.py:397), la lista completa delle serie risultanti viene costruita e validata prima di inserire un comando nello stack Undo. Vengono preparate anche le mappe successive di modelli e risultati. `redo` applica lo stato già preparato; `undo` ripristina esattamente le serie e le mappe precedenti. Non esegue più aggiunte progressive potenzialmente fallibili dentro il metodo virtuale Qt e non rimuove oggetti con una selezione basata sui soli ID del lotto.

**Perché risolve.** Una collisione viene respinta prima di qualsiasi modifica o inserimento nello stack. Undo non può confondere un oggetto preesistente con un oggetto importato. La preparazione anticipata elimina anche una copia ridondante del lotto durante redo. La selezione dell'ultima curva importata gestisce correttamente una serie finale vuota.

**Verifica.** Test GUI con `QUndoStack` reale: conflitto nella seconda serie, progetto e revisione invariati, stack vuoto, curva originale conservata. Importazione valida seguita da Undo/Redo: si ripristina soltanto il lotto, mantenendo dati e modello preesistenti. Coperto anche il lotto con serie finale vuota.

## R02 — P1 — Bootstrap e rappresentazioni equivalenti del rumore

**Problema.** Il fitter interpretava correttamente `sigma_y` e pesi inverso-varianza equivalenti, ma il bootstrap standardizzava soltanto i residui associati alle sigma/intervalli.

**Modifica.** Una funzione comune, [_resampling_scales](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/uncertainty.py:228), ricava le scale anche dai pesi inverso-varianza positivi: `1/sqrt(weight)`. La preparazione dei campioni, la validazione e la stima automatica della lunghezza dei blocchi usano la stessa rappresentazione. La configurazione registrata indica correttamente la standardizzazione e il modello di rumore relativo dei pesi.

**Perché risolve.** I residui vengono ricampionati nella stessa scala standardizzata, indipendentemente dalla rappresentazione equivalente dell'incertezza; poi vengono ricostruiti con la scala della riga di destinazione. La stessa correzione vale per residual bootstrap e block bootstrap, inclusa la scelta automatica del blocco.

**Scelte mantenute.** I moltiplicatori arbitrari dei residui non vengono reinterpretati come varianze. Il Monte Carlo continua a richiedere errori Y assoluti adeguati. Come già documentato, gli errori forniti descrivono il rumore del ricampionamento anche se il loro uso come pesi nel fit è disattivato; per il ricampionamento devono essere validi sulle righe fitted. Non è stata cambiata questa scelta scientifica per far passare i test.

**Verifica.** Equivalenza dei campioni per entrambi i bootstrap, coerenza della lunghezza automatica dei blocchi, test esistenti su errori asimmetrici, maschere, seriale/parallelo e rumore fornito con weighting disattivato. Misura di conferma a 200 repliche riportata sopra.

## R03 — P2 — Plugin disabilitato ripristinato dal livello progetto

**Problema.** Una formula del progetto poteva nascondere la definizione di un plugin. Disabilitando il plugin, la copia nascosta restava nel registro e tornava attiva rimuovendo la formula.

**Modifica.** [FunctionRegistry.remove_owner](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/registry.py:73) elimina sia le definizioni visibili del plugin sia quelle conservate sotto un override, preservando la formula attiva del progetto. `unregister` impedisce che una rimozione esplicita venga annullata dal ripristino del livello progetto; `copy` conserva in modo isolato le informazioni di quel livello.

In [PluginManager](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/plugins.py:281), disabilitazione e rimozione rendono inutilizzabili anche i callback precedentemente conservati da un chiamante. Il controllo tiene conto dello stato disabilitato anche dopo la cancellazione del record di installazione. Una nuova operazione esplicitamente autorizzata di caricamento riabilita il proprietario; la fase di registrazione viene gestita separatamente, e un caricamento fallito torna allo stato disabilitato.

**Perché risolve.** Il codice del plugin non rimane nascosto in un punto che possa ripristinarlo più tardi. Una semplice referenza Python a un vecchio wrapper non aggira più la disabilitazione mentre il plugin è spento o rimosso.

**Verifica.** Plugin effettivamente caricato con `3*x`, override `5*x`, disabilitazione oppure rimozione: la formula del progetto continua a produrre 10 per X=2, poi la rimozione dell'override non ripristina il plugin. I callback conservati falliscono con errore di plugin disabilitato. Un successivo caricamento autorizzato torna a funzionare. Coperti anche copia del registro e `unregister`.

## R04 — P2 — Fingerprint delle sorgenti interne/legacy dei plugin

**Problema.** Quando `storage` era un antenato della sorgente del plugin, la sua esclusione eliminava tutti i file dal fingerprint, producendo lo SHA-256 della sequenza vuota.

**Modifica.** In [_fingerprint](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/plugins.py:220), la directory di stato viene esclusa interamente soltanto quando è realmente una discendente della root sorgente. Se coincide con la root, vengono esclusi i soli file di stato previsti. Un antenato della sorgente non viene escluso.

**Perché risolve.** I file del plugin restano nell'insieme effettivamente sottoposto a hash. I criteri di proprietà dei file già esistenti continuano a delimitare gli helper e le risorse del plugin.

**Verifica.** Plugin sintetico in `storage/legacy`: digest non vuoto, modifica di `helper.py` rilevata, digest uguale a quello del manager headless senza storage. Mantiene il divieto già presente nell'updater community di scegliere nuove destinazioni interne: la correzione protegge anche le sorgenti manuali/legacy accettate dal loader.

## R05 — P2 — Coerenza del file durante il passaggio di controllo

**Problema.** La sincronizzazione poteva sostituire il progetto fra controllo dell'hash e lettura, lasciando caricati dati diversi da quelli confermati e un digest su disco obsoleto.

**Modifica.** [_poll_project_transfer](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/gui/main_window.py:4771) usa il [lettore responsivo comune](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/gui/project_loading.py:13) dopo l'acquisizione del lock. Il worker verifica il digest atteso prima della lettura e la stabilità del contenuto dopo la lettura. Prima del cambio di sessione vengono convalidate anche le definizioni personalizzate. Il digest registrato è quello verificato dal caricamento. Il monitor non rientra nel trasferimento mentre è già in corso un caricamento.

**Perché risolve.** Una copia non ancora sincronizzata o sostituita durante la lettura non viene adottata. In caso di errore viene rilasciato il nuovo lock e resta attiva la sessione precedente; la richiesta può attendere la sincronizzazione corretta. Hash e I/O non bloccano più il thread GUI del trasferimento.

**Verifica.** Sostituzione controllata subito dopo l'acquisizione del lock; sostituzione durante la lettura; conservazione della sessione read-only e rilascio del lock; timer Qt eseguito durante il lavoro; trasferimento normale verificato dai test esistenti.

**Limite.** È una verifica di coerenza del contenuto osservato, non un protocollo di mutua esclusione distribuita imposto al programma di sincronizzazione. Un cambiamento successivo rimane soggetto ai controlli di conflitto al salvataggio già presenti.

## R06 — P2 — Collisioni fra intestazioni degli export

**Problema.** I dizionari delle colonne usavano le etichette come identità uniche. Un nome coincidente poteva sovrascrivere X, Y, errori o altre tracce.

**Modifica.** Il nuovo [ExportColumns](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/export_columns.py:5) è condiviso da [wide_dataframe](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/export.py:126) ed [export rapido](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/spectrum_export.py:38). Alloca un suffisso `__2`, `__3`, ... finché il nome è disponibile. I DataFrame conservano nei metadati i nomi assegnati ai ruoli X/Y e, nell'export wide, X originale. L'export tidy usa quei ruoli invece di dedurre X dal testo dell'etichetta.

**Perché risolve.** Ogni inserimento conserva le colonne precedenti; la disambiguazione vale per l'intera tabella, non soltanto per i componenti. La logica comune elimina la duplicazione che aveva riprodotto lo stesso difetto nei due esportatori. Il formato rapido mantiene intestazioni senza spazi.

**Verifica.** Etichetta X uguale alla colonna Y generata nell'export rapido; etichette X/Y coincidenti con `sigma_y` nel wide; conservazione degli array X, Y e sigma; intestazioni uniche; coordinate e valori corretti anche nel tidy. Restano coperti i componenti con nomi duplicati dai test precedenti.

## R07 — P2 — Vincoli malformati e recupero degli archivi

**Problema.** Gli errori di vincolo/espressione sollevati costruendo un modello sfuggivano al contratto del validatore, anche con `raise_on_error=False`, e interrompevano l'elenco dei recuperi.

**Modifica.** [validate_manifest](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/archive_validation.py:68) converte anche `ConstraintError` ed `ExpressionError` dei value object in errori strutturali dell'archivio. I wrapper esistenti restituiscono così una lista di difetti oppure un `ProjectFormatError`, secondo l'opzione richiesta.

**Perché risolve.** `RecoveryManager.candidates` può scartare il singolo archivio non valido e proseguire con quelli validi. La cattura resta circoscritta agli errori previsti di validazione: non nasconde indiscriminatamente errori interni o cancellazioni.

**Verifica.** Archivio valido affiancato da una copia con minimo incompatibile con il valore oppure espressione malformata: validatore non eccezionale con lista di problemi, loader con `ProjectFormatError`, recupero valido ancora restituito nell'elenco.

## R08 — P2 — FWHM su griglie X irregolari

**Problema.** La larghezza in campioni veniva moltiplicata per il passo mediano globale, che non rappresenta il passo locale vicino al picco.

**Modifica.** [find_peak_suggestions](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/initialization.py:42) converte le intersezioni interpolate di sinistra e destra nelle coordinate X reali. X e Y vengono ordinati insieme; X decrescente o non ordinata è quindi gestita in modo coerente. Coordinate duplicate vengono respinte con un errore esplicito, evitando una larghezza fisica ambigua.

**Perché risolve.** La FWHM è la distanza fra le intersezioni sul vero asse X, indipendente dalla densità di campionamento delle code. Il centro del picco e la sua intensità restano associati ai dati corretti durante l'ordinamento.

**Verifica.** Gaussiana nota su griglia con passo locale 0,01 e passo 1 nelle code, nelle varianti crescente, decrescente e mescolata; tolleranza relativa 0,1%, risultato osservato circa 0,022%. Test esplicito delle coordinate duplicate.

## R09 — P2 — Unicità globale degli identificativi nell'API

**Problema.** `Project.add_curve` verificava la curva soltanto nella serie destinazione e poteva sostituire il modello di una curva con lo stesso ID in un'altra serie.

**Modifica.** [Project.add_curve](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/project.py:61) verifica l'appartenenza della serie al progetto e l'assenza dell'ID fra tutte le curve e serie prima di modificare il dataset. [Dataset.add_series](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/data.py:783) valida l'insieme risultante prima dell'aggiunta, proteggendo anche l'inserimento di un'intera serie.

**Perché risolve.** Un ID non valido viene respinto prima di creare un modello vuoto o incrementare la revisione. La protezione è nel core e si applica anche ai chiamanti Python/plugin.

**Verifica.** Curva duplicata in seconda serie, serie contenente una curva duplicata, serie di destinazione estranea: tutte respinte, conservando identità e componenti del modello originale, curve e revisione.

## R10 — P3 — Pesi e loro convenzione nell'export rapido

**Problema.** Il file rapido non conteneva i pesi espliciti; ridisegnava correttamente la curva, ma non descriveva il fit pesato.

**Modifica.** Le tabelle rapide includono `weight` e il campo numerico `weights_are_inverse_variance`: 1 per inverso-varianza, 0 per moltiplicatore diretto dei residui. La stessa convenzione è esplicitata negli export wide quando si esportano i pesi. I valori sono quelli correnti, dopo le trasformazioni.

**Perché risolve.** Il destinatario dispone sia dei valori sia dell'informazione necessaria a interpretarli, senza assumere automaticamente una convenzione di weighting.

**Verifica.** Scrittura e lettura del file rapido per entrambe le convenzioni: pesi `[1,2,3]` conservati e flag corretto. Non è stato aggiunto un riconoscimento automatico delle colonne al generico importatore: in una reimportazione restano da selezionare le colonne e la rappresentazione coerenti.

## R11 — P3 — Statistiche dei baseline individuali

**Problema.** L'estrazione di un baseline indipendente rimpiazzava le statistiche complete con il sottoinsieme dell'output per curva.

**Modifica.** [baseline_for_curve](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/fit_records.py:26) conserva le statistiche complete per un risultato già individuale. Per un batch indipendente ricalcola le statistiche sulla sola curva con il suo numero di parametri liberi. Il ramo globale conserva il risultato comune, necessario per i parametri accoppiati.

**Perché risolve.** N, k, gradi di libertà, chi-quadro e criteri informativi non scompaiono; i valori aggregati del batch non vengono attribuiti erroneamente a ogni spettro. Continuano a essere copiate soltanto le matrici e gli array selezionati.

**Verifica.** Confronto dei baseline estratti con fit individuali equivalenti per N, k, DOF, chi-quadro, chi-quadro ridotto, AIC/AICc/BIC. Il test di memoria è aggiornato per verificare statistiche complete e continua a impedire il deepcopy degli array dello spettro non selezionato. Verificata la conservazione dell'accoppiamento nei baseline globali.

## R12 — P3 — Jacobiano sparso e covarianza senza matrice densa N×P

**Problema.** Nei fit globali veniva costruita una matrice densa residui × parametri anche quando le curve dipendevano da pochi parametri locali.

**Modifica.** Il nuovo modulo [jacobians.py](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/jacobians.py:9) ricava le dipendenze transitive dei parametri, includendo link di uguaglianza e limiti relazionali. Per problemi con più curve, almeno 16 parametri liberi e densità stimata inferiore al 50%, costruisce uno schema CSR e raggruppa le perturbazioni numeriche compatibili. La stima della densità precede l'allocazione dello schema, evitando di costruire una matrice grande per poi scartarla.

[Il fitter](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/fitting.py:543) usa il Jacobiano sparso e seleziona TRF in modalità locale automatica per questi casi. LM esplicito e l'interfaccia Jacobiano dei solver plugin restano densi, mantenendo il loro contratto. Non si presume che tutte le curve siano indipendenti: i link fra curve sono parte dello schema.

La covarianza usa una riduzione QR a blocchi di righe e una SVD della matrice ridotta. Non converte l'intero Jacobiano in denso e non sostituisce la SVD con le sole equazioni normali, che peggiorerebbero il condizionamento numerico. I prodotti della covarianza robusta vengono eseguiti sullo sparso prima di materializzare le matrici fra parametri. SciPy viene caricato al momento del calcolo, preservando l'avvio leggero della GUI.

**Perché risolve.** Si conservano soltanto le derivate strutturalmente necessarie e si riducono le valutazioni per differenze finite. La riduzione per la covarianza limita la memoria delle righe dense temporanee, preservando le informazioni dei piccoli valori singolari.

**Verifica.** Derivate sparse contro differenze finite dense con parametri locali, link fra curve e limite dinamico; covarianze lineari e sandwich Huber/soft-L1/Cauchy contro la versione densa; fit automatico contro LM esplicito; SVD a più blocchi con colonne quasi dipendenti. Verificato anche che la GUI vuota non importi SciPy.

**Limiti mantenuti.** Covarianza e correlazione finali occupano ancora memoria quadratica nel numero di parametri. Modelli densamente accoppiati, fit piccoli e LM esplicito possono richiedere il percorso denso. L'ottimizzazione non cambia la semantica dei vincoli e non rende illimitata la dimensione del problema.

## R13 — P3 — Ripetibilità del publisher beta

**Problema.** `SHA256SUMS.txt` e `beta-notes.md`, generati nella cartella degli asset, venivano considerati asset estranei al secondo tentativo.

**Modifica.** [publish](/home/seb/.codex/worktrees/458d/curvemole/.github/scripts/beta_release.py:110) distingue esplicitamente quei due output generati dagli input della build. Continua a richiedere l'insieme esatto degli asset di build, rigenera checksum/note e conserva i controlli sul commit e sull'immutabilità delle beta pubblicate.

**Perché risolve.** Il secondo tentativo raggiunge il controllo della release esistente invece di fallire sui propri file temporanei. Altri file estranei continuano a bloccare la pubblicazione.

**Verifica.** Due invocazioni consecutive nella stessa cartella con chiamate GitHub sostituite da stub: entrambe completate, nessuna chiamata di modifica di una release già pubblicata. L'aggiunta di `unexpected.exe` viene ancora respinta. I test esistenti coprono anche verifica dei digest caricati e preservazione della release stabile. Nessuna pubblicazione reale eseguita.

## R14 — P3 — Hash degli artifact beta in streaming

**Problema.** Ogni installer veniva letto integralmente in RAM per calcolarne il digest.

**Modifica.** [file_digest](/home/seb/.codex/worktrees/458d/curvemole/.github/scripts/beta_release.py:102) aggiorna SHA-256 leggendo blocchi da 1 MiB. Il publisher lo usa per gli asset e il file dei checksum.

**Perché risolve.** L'allocazione per la lettura dipende dalla dimensione del blocco, anziché da quella del file più grande. Il digest e il formato dei checksum rimangono gli stessi.

**Verifica.** Confronto con SHA-256 di riferimento; test che vieta `Path.read_bytes` durante l'hash; misura di memoria su un file sintetico da 32 MiB: circa 2,23 MB di picco Python contro 33,55 MB del precedente metodo.

## Verifiche complessive e documentazione

Sono stati aggiunti **34 casi di regressione** nei file:

- [integrità e plugin](/home/seb/.codex/worktrees/458d/curvemole/tests/test_second_audit_integrity.py);
- [statistica e calcolo sparso](/home/seb/.codex/worktrees/458d/curvemole/tests/test_second_audit_science.py);
- [GUI, importazione e handoff](/home/seb/.codex/worktrees/458d/curvemole/tests/test_second_audit_gui.py).

È stato adeguato il test preesistente di memoria dei baseline alla completezza delle statistiche, conservandone le verifiche di isolamento e assenza di copie superflue.

**Esito complessivo:** 1.920 test superati, 1 saltato perché richiede l'helper PowerShell Windows, 2 warning già presenti (pulizia Matplotlib di un asse logaritmico e membro ZIP duplicato deliberatamente nel test di corruzione). Ruff e lint dei workflow passano; `git diff --check` non segnala errori. I test IPC Qt sono stati eseguiti con il permesso necessario ai socket locali, senza cambiare il codice per eludere le restrizioni della sandbox.

Le verifiche hanno incluso i test di aggiornamento, canali release, pubblicazione e workflow. Non sono stati eseguiti installer Windows/macOS reali o job remoti: le verifiche di pubblicazione usano stub.

Sono stati aggiornati `docs/python-api.md`, i passaggi corrispondenti di `docs/manual.md` e l'appendice Python incorporata. Le edizioni LaTeX e PDF sono state rigenerate dal Markdown. Il PDF ha 136 pagine; sono state renderizzate e controllate visivamente le pagine 49, 58, 66 e 110, relative a selezione del solver, bootstrap, export e riferimento API. Controllati anche testo estratto, versione e corrispondenza dell'identificativo PDF con il LaTeX.

Le misure, lo script di conferma e i log finali sono nella [cartella locale delle evidenze](/home/seb/.codex/visualizations/2026/10/30/01a18c7d-2867-70a1-af48-28cb565c5b15/curvemole-second-audit-fixes-2026-11-02). Il [rapporto originale del secondo audit](/home/seb/.codex/visualizations/2026/10/30/01a18c7d-2867-70a1-af48-28cb565c5b15/curvemole-second-audit-2026-11-02/REPORT.md) conserva le riproduzioni precedenti alle correzioni.
