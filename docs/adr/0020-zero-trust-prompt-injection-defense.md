# 0020 - Zero-Trust Prompt-Injection-Defense für den Refinement-Subgraphen

* **Status**: Accepted
* **Datum**: 2026-07-21
* **Entscheidungsträger**: Luis Arteaga / Antigravity

## Kontext und Problemstellung

Phase 3 (Autonome Verfeinerung & Veröffentlichung) nimmt nicht vertrauenswürdige
externe Inhalte auf — OpenRouter-Websuch-Snippets und Direkt-URL-Abrufe. Eine
bösartige Quelle kann eine indirekte Prompt-Injektion enthalten, die den Planner
dazu manipuliert, eine vergiftete implementation-ready-Aufgabe auszugeben. Da
veröffentlichte Aufgaben das `agent-ready`-Label tragen und von einem autonomen
Developer-Agent konsumiert werden, entsteht eine Multi-Agent-Angriffskette
(`Angreifer → Web/Repo-Inhalt → Planner → verfeinerte Aufgabe → Developer-Agent → Systemkompromittierung`).

Die bestehende `strict`-Quellen-Whitelist (ADR-0002) ist eine strukturelle
Kontrolle, die die meisten Injektionen *an der Quelle* verhindert, aber nicht
vollständig: allowlistete Domains (z. B. `github.com`, `arxiv.org`) können
dennoch nutzergenerierte Inhalte (Issue-Bodies, Kommentare, Preprint-PDFs)
hosten, die eine Injektions-Payload tragen. Wir brauchten eine explizite
Verteidigungsschicht für das Restrisiko.

## Entscheidung

Wir übernehmen eine Defense-in-Depth-Rangfolge innerhalb des
Refinement-Subgraphen, zwischen `evaluate_grade` und `apply_decision`:

1. **Strukturelle Trennung (primär, bestehend)** — externe Inhalte werden als
   DATA, nicht als Instruktion behandelt; die `strict`-Whitelist (ADR-0002)
   begrenzt die Quellen-Oberfläche.
2. **LLM-Sicherheitsrichter (primär, neu)** — ein `security_audit`-Knoten ruft
   ein günstiges, instruktionsfolgendes LLM mit einem strukturierten
   `SecurityAuditResult`-Schema über die Such-Snippets + abgeleiteten Vorschläge
   auf; bei Erkennung sperrt er die betroffene Quelle (Blacklist).
3. **HITL-Veröffentlichungs-Tor (primär, neu)** — eine optionale Bestätigung
   vor dem GitHub-API-Aufruf (`--interactive` / `--yes` /
   `[security].require_approval`).
4. **Regex-Vorfilter (nur best-effort)** — eine kleine, präzise
   Pattern-Liste. Im Modus `normal` werden Regex-Treffer nur protokolliert und
   sperren allein nie eine Quelle; im Modus `strict` tragen sie zur Sperr-Entscheidung
   bei. Wir lehnen es ausdrücklich ab, den Regex als primäre Verteidigung zu
   behandeln (Blacklisting über eine Denylist ist fragil und trivial umgehbar).

Ein Selbstheilungs-Loop stützt den Richter: bei Erkennung wird die betroffene
Quelle gesperrt und der Graph tritt erneut in `web_search` ein, welches die
akkumulierten Ergebnisse gegen die Blacklist **filtert** (kein Re-Fetch —
erneutes Suchen derselben Queries würde dieselbe indizierte Quelle
zurückliefern). Nach `max_security_retries` (2) oder wenn keine sauberen
Ergebnisse verbleiben, fällt der Subgraph in die **Offline-Verfeinerung** zurück
(externe Ergebnisse verworfen, nur lokale ADRs). Ein pro-Durchlauf
Markdown-Sicherheitsbericht wird nach `.planner/reports/<repo>/` geschrieben.

## Betrachtete Optionen

- **Regex-Sanitizer als primäre Verteidigung (Issue §2.A ursprünglich).**
  Abgelehnt: eine Blacklist von Phrasen wie „ignore previous instructions" ist
  High-Recall / Low-Precision und trivial umgehbar (Synonyme, Encoding,
  Verschleierung). OWASP A03:2021 und die Prompt-Injection-Literatur bevorzugen
  konsequent Allowlisting / strukturelle Kontrollen über Blacklisting.
  Herabgestuft zu einem optionalen Vorfilter.
- **LangGraph `interrupt()` für das HITL-Tor.** Vorerst abgelehnt: der
  Refine-Graph wird synchron von der CLI ohne Checkpointer aufgerufen. Ein
  fortsetzbares Interrupt würde Persistenz (einen Checkpointer) und eine
  `Command(resume)`-Treiber-Schleife erfordern — echter Aufwand für eine
  One-Shot-Batch-CLI. Eine synchrone `input()`-Abfrage vor dem API-Aufruf ist
  die angemessene Lösung; sie auto-genehmigt (mit Warnung), wenn stdin kein TTY
  ist, sodass CI-Läufe nicht hängen.
- **Re-Fetch beim Retry.** Abgelehnt: identische Queries liefern dieselbe (nun
  gesperrte) indizierte Quelle. Das Filtern der akkumulierten Ergebnisse ist
  billiger, deterministisch und entspricht der Issue-Semantik
  („search tools filter out blacklisted sources").

## Konsequenzen

* **Positiv:** Defense-in-Depth, die sich nicht auf eine einzige fragiles
  Kontrolle verlässt; der LLM-Richter fängt semantische Injektionen, die Regex
  und Whitelist verfehlen; der Offline-Fallback garantiert, dass der Batch
  dennoch eine (nur lokale) Aufgabe produziert, anstatt den nachgelagerten
  Agent zu vergiften; ein pro-Durchlauf-Bericht gibt menschliche
  Nachvollziehbarkeit.
* **Negativ:** der Subgraph erhält einen zusätzlichen LLM-Aufruf pro Entwurf
  (abgemildert durch das günstige Modell + den `audit_level=off`-Escape-Hatch
  und das Trivialitäts-Gate); ein zusätzlicher Knoten + bedingte Kante macht
  die Topologie komplexer; die `sanitized_search_results`-Sicht wurde
  eingeführt, damit der Audit-/Filter-Pfad wirksam wird, ohne den
  `search_results`-Akkumulations-Reducer (ADR-0013) zu stören — nachgelagerte
  Knoten müssen über `active_search_results` lesen.

## Inspiration & Referenzen

* **Google DeepMind — „Securing the future of AI agents" / „Three Layers of
  Agent Security"** (Multi-Layer-Agent-Sicherheit: einzelne Agenten,
  Multi-Agent-Systeme, Ermächtigung der Verteidiger).
  https://deepmind.google/blog/securing-the-future-of-ai-agents
* **Google — „Mitigating prompt injection attacks with a layered defense
  strategy"** (Model-Hardening + ML-basierte Injektions-Klassifikatoren +
  System-Level-Safeguards; untermauert Defense-in-Depth über einen einzelnen
  Filter). https://blog.google/security/mitigating-prompt-injection-attacks
* **OWASP Top 10 for LLM Applications (LLM01: Prompt Injection)** und
  **OWASP A03:2021 (Injection)** — Blacklisting/Denylisting ist fragil;
  Allowlisting und strukturelle Kontrollen werden bevorzugt.
  https://genai.owasp.org/
* **LangGraph Human-in-the-Loop** — `interrupt()` / `Command(resume)` ist das
  idiomatische fortsetzbare HITL-Pattern; wir verzichten bewusst zugunsten
  einer synchronen Abfrage für die Batch-CLI.
  https://docs.langchain.com/oss/python/langchain/human-in-the-loop
* **Issue #51 Pre-Selection-Verdict** — kürzte den duplikativen
  YAML→TOML-Abschnitt (bereits in #59 / ADR-0016 erledigt) und stufte die
  Verteidigungen neu (Struktur + LLM-Richter + HITL primär; Regex optionaler
  Vorfilter).
