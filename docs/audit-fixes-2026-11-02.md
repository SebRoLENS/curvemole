# CurveMole: correzioni dell'audit del 2 novembre 2026

## Esito e stato del lavoro

Le correzioni sono applicate **soltanto in locale sul ramo `testing`**. Da questo intervento non sono stati eseguiti push, pubblicazioni, promozioni su `main` o installazioni reali degli aggiornamenti. Versione del pacchetto, CITATION e metadati stabili del manuale restano invariati.

Il lavoro parte da `9ae1347`, con le modifiche esterne presenti nell'index, incluse quelle comparse durante il lavoro, lasciate intatte. Quelle modifiche riguardano changelog, relativo generatore/test e test delle shortcuts; non fanno parte di questo intervento. Le modifiche di questo lavoro restano disponibili nel working tree per la revisione. Durante le verifiche il checkout è avanzato esternamente fino a `4078073`, tramite commit su test delle shortcuts e changelog. Ho verificato che quei commit non modificano il codice applicativo o i workflow corretti in questo intervento. Il manifest delle evidenze registra il riferimento finale e gli hash dei file locali.

Sono stati affrontati i **22 rilievi** del rapporto iniziale: 18 comportamenti riprodotti, tre rischi da ispezione e la duplicazione architetturale negli esempi individuati. Per l'architettura è stato effettuato un consolidamento mirato dei percorsi segnalati; altri strumenti GUI continuano a usare gli installer storici descritti più avanti.

**Verifica finale: 1.886 test passati, uno saltato, nessun errore.** Il test saltato esercita il vero helper PowerShell su Windows, mentre questa verifica è stata eseguita su Linux. Sono stati aggiunti 46 casi di regressione nei tre nuovi moduli `test_november_audit_*`. Ruff su sorgenti, test, script e script GitHub: nessun rilievo. `git diff --check`: nessun problema. Il Markdown del manuale supera la validazione del generatore e i riferimenti Python/YAML incorporati sono sincronizzati con le rispettive guide.

Gli esempi di test citati sotto sono consultabili in:

- [Regressioni scientifiche](/home/seb/.codex/worktrees/458d/curvemole/tests/test_november_audit_science.py).
- [Integrità dei dati e limiti di risorse](/home/seb/.codex/worktrees/458d/curvemole/tests/test_november_audit_integrity.py).
- [Regressioni dell'interfaccia e updater](/home/seb/.codex/worktrees/458d/curvemole/tests/test_november_audit_gui.py).

## 01. Apertura di una copia superata del progetto

**Modifica.** La conferma sul progetto corrente precede la lettura del nuovo file. Il lock del candidato viene acquisito prima della lettura; il progetto corrente e il suo lock vengono mantenuti finché lettura, verifica del file e definizioni custom non sono accettate. Il caricamento confronta i digest prima e dopo la lettura, nello stesso worker. Un cambiamento rilevato interrompe l'apertura. Il digest accettato viene associato al progetto caricato.

**Perché risolve.** Non si può più caricare la vecchia copia prima del dialogo e assegnarle successivamente l'impronta della nuova copia scritta durante quel dialogo. Un'apertura fallita conserva la sessione precedente. Se il file cambia successivamente, resta operativo il controllo prima del salvataggio.

**Verifica.** Il test sostituisce il file nel callback di conferma: viene aperto `latest`, con il suo digest. Un secondo tentativo su un file inesistente lascia intatti progetto e lock correnti. Si verificano anche eventi GUI e annullamento del caricamento.

**Codice:** [MainWindow](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/gui/main_window.py), [caricamento responsivo](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/gui/project_loading.py), [digest cancellabile](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/project_handoff.py).

## 02. Contaminazione delle funzioni tra progetti

**Modifica.** Ogni finestra ha un registro di sessione distinto. Le funzioni del progetto sono uno strato sostituibile: prima si compilano e verificano tutte le definizioni, poi si sostituisce lo strato, ripristinando eventuali definizioni preesistenti quando si cambia progetto. Anche il nuovo progetto richiama questo ripristino. Workflow senza registro esplicito ed export automatici lavorano su copie del registro globale.

È stato introdotto `register_custom`, che impedisce alle formule provenienti da progetto, libreria, builder e workflow di riutilizzare identificativi integrati. Le collisioni vengono segnalate esplicitamente. La libreria persistente viene caricata prima dello strato del progetto. Il registro passato esplicitamente dal chiamante a un workflow conserva la sua precedente semantica di oggetto posseduto dal chiamante; l'API di estensione a basso livello mantiene la sostituzione esplicita tramite `register(..., replace=True)`.

**Perché risolve.** Un file di progetto non modifica più il significato delle funzioni dei progetti successivi o degli export successivi. Una collisione non viene reinterpretata silenziosamente come la funzione integrata.

**Verifica.** Isolamento del registro base, rimozione dello strato al nuovo progetto, ripristino di una funzione della libreria, rifiuto di `constant` custom, isolamento del registro di export. Restano verdi i test delle sostituzioni esplicite a basso livello e del multicore.

**Codice:** [registro](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/registry.py), [workflow](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/workflow.py), [export](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/export.py), [libreria](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/gui/quick_function_library.py).

## 03. Risultati precedenti eliminati dall'import automatico

**Modifica.** Il merge distingue le mappe previste dallo schema: fit, incertezze, report, fallimenti, scelta del metodo visualizzato e baseline globali. Queste mappe vengono unite per identificativo; riferimenti a curve estranee e collisioni con analisi esistenti sono rifiutati. Per gli altri campi di primo livello, un valore precedente sostituito viene conservato in `import_result_history`. Uno storico ricevuto dall'acquisizione viene aggiunto allo storico corrente. Undo ripristina il dizionario precedente.

**Perché risolve.** Il nuovo dizionario di una sola acquisizione non sostituisce più la mappa di tutte le curve. I risultati generali che rappresentano l'ultima operazione possono aggiornarsi senza cancellarne il precedente valore archiviato.

**Verifica.** Conservazione simultanea delle analisi vecchie e nuove, dei metodi visualizzati e degli storici ricevuti; rifiuto di ID non appartenenti all'acquisizione. Passano i test dell'import da cartella.

**Codice:** [merge dei risultati](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/folder_import.py), [controller e undo](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/gui/folder_import.py).

## 04. Sovrascritture implicite e link simbolici nell'export

**Modifica.** `export_spectra` esegue il preflight di tutte le destinazioni e usa `overwrite=False` come default. L'interfaccia chiede una conferma con risposta predefinita negativa quando esistono file da sostituire. I link simbolici sono rifiutati anche con overwrite esplicito. Le conversioni vengono preparate in file temporanei, scaricate su disco e poi pubblicate; senza overwrite, la pubblicazione è esclusiva. Sui filesystem senza hard link è disponibile una scrittura esclusiva compatibile. L'export bundle propaga la scelta di overwrite già autorizzata dal proprio flusso.

**Perché risolve.** Un export normale non può più cancellare un file già esistente né seguire il suo link verso un altro file. Le conversioni fallite non lasciano file finali prematuramente troncati.

**Verifica.** Un conflitto sul secondo file impedisce di scrivere anche il primo; una sentinella esistente resta intatta; il target di un symlink resta intatto anche chiedendo overwrite. Verificati sostituzione esplicita, pulizia dei temporanei e filesystem senza hard link.

Un errore del filesystem durante la pubblicazione di più file può ancora lasciare un insieme parziale di file pubblicati: la transazione non è atomica sull'intero batch. Questo limite è dichiarato nella documentazione.

**Codice:** [export numerico](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/spectrum_export.py), [azione GUI](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/gui/spectrum_export_ui.py).

## 05. Covarianza robusta incoerente fra solver

**Modifica.** Per `least_squares` robusto si ricostruisce il Jacobiano dei residui pesati originali; i percorsi minimize/estensioni hanno già quel Jacobiano e lo riutilizzano. Il sandwich usa la funzione d'influenza e la sua derivata coerenti con Huber, soft-L1 o Cauchy:

`A = J.T @ diag(psi_prime) @ J`

`B = J.T @ diag(psi**2) @ J`

`C = inv(A) @ B @ inv(A).T * N/(N-k)`

Una sensibilità singolare rende la covarianza non disponibile, con spiegazione. La ricostruzione avviene dentro il percorso protetto di annullamento e ripristino dei parametri.

**Perché risolve.** Non si mescolano più Jacobiani con semantiche diverse né residui quadratici e influenza robusta. Cambiare solver, a parità di ottimo, non cambia l'estimatore statistico.

**Verifica numerica, esempio Huber dell'audit:**

| Solver | Prima: varianza | Dopo: varianza |
|---|---:|---:|
| local | 0,01953125 | 0,09765625 |
| Powell | 4,765625 | 0,097656249995 |

L'ottimo resta circa 0,25. Il nuovo valore coincide con il riferimento scalare usando la stessa correzione finita HC1. Ci sono test anche per soft-L1, Cauchy e annullamento prima della covarianza. Il sandwich resta un'approssimazione locale: il resampling rimane consigliato nei problemi difficili.

**Codice:** [fitting](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/fitting.py).

## 06. Profile likelihood dipendente dall'unità di Y

**Modifica.** La distinzione fra rumore assoluto noto e scala stimata è condivisa con la covarianza. Con scala nota si usa la differenza di chi-quadro; con scala ignota si profila la varianza comune tramite `N*log(Q_trial/Q_min)`. Per un fit globale separabile, il profilo usa il contributo delle altre curve e il numero totale di osservazioni per la scala comune.

Loss robuste, errori asimmetrici e bilanciamenti arbitrari degli spettri vengono rifiutati da questo profilo gaussiano con un messaggio che indirizza al bootstrap. Un fit a residuo esattamente nullo, senza sigma note, non può stimare il rumore: viene richiesto un rumore noto invece di produrre un intervallo ingannevole. Il nome serializzato `delta_chi_square` viene mantenuto per compatibilità e la documentazione chiarisce la statistica utilizzata.

**Perché risolve.** Nel caso di scala ignota il rapporto di somme quadratiche non cambia se si cambia coerentemente l'unità di misura. Non viene più attribuita una calibrazione gaussiana a un diverso obiettivo robusto.

**Verifica.** Nel confronto originale fra Y e `100*Y`, la statistica all'estremo normalizzato +1 ora è **2,02732554054 in entrambi i casi**, invece di 5 e 50.000. Test separati verificano sigma note, profilo globale separabile, rifiuto della loss robusta e rumore non stimabile. La soglia resta una calibrazione asintotica e la scansione resta finita: non è una garanzia di copertura esatta per piccoli campioni.

**Codice:** [uncertainty](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/uncertainty.py).

## 07. Convoluzione e maschere nel profilo

**Modifica.** Anche quando fissare il parametro esaurisce i parametri liberi, il profilo usa `evaluate_for_curve`: convoluzione sulla griglia completa, selezione degli indici dopo la valutazione. Gli errori applicativi di un punto di scansione vengono contati come punti falliti in modo coerente con il percorso che richiede un nuovo fit.

**Perché risolve.** Una maschera interna non trasforma più artificialmente la griglia della convoluzione in una griglia irregolare.

**Verifica.** Fit e profilo delle gaussiane convolute su griglia regolare con un punto interno mascherato terminano correttamente; nessun punto del profilo fallisce. L'esempio usa sigma note per definire correttamente il problema statistico.

## 08. Propagazione dei pesi inverso-varianza

**Modifica.** Si propaga un fattore di sigma unitario attraverso le trasformazioni reversibili e le derivate locali delle formule. Alla fine il peso inverso-varianza viene diviso per il quadrato di quel fattore. L'uso del fattore unitario evita il rumore numerico di una conversione peso-sigma-peso quando Y non cambia. Un fattore nullo non viene trasformato in informazione infinita. I moltiplicatori arbitrari dei residui conservano la propria semantica dichiarata.

**Perché risolve.** L'informazione statistica espressa come peso inverso-varianza si trasforma come quella espressa come sigma.

**Verifica.** Dopo `Y *= 10`, `[1,4,9]` diventa **[0,01; 0,04; 0,09]**. Formule non lineari concordano con la propagazione delle sigma e undo ripristina i pesi. Aggiornato il test del worksheet per mostrare i nuovi pesi corretti.

**Codice:** [Curve._recompute](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/data.py).

## 09. Righe a peso zero nei gradi di libertà

**Modifica.** Quando i pesi sono la rappresentazione attiva dell'errore Y, le righe a peso zero sono escluse dagli array del fit. Restano consultabili nel dato e nel worksheet. Quando è attiva un'altra rappresentazione dell'errore, non si eliminano righe per pesi non utilizzati.

**Perché risolve.** Covarianza, N, gradi di libertà e statistiche lavorano sulle osservazioni che forniscono informazione all'obiettivo.

**Verifica.** Aggiungere tre righe a peso zero lascia invariati **N=3**, **dof=2** ed errore standard **0,881917103688197**. Prima l'errore standard scendeva impropriamente a circa 0,558.

## 10. AIC/AICc/BIC nei fit pesati

**Modifica.** I criteri derivano dalla verosimiglianza gaussiana dei residui pesati, inclusa la normalizzazione delle precisioni. Se la scala del rumore viene stimata, conta come parametro di verosimiglianza. Il merge di fit indipendenti conserva le rispettive scale stimate, sommando le log-verosimiglianze; non le sostituisce con un'unica scala dopo il fit. Sono esposti `negative_twice_log_likelihood` e `likelihood_parameters`.

Per loss robuste, errori asimmetrici e bilanciamenti arbitrari non viene pubblicato un criterio gaussiano non giustificato.

**Perché risolve.** Il criterio usa il modello di rumore del fit anziché classificare un fit pesato attraverso il suo RSS non pesato. I valori numerici precedenti dei criteri possono quindi cambiare: è una modifica intenzionale della definizione statistica.

**Verifica.** Controllo della formula gaussiana con sigma note, conteggio del parametro di scala ignota ed equivalenza tra sigma e pesi inverso-varianza relativi. I test di fitting e workflow restano verdi.

## 11. Mutazioni respinte sui progetti read-only

**Modifica.** `ensure_editable()` controlla l'accesso prima delle mutazioni core segnalate: aggiunta/rimozione di curve, serie e componenti, invalidazione e snapshot. `touch()` mantiene il controllo aggiuntivo. La lettura di un modello mancante in un progetto read-only restituisce un modello vuoto temporaneo senza inserirlo nel progetto.

**Perché risolve.** Il rifiuto non arriva più dopo aver già cambiato dataset o modelli. Una semplice lettura non crea stato persistente.

**Verifica.** Cinque casi di mutazione rifiutata conservano curve, serie, componenti, storico, dirty e revisione. Rimangono verdi i test del notebook in sola lettura. Le strutture Python restano oggetti mutabili: questo controllo riguarda i metodi dell'API, non una sandbox contro plugin Python fidati che assegnino direttamente ai campi.

## 12. copy_fit e stato delle curve dipendenti

**Modifica.** Dopo una copia riuscita, l'API core invalida i fit delle destinazioni e dei dipendenti transitivi tramite link e accoppiamenti globali. Anche aggiungere una componente attraverso l'API invalida il relativo fit. Le registrazioni precedenti restano come storico fuori data.

**Perché risolve.** Parametri modificati non vengono più accompagnati da uno stato `Fitted` ancora considerato corrente. Non vengono presentati come risultati ricalcolati: il nuovo fit deve essere eseguito.

**Verifica.** La sorgente resta `Fitted`; destinazione e terza curva collegata diventano `Modified/outdated` dopo il cambiamento del parametro risolto.

**Codice:** [Project](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/project.py).

## 13. Formula custom disabilitata nel multicore

**Modifica.** La preparazione del registro dei worker include anche le definizioni richieste dalla validazione delle componenti disabilitate. Una definizione non trasferibile non viene inviata come callback Python eseguibile al processo.

**Perché risolve.** Validazione del modello e costruzione del registro dei worker usano lo stesso insieme di componenti, evitando `Unknown function` dipendente dal numero di worker.

**Verifica.** Lo stesso problema con formula custom disabilitata riesce con uno e due worker, con parametri concordanti.

**Codice:** [worker_functions](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/worker_functions.py).

## 14. Validazione strutturale incompleta degli archivi

**Modifica.** Un modulo dedicato valida schema, tipi essenziali, identificativi, riferimenti delle serie, strutture di modelli/maschere/trasformazioni, checksum e membri duplicati. Non richiede che un modello scientifico incompleto sia già fittabile e accetta i record storici di modelli rimossi usati dal notebook. Gli errori di struttura durante il caricamento sono convertiti in `ProjectFormatError`.

**Perché risolve.** Il contenitore leggibile e il checksum corretto non bastano più per dichiarare valido un progetto con `project=[]` o record annidati strutturalmente errati. La verifica del checksum viene conservata anche quando un header NumPy è corrotto.

**Verifica.** Rifiuto del manifest originale dell'audit, di modelli/maschere/trasformazioni malformati e di array con dimensioni falsificate. Passano round-trip, corruzione, recupero parziale, memoria di storage e notebook storico.

**Codice:** [archive_validation](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/archive_validation.py), [serialization](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/serialization.py).

## 15. Impronta dei plugin e helper locali

**Modifica.** L'impronta comprende i sorgenti Python ausiliari locali. Nelle directory piatte gli entry point degli altri plugin sono separati, salvo import esplicito; per un plugin in un package vengono incluse anche le risorse del package. Risorse aggiuntive in una directory piatta sono dichiarabili con `files` nel manifest. Stato del manager e cache non fanno parte del codice approvato. Si riutilizza l'algoritmo canonico di fingerprint.

**Perché risolve.** Cambiare `helper.py` modifica l'impronta e fa scattare la verifica di nuova approvazione. Cambiare il file di configurazione del manager o una diversa estensione non genera la stessa contaminazione dell'impronta.

**Verifica.** Cambio helper rilevato, stato del manager escluso, avvio incrementale di più plugin e quarantena del plugin cambiato verificati dalla suite.

**Compatibilità.** Il nuovo algoritmo può richiedere una nuova approvazione una tantum dei plugin già registrati. Le dipendenze Python esterne alla cartella del plugin restano parte dell'ambiente fidato; il fingerprint non è una sandbox.

**Codice:** [PluginManager](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/plugins.py), [fingerprint canonico](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/plugin_fingerprint.py).

## 16. Precisione dell'export numerico

**Modifica.** Il formato numerico passa da 12 a 17 cifre significative.

**Perché risolve.** Il testo conserva la precisione necessaria al round-trip dei float64, senza confondere due numeri diversi semplicemente perché vicini.

**Verifica.** `1.0000000000001` e `1.0000000000002` rimangono distinti e vengono riletti esattamente da NumPy; prima entrambi diventavano `1`.

## 17. Liste temporanee inutili dopo il resampling

**Modifica.** La costruzione del report usa `to_dict(include_samples=False)` per i risultati di ricampionamento. I campioni restano conservati nel risultato scientifico; vengono convertiti solo quando l'operazione richiede davvero di serializzarli.

**Perché risolve.** Non si costruisce più una grande lista Python per eliminarla immediatamente dal report.

**Verifica.** Un array di test che solleva un errore quando viene chiamato `tolist()` viene gestito correttamente. Nel benchmark della sola conversione di metadati, per una matrice da 4 MB il picco temporaneo Python passa da circa **16,64 MB a 584 byte**. Questo non misura tutta la memoria della GUI: per esempio la correlazione dei campioni resta un calcolo necessario separato.

**Codice:** [_store_uncertainty_result](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/gui/main_window.py).

## 18. Updater che procede senza digest

**Modifica.** Il digest deve avere formato `sha256:` seguito da 64 cifre esadecimali. Digest mancanti, incompleti o di algoritmi non supportati interrompono il percorso automatico, eliminano il download temporaneo e indicano il download manuale. Un digest valido viene confrontato con quello del contenuto prima dell'installer.

**Perché risolve.** L'assenza dei metadati non disattiva più implicitamente la verifica d'integrità.

**Verifica.** Tre casi di digest non valido non raggiungono il callback dell'installer. I test degli aggiornamenti e dei canali restano verdi. Le prove non hanno lanciato installer reali.

**Codice:** [UpdateController](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/gui/updates.py).

## 19. Budget degli archivi e blocco dell'interfaccia durante l'apertura

**Modifica.** `ArchiveLimits` impone valori predefiniti espliciti: 100.000 membri, 1 GiB di contenuto espanso totale, 256 MiB per array e 32 MiB di manifest. Gli header NumPy vengono letti prima di allocare gli array, confrontando dimensioni, dtype e byte effettivamente disponibili. La lettura verifica l'annullamento durante lo streaming.

Apertura, verifica e digest sono eseguiti in un worker. Il dialogo modale lascia elaborare gli eventi GUI e permette l'annullamento; un flag impedisce modifiche e sostituzioni rientranti del progetto durante l'attesa. Il chiamante Python può passare limiti di lettura/validazione maggiori per dati grandi fidati.

**Perché risolve.** Dimensioni dichiarate enormi non innescano un'allocazione preventiva incontrollata e l'I/O non monopolizza il thread GUI. I limiti sono espliciti e verificabili, non basati su un rapporto di compressione che penalizzerebbe anche dati scientifici legittimamente molto comprimibili.

**Verifica.** Budget ridotti rifiutano gli archivi prima del caricamento; una shape falsificata da mille miliardi di elementi viene rifiutata senza allocarla. Il test GUI osserva eventi durante la lettura, blocca un nuovo progetto e verifica il ripristino del flag dopo la fine.

## 20. Budget delle espressioni matematiche

**Modifica.** Alla whitelist sintattica si aggiungono limiti di sorgente, nodi e profondità: 16.384 caratteri, 2.048 nodi, profondità 64. Gli interi sono limitati a 4.096 bit e le potenze vengono controllate prima del calcolo. Gli array hanno un limite di 10 milioni di elementi e una valutazione ha un budget aggregato di 50 milioni di elementi. La shape di broadcasting è controllata prima dell'allocazione, anche per confronti, condizioni e funzioni.

**Perché risolve.** Espressioni brevi come potenze annidate non possono richiedere interi arbitrariamente grandi; due input piccoli con shape incompatibili con il budget non generano un risultato enorme tramite broadcasting.

**Verifica.** Rifiuto di `2**100000`, `10**(10**10)`, sorgente eccessiva e broadcasting oltre il limite. Le normali formule vettoriali e i test delle funzioni restano validi. Questi budget riguardano l'interprete matematico incorporato, non impongono una scadenza del sistema operativo al codice arbitrario di un plugin fidato.

**Codice:** [SafeExpression](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/expressions.py).

## 21. Manuale beta non allineato al sorgente

**Modifica.** Il job documenti installa la toolchain e costruisce TeX/PDF dal Markdown del checkout testato, in una directory temporanea. Solo dopo la generazione e la verifica degli input prepara i quattro documenti attesi. Toolchain mancante, sorgente non valido o generazione fallita bloccano il job e quindi la pubblicazione: non si ripiega sul PDF committato precedente. Il timeout del job documenti è adeguato alla compilazione. Il generatore accetta anche directory di output esterne al repository.

Guide Python/YAML, audit per automazione e appendici incorporate nel manuale sono stati aggiornati alle nuove semantiche. Non sono state riscritte le edizioni stabili tracciate PDF/TeX né la versione stabile.

**Perché risolve.** Il nome beta non viene più applicato automaticamente a un manuale preso da un'altra edizione: il contenuto proviene dal sorgente corrente.

**Verifica.** Il test controlla l'invocazione del generatore, usa testo corrente differente dai documenti stabili e verifica che gli output contengano quel testo lasciando intatti gli input stabili. Mancanza di input non produce output parziale. Tutti i test release/canali/workflow e coerenza documentale passano.

**Limite della verifica locale:** `pandoc`, `latexmk` e `xelatex` non sono installati su questa macchina. Non è stato eseguito qui un build PDF reale; sono verificati il sorgente, l'orchestrazione e il comportamento in caso di errore. La pipeline installa esplicitamente gli strumenti necessari.

**Codice:** [beta_release.py](/home/seb/.codex/worktrees/458d/curvemole/.github/scripts/beta_release.py), [testing.yml](/home/seb/.codex/worktrees/458d/curvemole/.github/workflows/testing.yml), [build_manual.py](/home/seb/.codex/worktrees/458d/curvemole/scripts/build_manual.py).

## 22. Duplicazioni e sostituzioni implicite dei metodi

**Modifica.** Sono consolidati i casi individuati nell'audit:

- `Fitter._fit_sequential` delega esplicitamente all'implementazione canonica; rimossi il vecchio corpo duplicato e la sostituzione implicita all'import.
- Editor singolo e multiselezione chiamano la stessa routine di validazione, ripristino e undo dei parametri.
- L'installer canonico dei punti manuali richiama esplicitamente il supporto live; non viene più sostituita la funzione installer di un altro modulo.
- `UpdateController` instrada esplicitamente download e installazione Windows; rimossi i wrapper che alteravano i suoi metodi e il vecchio ramo Windows duplicato.
- SHA-256 nativo PowerShell è generato direttamente nell'helper canonico. Il modulo di compatibilità rimane un semplice re-export, senza una seconda trasformazione testuale dello script.

**Perché risolve.** Nei percorsi segnalati c'è un'unica implementazione del comportamento e un richiamo visibile, anziché una versione che viene soppiantata successivamente. I controlli di modifica dei parametri non possono divergere fra editor per copia del medesimo blocco.

**Verifica.** Suite completa, inclusi propagazione sequenziale, multiselezione, punti manuali, configurazione delle funzioni e updater. Gli altri installer GUI storici restano parte della composizione dell'interfaccia: questo è un consolidamento dei duplicati segnalati, non una conversione dell'intera GUI a un'altra architettura.

**Codice:** [fitting](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/fitting.py), [sequential_fit](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/core/sequential_fit.py), [MainWindow](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/gui/main_window.py), [multiselezione](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/gui/model_multiselect.py), [punti manuali](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/gui/manual_points.py), [updater Windows](/home/seb/.codex/worktrees/458d/curvemole/src/curvemole/gui/windows_update_fix.py).

## Verifiche, evidenze e limiti pratici

La suite finale è stata eseguita con Python 3.14.8, NumPy 2.4.6, SciPy 1.17.1, pandas 2.3.3, PySide6 6.11.2 e pyqtgraph 0.14.0, usando Qt offscreen e preferenze isolate. L'esecuzione fuori dal sandbox consente ai test desktop di creare i socket Qt locali. Nessun test dipendente da quei socket è rimasto classificato come errore del prodotto.

Il lint dei workflow è stato eseguito su tutti i file. Actionlint 1.7.12 segnala come sconosciuto `concurrency.queue`, che è invece documentato da [GitHub](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency?apiVersion=2022-11-28); il limite è segnalato anche nell'[issue upstream](https://github.com/rhysd/actionlint/issues/746). È stata esclusa soltanto quella diagnosi specifica, mantenendo tutti gli altri controlli. Non è stato rimosso `queue` dai workflow per adattarli a un linter in ritardo.

Comando di test:

```bash
PYTHONPATH=src QT_QPA_PLATFORM=offscreen CURVEMOLE_DISABLE_UPDATE_CHECK=1 \
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m pytest -q --tb=short
```

I limiti nuovi possono respingere input che prima tentavano di consumare risorse illimitate; un profilo non supportato viene segnalato come tale. Sono scelte intenzionali, documentate. Le approssimazioni statistiche restano tali: queste correzioni eliminano le incoerenze riprodotte, non certificano automaticamente la validità scientifica di qualsiasi modello o dataset.

Gli artefatti di verifica locali comprendono il log della suite finale, i risultati numerici prima/dopo, il sorgente del benchmark e i log di lint. Il PDF reale e l'installer reale Windows restano le due verifiche di piattaforma/toolchain non effettuate qui. Nessun workflow remoto è stato avviato.

Evidenze: [log completo dei test](/home/seb/.codex/visualizations/2026/10/30/01a18c7d-2867-70a1-af48-28cb565c5b15/curvemole-fixes-2026-11-02/pytest-final.log), [metriche numeriche e memoria](/home/seb/.codex/visualizations/2026/10/30/01a18c7d-2867-70a1-af48-28cb565c5b15/curvemole-fixes-2026-11-02/verification_metrics.json), [patch locale](/home/seb/.codex/visualizations/2026/10/30/01a18c7d-2867-70a1-af48-28cb565c5b15/curvemole-fixes-2026-11-02/applied-changes.patch).
