# Correzioni dell’ultimo audit scientifico — 2 novembre 2026

Le sette segnalazioni S01–S07 dell’audit scientifico sono state corrette sul ramo
`testing`. Il rilascio beta include anche le correzioni locali degli audit generali
precedenti, documentate in `audit-fixes-2026-11-02.md` e
`second-audit-fixes-2026-11-02.md`. I metadati della versione stabile rimangono 1.1.0;
la pipeline assegna la versione beta al momento della costruzione.

## S01 — Unità, scale numeriche, vincoli e griglie FFT

**Problema:** le perturbazioni del Jacobiano e alcune soglie introducevano una
scala fisica minima arbitraria. Cambiare coerentemente le unità poteva cambiare il
risultato del fit, i limiti automatici DE e le segnalazioni sui vincoli.

**Correzione:** i solver integrati lavorano su coordinate adimensionali. Le scale
si ricavano dai parametri e dai domini X/Y, rispettando le coordinate dei vincoli
dinamici; Jacobiani e covarianze vengono trasformati coerentemente nelle due
direzioni. I passi numerici rispettano la scala pertinente e la rappresentabilità
floating point. Limiti DE e diagnostica dei bounds usano queste scale. I vertici
dell’eventuale simplex fornito dall’utente rimangono espressi in unità fisiche.
La positività delle larghezze usa il minimo float64 normale, anziché epsilon.
La verifica di uniformità FFT rimuove la tolleranza assoluta di un’unità.

**Verifica:** Gaussiane con X/area riscalati di 1, 1e-9 e 1e-18 recuperano centro
normalizzato 0,4 e sigma 0,8 con fit locale e DE, senza falsi avvisi di bound.
Il controesempio di griglia `[0,1,2,4,8]*1e-18` viene rifiutato.

## S02 — Propagazione delle formule non lineari

**Problema:** per Y piccoli la perturbazione superava il valore da differenziare,
introducendo un errore enorme nelle incertezze, pur trasformando correttamente Y.

**Correzione:** una funzione numerica condivisa usa perturbazioni locali,
differenze centrate a due risoluzioni ed estrapolazione di Richardson. Il percorso
comune alle formule su coordinate/colonne e ai pesi inverso-varianza usa questa
derivata; i risultati non finiti sono rifiutati.

**Verifica:** per `z=y**3`, Y=1e-9 e sigmaY=1e-11, sigmaZ torna a 3e-29 anziché
circa 3,66685e-22. I confronti analitici coprono anche scale 1 e 1e-18.
Resta una propagazione locale di primo ordine, senza covarianze tra colonne.

## S03 — Errori dei parametri collegati

**Problema:** la secante numerica del link cubico a scala 1e-9 sovrastimava l’errore
standard di circa 89,9 volte.

**Correzione:** il gradiente usa differenze a tre punti, scale del problema,
perturbazioni compatibili con i bounds ed estrapolazione di Richardson. Il vettore
ottimo viene ripristinato dopo le valutazioni. La stessa covarianza viene propagata
con il gradiente corretto, conservando la trasformazione fisica dei vincoli.

**Verifica:** `SE(a**3)=abs(3*a**2)*SE(a)` concorda con la formula analitica a
scale 1, 1e-9 e 1e-18; anche il controllo WLS con link lineare concorda con il
riferimento indipendente. Non si tratta di intervalli esatti per modelli arbitrari.

## S04 — Centro della convoluzione su griglie pari

**Problema:** il ritaglio intero di due vettori pari introduceva mezzo campione
di spostamento, compensato dal centro fittato e quindi invisibile nei residui.

**Correzione:** con segnali di lunghezza pari i kernel sono valutati su una
griglia dispari con lag centrale esatto. Si conserva l’integrazione FFT con
spaziatura assoluta e un solo ritaglio per blocco di convoluzioni consecutive.
Rimane la convenzione del kernel riferito al punto medio del dominio. Lo stesso
percorso viene applicato ai contributi di background.

**Verifica:** il riferimento analitico di due Gaussiane restituisce centro 0,25
con 100 e 101 campioni, sia crescenti sia decrescenti; il fit non compensa più
il precedente bias di circa ±0,050505. Finestra finita e campionamento rimangono
approssimazioni che l’utilizzatore deve scegliere adeguatamente.

## S05 — Cancellazione numerica e identità casuali

**Problema:** l’accumulo semplice, ordinato secondo UUID casuali, poteva perdere
il contributo 1 in `1e16+1-1e16` e cambiare il risultato tra modelli equivalenti.

**Correzione:** i termini Add/Subtract usano somma compensata di Neumaier e
un ordine indipendente dagli UUID. Anche il background additivo usa la somma
compensata. Le operazioni globali esplicite conservano il loro ordine scelto.

**Verifica:** tutte le permutazioni del controesempio restituiscono 1 e il fit
del piccolo offset recupera 1. La compensazione migliora l’aritmetica float64,
ma non sostituisce l’aritmetica a precisione arbitraria.

## S06 — Regioni e limiti dei profili di verosimiglianza

**Problema:** il primo e l’ultimo punto accettato venivano uniti, anche attraverso
regioni escluse. La griglia troncava inoltre gli estremi di un intervallo connesso.

**Correzione:** si individuano separatamente i blocchi contigui accettati; gli
attraversamenti della soglia vengono raffinati tramite refit e ricerca di radici
in un intervallo delimitato. `confidence_regions` conserva tutte le regioni
individuate; `interval` seleziona quella contenente la stima. Regioni disconnesse
producono una valutazione Critical e vengono mostrate nel pannello. La visualizzazione
di un singolo errore ± viene sospesa quando sarebbe ambigua. Fallimenti, limiti
della scansione e raffinamenti non riusciti sono segnalati; non si attraversano
punti falliti per unire regioni. I parametri fissi sono rifiutati esplicitamente.

**Verifica:** con sigma noto e 25 osservazioni la griglia predefinita di 31 punti
restituisce ±0,391992796908, cioè ±1,95996398454 SE e copertura teorica 95% nel
riferimento normale, anziché ±1,8 SE. Nel caso `y=a**2`, zero rimane escluso:
le regioni sono circa [-1,06705,-0,92812] e [0,92812,1,06705], con stato Critical.
Una scansione finita può ancora non individuare modi remoti molto stretti;
la soglia asintotica non garantisce copertura esatta per ogni modello.

## S07 — Stato iniziale, provenienza e riesecuzione controllata

**Problema:** ripartire dal modello ottimizzato salvato non ricostruiva il calcolo
originale; per DE potevano cambiare i limiti automatici nonostante lo stesso seed.

**Correzione:** `FitResult.provenance` registra snapshot iniziali dei modelli e
vincoli, hash dei dati, ordine dei parametri, vettori iniziali, scale, limiti
risolti, metodo, impostazioni, seed e identità RNG. Sono registrati versione e
identità sorgente CurveMole, Python/NumPy/SciPy, configurazione numerica e thread,
identità delle funzioni e fingerprint delle sorgenti dei plugin/solver. Profili e
campionamenti conservano inoltre identità del baseline e configurazione effettiva.
Le repliche temporanee evitano di duplicare il registro completo quando non serve.
I record individuali selezionano i propri modelli/matrici; la propagazione
sequenziale conserva anche i modelli iniziali effettivi di ciascuna esecuzione.

`Fitter.replay(result, curves)` ricostruisce gli input iniziali e rifiuta dati,
definizioni, solver o ambiente incompatibili. `verify_environment=False` permette
un confronto esplicito tra ambienti, senza promettere identità numerica.
L’archivio salva questi record con i risultati. Gli hash non archiviano copie
separate di ogni dataset storico: occorre conservare gli input corrispondenti.
I risultati precedenti alla modifica non acquistano retroattivamente uno stato
iniziale ricostruibile. Una nuova chiamata fit sul modello corrente rimane un
nuovo calcolo, distinto dalla riesecuzione.

**Verifica:** un risultato DE salvato/caricato riproduce esattamente i vettori
iniziali, i limiti risolti e i parametri finali. Cambiamenti di dati, definizioni o
ambiente vengono rifiutati. Sono verificati anche callback individuali e baseline
sequenziali. Monte Carlo e bootstrap, fissi e adattivi, producono campioni e
checkpoint identici con uno e due processi nell’ambiente provato.

## Documentazione e validazione

Manuale Markdown/PDF/LaTeX, riferimenti Python/YAML e i due contratti AI sono
sincronizzati: i sette difetti non sono più descritti come aperti. I documenti
mantengono espliciti i limiti delle approssimazioni scientifiche.

La suite completa ha superato 1.938 test (uno specifico Windows escluso su Linux).
Dopo la piccola estensione finale al background additivo e due ulteriori test sui
record, 43 controlli mirati su regressioni e documentazione sono passati.
La verifica finale comprende anche background, aggiornamenti e canali di rilascio.
Ruff e il validatore dei workflow del repository sono stati eseguiti. Il PDF di
140 pagine è stato rigenerato e le pagine delle correzioni controllate visivamente.
La CI della beta ripete i controlli sulle piattaforme previste prima di pubblicare.
