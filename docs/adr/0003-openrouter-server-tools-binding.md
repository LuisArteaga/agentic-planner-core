# 0003 - OpenRouter Server Tools Tool-Binding in LangChain

* **Status**: Accepted
* **Datum**: 2026-07-02
* **Entscheidungsträger**: Luis Arteaga

## Kontext und Problemstellung
Der Refinement Subgraph verwendet das OpenRouter Server-Side Tool `openrouter:web_search`, um Websuchen durchzuführen. Die Standard-Implementierung von `bind_tools()` in LangChains `ChatOpenAI` erwartet jedoch standardkonforme OpenAI-Funktions-Schemas, bei denen der Typ zwingend `"type": "function"` sein muss. Da OpenRouter den Typ `"type": "openrouter:web_search"` verwendet, schlägt die Standard-Validierung fehl und bricht mit einem Fehler (`Unsupported function`) ab. Wir benötigen eine Möglichkeit, OpenRouter Server-Side Tools mit ihren spezifischen Parametern (wie `allowed_domains` für den Strict-Modus) dynamisch an das Modell zu binden.

## Entscheidungsfaktoren (Drivers)
* Kompatibilität mit dem OpenRouter Server-Side Tooling-Format.
* Beibehaltung der dynamischen Tool-Bindung (`bind_tools()`) im Code.
* Einhaltung des Strict-Modus aus [ADR-0002](./0002-strict-modus-quelleneinschraenkung.md) durch Injektion der `allowed_domains`.
* Saubere und verständliche Tracing-Struktur in Langfuse.

## Betrachtete Optionen

### Option 1: Nutzung von `model_kwargs` bei der Instanziierung
Die Tools werden direkt als statischer Parameter `model_kwargs={"tools": [...]}` an den Konstruktor von `ChatOpenAI` übergeben.
* **Vorteil**: Bypasst die LangChain-Validierung ohne Code-Erweiterungen.
* **Nachteil**: Keine dynamische Bindung nach der Instanziierung möglich.

### Option 2: Nutzung eines standardkonformen Dummy-Tools (Hoisting)
Es wird ein lokales Dummy-Tool namens `web_search` definiert.
* **Vorteil**: Nutzt das Standard-Tool-Binding von LangChain.
* **Nachteil**: Keine Möglichkeit, OpenRouter-spezifische Parameter wie `allowed_domains` für den Strict-Modus sicher im API-Payload zu konfigurieren.

### Option 3: Eigene `ChatOpenRouter`-Klasse mit `bind_tools` Override
Wir erstellen eine Unterklasse von `ChatOpenAI`, die `bind_tools` überschreibt. Wenn sie ein OpenRouter Server-Side Tool erkennt, bindet sie dieses direkt über `self.bind(tools=[...])` ohne die standardmäßige Funktions-Validierung von LangChain.
* **Vorteil**: Ermöglicht die dynamische Tool-Bindung im Code, schützt die Parameter-Injektion für den Strict-Modus und bypass-t die Validierung fehlerfrei.
* **Nachteil**: Koppelung an die interne Struktur von LangChains `bind()` Methode (Rückgabe von `RunnableBinding`) und zusätzliche eigene Abstraktionsschicht.

### Option 4: Direktes Parameter-Binding (`model.bind(tools=[...])`) auf Standard-`ChatOpenAI` (Gewählt)
Wir instanziieren standardmäßig `ChatOpenAI` mit dem OpenRouter-Endpunkt und binden die Tools direkt per `.bind(tools=[tool_definition], tool_choice=...)` anstelle von `.bind_tools(...)`.
* **Vorteil**: Bypasst die standardmäßige OpenAI-Validierung in `bind_tools`, erhält die dynamische Bindung, unterstützt `allowed_domains` für den Strict-Modus und benötigt absolut keine eigene Subklasse oder benutzerdefinierten Code.
* **Nachteil**: Keine Typsicherheit bei Tool-Parametern über Pydantic (da direkt JSON-Dictionaries übergeben werden), was in diesem Fall jedoch unproblematisch ist, da die Tool-Spezifikation für `openrouter:web_search` ohnehin ein vordefiniertes JSON ist.

## Entscheidung
Wir wählen **Option 4** (Direktes Parameter-Binding per `model.bind`). Option 3 wurde ursprünglich gewählt, aber zugunsten von Option 4 verworfen, da eine eigene Subklasse unnötige Komplexität und eine enge Kopplung an LangChain-Internals einführen würde (Verstoß gegen Radical Simplicity / Lazy Coding).

## Konsequenzen
* **Positiv**: Maximale Einfachheit. Kein benutzerdefinierter Wrapper-Code zu warten. Das Tool `openrouter:web_search` wird erfolgreich gebunden und auf den OpenRouter-Servern ausgeführt. Der Strict-Modus wird durch Parameter-Injektion voll unterstützt.
* **Negativ**: Manuelle Definition der Tool-Payload-Struktur im Code, was für das statische OpenRouter-Such-Tool jedoch vernachlässigbar ist.
