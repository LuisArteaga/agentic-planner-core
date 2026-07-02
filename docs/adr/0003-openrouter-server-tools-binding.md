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

### Option 3: Eigene `ChatOpenRouter`-Klasse mit `bind_tools` Override (Gewählt)
Wir erstellen eine Unterklasse von `ChatOpenAI`, die `bind_tools` überschreibt. Wenn sie ein OpenRouter Server-Side Tool erkennt, bindet sie dieses direkt über `self.bind(tools=[...])` ohne die standardmäßige Funktions-Validierung von LangChain.
* **Vorteil**: Ermöglicht die dynamische Tool-Bindung im Code, schützt die Parameter-Injektion für den Strict-Modus und bypass-t die Validierung fehlerfrei.
* **Nachteil**: Koppelung an die interne Struktur von LangChains `bind()` Methode (Rückgabe von `RunnableBinding`).

## Entscheidung
Wir wählen **Option 3**. Die Klasse `ChatOpenRouter` überschreibt `bind_tools` und leitet OpenRouter Server-Tools direkt an die `bind`-Methode weiter.

## Konsequenzen
* **Positiv**: Das Tool `openrouter:web_search` wird erfolgreich gebunden und auf OpenRouter-Servern ausgeführt. Der Strict-Modus wird durch Parameter-Injektion voll unterstützt.
* **Negativ**: Zukünftige LangChain-Updates, die die Signatur oder das Verhalten von `bind` verändern, könnten diese Koppelung brechen und Anpassungen erfordern.
