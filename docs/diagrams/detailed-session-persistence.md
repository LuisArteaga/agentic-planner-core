# Detailed view — session persistence and resuming

How the interactive commands (`grill`, `verify`) persist every conversation
turn to plain JSON and how an interrupted session is resumed.

> **Reflects:** behavior on `main` as of 2026-09-12. Grounded in the sources
> below; where an ADR and the code disagree, this diagram follows the code and
> the mismatch is flagged under **Sources**.

## Diagram

```mermaid
flowchart TD
    START["python -m planner grill or verify<br/>optional --session-id flag"]
    SCAN{"Incomplete sessions found ?<br/>.planner/sessions/repo/<br/>scanned per command prefix<br/>sorted by last_modified descending"}
    MENU["Interactive menu<br/>pick an incomplete session or start new"]
    LOAD["Load the --session-id file directly"]
    NEW["Start a fresh session"]
    RESUME{"Resumed and last message is an AIMessage ?"}
    SKIP["Skip the first agent turn<br/>continue directly at user input"]
    NOSKIP["Run the agent turn first"]
    LOOP["Interactive turns<br/>user input and agent reply"]
    SAVE["save_session after every turn<br/>serialize_messages keeps type - content -<br/>tool_calls - tool_call_id - name"]
    FILE["JSON file<br/>prefix_session_id.json<br/>prefix is grill_ or verify_"]
    FIN["finish_session tool marks the session completed<br/>it no longer appears in the resume menu"]
    START --> SCAN
    SCAN -->|Yes and no --session-id| MENU
    SCAN -->|Yes and --session-id| LOAD
    SCAN -->|No| NEW
    MENU --> RESUME
    LOAD --> RESUME
    NEW --> LOOP
    RESUME -->|Yes| SKIP
    RESUME -->|No| NOSKIP
    SKIP --> LOOP
    NOSKIP --> LOOP
    LOOP --> SAVE
    SAVE --> FILE
    FILE --> LOOP
    LOOP --> FIN
```

## Notes

- Custom serialization instead of library serialization (ADR-0006): plain
  stdlib `json` with an explicit field mapping (`type`, `content`,
  `tool_calls`, `tool_call_id`, `name`). The format is decoupled from
  LangChain-internal classes, so library upgrades cannot corrupt saved
  sessions; corrupt JSON files are ignored when scanning.
- The first-agent-turn skip (ADR-0007) prevents a redundant agent reaction
  (and its token cost) when the saved history already ends with an agent
  reply.
- `grill` and `verify` share exactly the same persistence and resume
  mechanism; the command type is encoded in the filename prefix
  (`grill_`, `verify_`).

## Sources

- ADR-0006 — custom JSON session serialization:
  [../adr/0006-custom-json-session-serialization.md](../adr/0006-custom-json-session-serialization.md)
- ADR-0007 — interactive session resuming:
  [../adr/0007-interactive-session-resuming.md](../adr/0007-interactive-session-resuming.md)
- Implementation: [../../planner/cli_planning.py](../../planner/cli_planning.py)
  (`serialize_messages`, `deserialize_messages`, `save_session`,
  `load_or_select_session`, `run_interactive_console_loop`)
- Glossary anchors (CONTEXT.md): *Sitzungs-Serialisierung (Session
  Serialization)*, *Grill-Session (Grill Session)* —
  [../../CONTEXT.md](../../CONTEXT.md)
