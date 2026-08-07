# 0012 - url_citation Annotation Capture via ChatOpenAI Subclass

* **Status**: Accepted
* **Datum**: 2026-08-06
* **Entscheidungsträger**: Luis Arteaga

## Kontext und Problemstellung

OpenRouter liefert Web-Suchergebnisse nicht als strukturierten Textblock aus, sondern als
`url_citation`-Annotations im `message.annotations`-Array der Chat-Completions-Antwort (siehe
[OpenRouter — Parsing web search results](https://openrouter.ai/docs/guides/features/plugins/web-search#parsing-web-search-results)).
Der `web_search`-Knoten leitete seine `search_results` bisher aus einem vom Modell transkribierten
JSON-Block im Prosa-Content ab (`json.loads(extract_json_block(...))`). Liefert das Modell keinen
Block, schlug `json.loads` fehl (`JSONDecodeError`) und der Knoten maskierte den Fehler als
`"status": "success"` (Issue #54).

Die zentrale Schwierigkeit: **langchain-openai 1.3.3 verwirft die `annotations` im
Chat-Completions-Modus vollständig.** `_convert_dict_to_message` (`langchain_openai/chat_models/base.py`)
liest für `role == "assistant"` nur `content`, `function_call`, `tool_calls` und `audio` —
`message.annotations` wird ignoriert und landet weder auf `additional_kwargs` noch in
`response_metadata`. Dies wurde experimentell verifiziert (typisierte `ChatCompletion` mit
Annotations → `AIMessage.additional_kwargs == {}`). Die LangChain-Referenz selbst rät für
OpenRouter zum provider-spezifischen Paket. **Aber auch `langchain-openrouter` 0.2.7
(`ChatOpenRouter`)** wertet `annotations` nicht aus (Quellcode-Inspektion: kein Handler).
Ein Wechsel auf `ChatOpenRouter` würde Bug 1 also nicht lösen.

Da [ADR-0003](./0003-openrouter-server-tools-binding.md) bewusst Chat-Completions +
`model.bind(tools=..., tool_choice=...)` ohne Subklasse wählt, brauchen wir einen Weg, die
Annotations dennoch zugänglich zu machen.

## Entscheidungsfaktoren (Drivers)

* Issue #54 AC: `search_results` müssen aus `url_citation`-Annotations stammen, nicht aus einem
  modellseitigen JSON-Block; eine leere/unparsierbare Antwort darf kein `JSONDecodeError` loggen.
* Beibehaltung der ADR-0003-Tool-Bindung (`model.bind` ohne `bind_tools`-Override).
* Erhalt der LangChain-Telemetrie/Callbacks/Token-Tracking für den `web_search`-LLM-Aufruf.
* Robustheit gegenüber künftigen langchain-openai-Versionen.

## Betrachtete Optionen

### Option 1: Minimale `ChatOpenAI`-Subklasse mit `_create_chat_result`-Override
Eine Subklasse `OpenRouterAnnotationChatOpenAI` überschreibt ausschließlich `_create_chat_result`,
liest `choices[0].message.annotations` VOR der konvertierungsschritt-beendenden Base-Methode und
schreibt die (zu dicts normalisierten) Annotations auf
`AIMessage.additional_kwargs["annotations"]`.
* **Vorteil**: Kleinster Delta; erhält Telemetrie/Callbacks/Token-Tracking und die
  `get_llm`-Konfiguration; Override ist ein No-op für Antworten ohne Annotations (sicher für alle
  Knoten); testbar (Mock einer typisierten `ChatCompletion`).
* **Nachteil**: Koppelung an die private Methode `_create_chat_result` (abgemildert durch
  defensives `try/except`); berührt das in ADR-0003 abgelehnte Thema „Subklasse".

### Option 2: Direkter OpenAI-SDK-Aufruf im `web_search`-Knoten
Den `openai.OpenAI`-Client direkt nutzen und `response.choices[0].message.annotations`
typsicher auslesen.
* **Vorteil**: Keine Subklasse; robust typisierte Annotations.
* **Nachteil**: Verliert LLM-Level-Telemetrie/Callbacks; reimplementiert Request-Building
  (Model, `extra_body`/Provider-Routing, Timeout, Retries) und bricht mit dem
  `get_llm().invoke()`-Muster aller anderen Knoten.

### Option 3: Wechsel auf die Responses API (`use_responses_api=True`)
langchain-openai erhält Annotations im Responses-Pfad als Content-Block-Annotations.
* **Vorteil**: Idiomatisch; Annotations nativ erhalten.
* **Nachteil**: Widerspricht ADR-0003; erfordert Rework des Tool-Binding-Formats
  (`openrouter:web_search` hat im Responses-API ein anderes Schema); schwer ohne echten
  API-Key zu testen; größerer Scope (Issue stuft die Migration als optional/größer ein).

### Option 4: Migration auf `langchain-openrouter` `ChatOpenRouter`
* **Vorteil**: Provider-spezifisches Paket (von LangChain empfohlen).
* **Nachteil**: **Verwirft Annotations ebenfalls** (verifiziert) — löst Bug 1 nicht; zusätzlicher
  SDK-Wechsel (`openrouter`- statt `openai`-Paket).

## Entscheidung

**Option 1** — minimale `ChatOpenAI`-Subklasse `OpenRouterAnnotationChatOpenAI`.

Dies ist **orthogonal zu ADR-0003**: ADR-0003 (Option 3 dort) lehnte eine Subklasse ab, die
`bind_tools` überschreibt, um die **Tool-Bindung**-Validierung zu umgehen. Hier wird ausschließlich
`_create_chat_result` (also **Resultat-Parsing**) überschrieben, um providerseitige Metadaten
zu retten, die die Base-Integration verwirft. Die Tool-Bindung bleibt unverändert über
`model.bind(tools=[...], tool_choice=...)` gemäß ADR-0003.

### Konsequenzen

* **Positiv**:
  - `search_results` werden kanonisch aus `url_citation`-Annotations gewonnen (Issue #54 AC).
  - Telemetrie, Callbacks und Token-Tracking bleiben erhalten; `get_llm` bleibt die einzige
    LLM-Factory (konsistent mit allen Knoten).
  - Defensive Implementierung: Annotations-Fehler brechen nie den LLM-Aufruf; fehlen
    Annotations, setzt der `web_search`-Knoten ein ehrliches Status-/Fehlersignal
    (`web_search_failed` + `web_search_error`).
* **Negativ**:
  - Koppelung an `_create_chat_result` (private Methode); mitigiert durch defensiven Code und
    Versions-Pinning. Sollte langchain-openai die Annotations künftig nativ surfacen, wird die
    Subklasse zum No-op und kann entfernt werden.

## Inspiration & Referenzen

* [OpenRouter — Parsing web search results (`url_citation` annotations)](https://openrouter.ai/docs/guides/features/plugins/web-search#parsing-web-search-results)
* [LangChain — `ChatOpenAI` reference](https://reference.langchain.com/python/langchain-openai/chat_models/base/ChatOpenAI)
  („targets official OpenAI API specifications only; non-standard fields not preserved;
  use provider-specific package for OpenRouter") und
  [LangChain — ChatOpenRouter integration](https://docs.langchain.com/oss/python/integrations/chat/openrouter)
* [LangChain — `extra_body` reference](https://reference.langchain.com/python/langchain-openai/chat_models/base/BaseChatOpenAI/extra_body)
  (Begründung für Bug 2: `extra_body` ist ein first-class-Kwarg, nicht via `model_kwargs`)
* [ADR-0003 — OpenRouter Server Tools Tool-Binding](./0003-openrouter-server-tools-binding.md)
* Issue #54 — `web_search node silently fails: JSONDecodeError masked as 'success' + extra_body misconfiguration`
