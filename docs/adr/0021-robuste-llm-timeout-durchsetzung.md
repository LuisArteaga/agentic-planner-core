# 0021 - Robuste Timeout-Durchsetzung auf Transport-Ebene für LLM-Calls

* **Status**: Accepted
* **Datum**: 2026-08-13
* **Entscheidungsträger**: Luis Arteaga / Antigravity

## Kontext und Problemstellung

`python -m planner refine` konnte scheinbar endlos hängen, obwohl `get_llm()`
einen `timeout=600.0` setzte. Die Beobachtung (Issue #71): ein Prozess blockierte
nach 21 Minuten auf einem einzigen `ESTAB`-Socket zu OpenRouter (Cloudflare),
`WCHAN=poll_schedule_timeout` (Netzwerk-I/O, keine CPU-Schleife). Der konfigurierte
Timeout wurde nicht zuverlässig auf Socket-Ebene durchgesetzt.

Die Ursachenanalyse (gestützt auf LangChain- und openai-python-Dokumentation, siehe
Referenzen) ergab zwei Wurzelursachen:

1. **Retry-Multiplikation**: `ChatOpenAI.max_retries` defaultet auf `2` (3 Versuche
   insgesamt). Jeder Versuch wartet die volle Timeout-Dauer, bevor erneut versucht
  wird — `timeout=600` mit Default-Retries ergibt effektiv ~1800s pro einzelnem
   `.invoke()`. Die 21-Minuten-Beobachtung liegt exakt innerhalb dieses
   3×600s-Fensters.
2. **Unvollständige Timeout-Konfiguration**: Ein bloßer Float `timeout=600.0`
   setzt für den OpenAI-Client nur die `read`-Phase; die `connect`-Phase wird nicht
   separat begrenzt, sodass ein nicht erreichbarer Endpunkt die volle
   `read`-Budget-Dauer blockieren kann.

Zusätzlich stapeln sich innerhalb eines Drafts mehrere sequenzielle LLM-Calls
(per-Query-Fan-out in `web_search`, `propose_options` mit `thinking: max`, der
`apply_decision`-Retry-Loop). Selbst mit begrenztem Per-Call-Timeout summiert sich
das zu Stunden, wenn kein Gesamt-Budget pro Draft existiert.

Begleitsymptom: ein `CLOSE-WAIT`-Socket vom GitHub-Rate-Limit-Check, weil die
`requests`-Response nie geschlossen wurde.

## Entscheidungsfaktoren (Drivers)

* **Harte Budget-Einhaltung**: Ein nie antwortender Endpunkt muss nach ≤ Timeout
  abbrechen und den Draft als fehlgeschlagen markieren — kein unendlicher Block.
* **Fehlerisolation (ADR-0005)**: Retry-Logik auf Anwendungsseite (per-Query
  try/except in `web_search`, per-Draft try/except im Master-Loop) statt
  unsichtbares SDK-Retry-Stacking.
* **Langlebige legitime Generierungen**: `thinking: max`-Modelle benötigen Minuten
  pro nicht-streaming Call — das `read`-Timeout muss großzügig bleiben.
* **Keine Seiteneffekt-Lecks**: Ein abgebrochener Draft darf keinen verwaisten
  Worker hinterlassen, der weiterhin Issues veröffentlicht oder Dateien schreibt.

## Betrachtete Optionen

* **Option 1**: SDK-Retries belassen (`max_retries=2`) und nur Float-Timeout
  erhöhen. *Verworfen* — multipliziert weiterhin das Worst-Case-Budget und
  verletzt das „≤ Timeout"-Akzeptanzkriterium (3× Timeout).
* **Option 2**: `max_retries=0` + explizites `httpx.Timeout(connect, read, write,
  pool)` (Gewählt, Per-Call-Ebene) kombiniert mit einem harten Wall-Clock-Budget
  pro Draft via `SIGALRM` (Gewählt, Per-Draft-Ebene).
* **Option 3**: Per-Draft-Budget über `threading.Timer` / ThreadPoolExecutor +
  `future.result(timeout)`. *Verworfen* — ein Timer kann einen blockierenden Call
  in einem Geschwister-Thread nicht unterbrechen (die Exception landet im
  Timer-Thread, nicht im Main-Thread); ein verwaister Worker würde zudem weiterhin
  Seiteneffekte (Publish, Datei-Schreiben) ausführen.

## Entscheidung

Wir wählen **Option 2** auf zwei Ebenen:

1. **Per-Call-Ebene** (`get_llm`, `planner/config.py`): `max_retries=0` (kein
   silent SDK-Retry-Stacking) und `timeout=httpx.Timeout(connect=10, read=600,
   write=30, pool=30)`. Beide Werte sind über optionale `ModelConfig`-Felder
   (`timeout_seconds`, `max_retries`) pro Knoten in `config/factory.json`
   konfigurierbar. Die `read`-Phase entspricht der maximalen legitimen
   Generierungsdauer eines nicht-streaming-Calls (bis zur ersten Byte-Antwort);
   `connect`/`write`/`pool` sind eng, damit ein toter Endpunkt schnell scheitert.
   Retry-Isolation erfolgt auf Anwendungsebene (ADR-0005): transiente Fehler
   werden explizit gemacht, der Draft verbleibt auf der Festplatte für einen Rerun.
2. **Per-Draft-Ebene** (`planner/timeout.py`, `planner/refine_graph.py`): Jeder
   Subgraph-Invoke läuft unter einem `SIGALRM`-Wall-Clock-Deadline
   (`REFINE_DRAFT_BUDGET_S`, Default 1800s). `SIGALRM` unterbricht den
   blockierenden Syscall *in place* im Main-Thread und wirft eine
   `DraftTimeoutError`, die der generische `except` im Master-Loop auffängt
   (ADR-0005) — der Draft wird als fehlgeschlagen markiert, kein verwaister
   Worker, keine fortlaufenden Seiteneffekte. Außerhalb des Main-Threads ist
   `SIGALRM` nicht verfügbar; dann läuft der Draft uncapped, aber jeder
   einzelne LLM-Call bleibt durch das Per-Call-Transport-Timeout begrenzt.

Ergänzend wird der GitHub-Rate-Limit-Check (`_check_github_rate_limit`) in einen
`with session.get(...) as response:`-Kontextmanager gekapselt, sodass der Socket
sofort geschlossen wird (kein `CLOSE-WAIT`-Leak mehr).

### Konsequenzen

* **Positiv**: Ein nie antwortender Endpunkt bricht nach ≤ einer
  Read-Timeout-Periode ab; der Gesamtlauf pro Draft ist nach oben begrenzt;
  `CLOSE-WAIT`-Sockets werden nicht mehr geleakt. Fehler sind explizit und
  nachvollziehbar.
* **Negativ**: `max_retries=0` bedeutet, dass ein einzelner transienter 429/503
  auf einem Single-Call-Knoten (z. B. `propose_options`) den ganzen Draft
  fehlschlagen lässt. Das ist akzeptiert: ADR-0005 isoliert Draft-Fehler und der
  Draft bleibt für einen Rerun auf der Festplatte. `SIGALRM` ist Unix-only und
  Main-Thread-only — für die CLI (WSL2/Linux, Main-Thread) erfüllt; außerhalb
  greift der Per-Call-Timeout als Fallback.

## Inspiration & Referenzen

* **LangChain Support — „Configuring timeout for init_chat_model"**:
  `max_retries=2` (Default) × `timeout` = 3× Multiplikation; Empfehlung
  `max_retries=0` und `httpx.Timeout(connect, read, write, pool)` statt
  barem Float. <https://support.langchain.com/articles/1557730279>
* **openai-python Timeout-/Connection-Defaults**: `Timeout(timeout=600,
  connect=5.0)`, `max_retries=2`, `Limits(max_connections=1000,
  max_keepalive_connections=100)`.
  <https://leeroopedia.com/index.php/Heuristic:Openai_Openai_python_Timeout_Connection_Defaults>
* **openai-python Issue #2599 — „timeout not respected"**: Bestätigt das
  Muster, dass SDK-Retries das effektive Timeout multiplizieren.
  <https://github.com/openai/openai-python/issues/2599>
* **The Debugging Book — „Timeout" (`SignalTimeout`)**: Kanonische
  `SIGALRM`-Context-Manager-Implementierung zum in-place-Unterbrechen
  blockierender synchroner Aufrufe.
  <https://www.debuggingbook.org/html/Timeout.html>
* **Mark Story — „Building time limited workers with SIGALRM"**: Praxisbericht
  über `signal.alarm()` als primitives für harte Worker-Timeouts.
  <https://mark-story.com/posts/view/building-time-limited-workers-with-sigalrm>
* **John Paton — „Schedule the interruption of hung Python processes with
  signals"**: `SIGALRM`-Handler-Pattern zum Erzwingen eines `TimeoutError`.
  <https://johnpaton.net/posts/interrupt-long-processes>
