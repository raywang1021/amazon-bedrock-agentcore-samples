# FAQ

> [繁體中文版](faq-zh.md)

## Why use an Agent instead of a Python script calling Claude directly?

If the requirement is a fixed single task (e.g., batch-evaluating GEO scores for a list of URLs), calling the Bedrock API directly from a script is faster and simpler — just one Claude call.

The value of an Agent framework lies in:

- **Intent detection**: The same entry point can rewrite content, evaluate scores, or generate llms.txt — the model decides which tool to call based on natural language input
- **Multi-step tasks**: A user can say "evaluate this URL first, then rewrite its content," and the agent chains multiple tools together
- **Conversational interaction**: Users can follow up, add requirements, and the agent maintains context

The trade-off is an extra Claude call for intent detection. If your scenario doesn't need this flexibility, a direct script is the better choice.

See the [Architecture doc](architecture.md#agent-tool-invocation-flow) for detailed invocation flow diagrams.

## Strands `@tool` vs MCP

This project's tools are defined using Strands' `@tool` decorator, running in the same process as the agent. Each call is a Python function call with no extra network overhead.

MCP (Model Context Protocol) is a standardized client/server protocol where tools run on separate servers. Each call has I/O overhead, but the benefit is that any MCP client can connect. For this project, tools don't need to be shared with other clients, so `@tool` is more straightforward.

## Why is sanitize needed? Isn't AgentCore / Guardrail enough?

`sanitize_web_content()` defends against **indirect prompt injection** — attackers embed malicious instructions in web content that gets fed into the LLM prompt via tools.

Attack path:

```
Malicious website (hidden text "ignore all previous instructions...")
  → fetch_page_text()
  → Agent tool injects content into prompt
  → LLM hijacked, produces polluted HTML
  → Stored in DDB → Distributed at scale via CloudFront CDN
```

AgentCore is the runtime/hosting layer — it doesn't filter prompt content passed in by tools. Bedrock Guardrail is designed for content safety (PII, hate speech, etc.), not prompt injection prevention.

So sanitize and Guardrail are complementary:

| Protection Layer | Defends Against | Position |
|-----------------|-----------------|----------|
| `sanitize.py` | Indirect prompt injection (from web content) | Tool layer, before LLM sees it |
| Bedrock Guardrail | Content safety (PII, hate speech, explicit content, etc.) | LLM layer, filters input/output |

sanitize does three things:
1. **Strip HTML comments** — attackers often hide instructions in `<!-- ... -->`
2. **Remove invisible unicode** — zero-width characters can bypass regex detection
3. **Redact known injection patterns** — `ignore all previous instructions`, `[INST]`, `<<SYS>>`, etc.

Protected targets: directly protects the LLM from hijacking; ultimately protects AI search engines and their users who receive GEO content via CloudFront. Any system feeding untrusted external content into an LLM needs this layer of protection.
