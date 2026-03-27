# GEO Agent

Generative Engine Optimization (GEO) agent deployed via Bedrock AgentCore, with CloudFront OAC + Lambda Function URL for edge serving. AI search engine crawlers receive GEO-optimized content automatically.

## Archiecture
The architecture routes AI bot traffic (e.g., GPTBot, ClaudeBot) through CloudFront to a geo-bot-router that detects bots and directs them into a GEO processing pipeline, while normal users are sent directly to the origin site; for bot requests, a Lambda-based geo-content-handler first checks DynamoDB for cached GEO content and, on a miss, fetches the original content and asynchronously triggers a geo-content-generator, which invokes a GEO Agent (AgentCore) to orchestrate LLM generation (Claude Sonnet 4 with guardrails) and optional scoring/storage via Lambda, with results written back to DynamoDB for future cache hits, enabling a low-latency, cost-efficient, edge-first design that separates routing, generation, and intelligence layers.
![image](https://github.com/user-attachments/assets/90eb5949-7b92-479d-9fe7-8422937ee642)

## Features

- **Content Rewriting**: Rewrites web content into GEO-optimized format (structured headings, Q&A, E-E-A-T signals)
- **GEO Scoring**: Three-perspective analysis (as-is / original / geo) of a URL's GEO readiness, each with three dimensions (cited_sources / statistical_addition / authoritative), using `temperature=0.1` for consistency
- **Score Tracking**: Automatically records pre/post-rewrite GEO scores to DynamoDB for optimization tracking (see [Score Tracking](docs/score-tracking.md))
- **llms.txt Generation**: Generates AI-friendly llms.txt for websites
- **Edge Serving**: CloudFront Function detects AI bots, routes to GEO-optimized content via OAC + Lambda Function URL
- **Multi-Tenant**: Multiple CloudFront distributions share a single set of Lambda + DynamoDB, isolated via `{host}#{path}` composite key
- **Guardrail (Optional)**: Bedrock Guardrail filters inappropriate content and prevents PII leakage

## Project Structure

```
src/
├── main.py                  # AgentCore entry point, Strands Agent definition
├── model/load.py            # Model ID + Region + Guardrail centralized config
└── tools/
    ├── fetch.py             # Shared web fetching (trafilatura + fallback, custom UA)
    ├── rewrite_content.py   # GEO content rewriting
    ├── evaluate_geo_score.py # Three-perspective GEO scoring (as-is / original / geo)
    ├── generate_llms_txt.py # llms.txt generation
    ├── store_geo_content.py # Fetch → Rewrite → Score → Store to DynamoDB
    ├── prompts.py           # Shared rewrite prompt
    └── sanitize.py          # Prompt injection protection

infra/
├── template.yaml                    # SAM: DynamoDB + Lambda (OAC architecture)
├── cloudfront-distribution.yaml     # CloudFormation: new CF distribution
├── lambda/
│   ├── geo_content_handler.py       # Serves GEO content (3 cache-miss modes)
│   ├── geo_generator.py             # Async invocation of AgentCore for content generation
│   ├── geo_storage.py               # Storage service for Agent writes to DDB
│   └── cf_origin_setup.py           # Custom Resource: auto-configures existing CF distribution
└── cloudfront-function/
    ├── geo-router-oac.js            # CFF: AI bot detection + Lambda Function URL origin switching
    └── template.yaml               # CFF CloudFormation template
```

## Quick Start

```bash
# 1. Environment setup
./setup.sh
source .venv/bin/activate

# 2. AWS configuration
agentcore configure

# 3. Local development
agentcore dev
agentcore invoke --dev "What can you do"

# 4. Deploy
agentcore deploy
sam build -t infra/template.yaml
sam deploy -t infra/template.yaml

# 5. Query score tracking data
python scripts/query_scores.py --stats        # Show statistics
python scripts/query_scores.py --top 10       # Top 10 improvements
python scripts/query_scores.py --url /path    # Query specific URL
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL_ID` | `us.anthropic.claude-sonnet-4-20250514-v1:0` | Bedrock model ID |
| `AWS_REGION` | `us-east-1` | AWS region |
| `GEO_TABLE_NAME` | `geo-content` | DynamoDB table name |
| `BEDROCK_GUARDRAIL_ID` | (empty) | Bedrock Guardrail ID (optional) |
| `BEDROCK_GUARDRAIL_VERSION` | `DRAFT` | Guardrail version |

## Documentation

- [Why AgentCore](docs/why-agentcore.md) — AgentCore vs direct LLM calls, Tool Selection vs MCP, three-layer trigger architecture
- [Deployment Guide](docs/deployment.md) — AgentCore, SAM, CloudFront deployment steps
- [Architecture](docs/architecture.md) — Edge Serving architecture, DDB Schema, Response Headers, HTML validation, multi-tenant
- [Score Tracking](docs/score-tracking.md) — Pre/post-rewrite GEO score recording and optimization analysis
- [FAQ](docs/faq.md) — Why use an Agent, tool invocation flow, @tool vs MCP
- [Roadmap](docs/roadmap.md) — Development progress and backlog

## Troubleshooting

### `RequestsDependencyWarning: urllib3 ... or chardet ...`

`prance` (an indirect dependency of `bedrock-agentcore-starter-toolkit`) pulls in `chardet`, which conflicts with `charset_normalizer` preferred by `requests`.

```bash
pip uninstall chardet -y
```

`agentcore dev` may reinstall it — just run the uninstall again.
