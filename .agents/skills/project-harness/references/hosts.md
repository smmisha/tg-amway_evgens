# Host capability guidance

Use current host documentation and tool schemas. Examples here describe decisions, not fixed tool names.

## Capability discovery

Before relying on a mechanism, establish whether the current environment provides:

- permitted file read and write;
- command or code execution;
- network research;
- visual inspection;
- subagents or separate tasks;
- connectors and external accounts;
- persistent project storage.

Availability is not authorization. A visible connector or executable does not grant permission to publish, spend money, send data, or make destructive changes.

## Degradation rules

| Missing capability | Behavior |
|---|---|
| File write | Keep a compact record in context and return a continuation packet. Do not claim persistent state. |
| Command execution | Inspect what can be inspected; provide exact unexecuted checks and label them unrun. |
| Network | Do not claim freshness. Continue work independent of current external facts and identify the affected assertions. |
| Visual inspection | Do not claim visual acceptance. Use structural checks where useful and disclose the missing observation. |
| Subagents | Execute sequentially. Self-review is not independent review. |
| Connector or account | Prepare the local result and stop the dependent external action at the missing capability or permission. |

## Host mapping

In Codex, use only tools exposed to the current task and respect sandbox and approval behavior. In Claude Code, use only its currently available file, shell, browser, and agent mechanisms. On another Agent Skills host, inspect capabilities instead of importing assumptions from Codex or Claude.

Host-specific metadata such as `agents/openai.yaml` may be ignored by another host without making the portable instructions invalid.
