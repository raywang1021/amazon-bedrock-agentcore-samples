# GEO Agent — Roadmap

> [繁體中文版](roadmap.zh-TW.md)

## Completed

| Phase | Description |
|-------|-------------|
| Phase 1 | Project foundation — Strands Agent + AgentCore |
| Phase 2 | Security — sanitize, guardrail, prompt injection protection |
| Phase 3 | Edge Computing — CloudFront OAC + Lambda Function URL |
| Phase 4 | Deployment — SAM template, multi-tenant DDB |
| Phase 5 | Testing — 60 unit tests, e2e test suite |
| Phase 6 | PR & Review — [PR #1](https://github.com/KenexAtWork/geoagent/pull/1) |

### Key milestones
- Agent stateless DDB decoupling (store_geo_content → geo-content-storage Lambda)
- CloudFront OAC integration into main template
- Multi-tenant DDB key format: `{host}#{path}[?query]`
- Processing timeout (5min) + stale record recovery
- Purge + CF invalidation sync
- Shared `fetch_page_text` + unified rewrite prompt
- Three-perspective GEO scoring (as-is / original / geo) with `temperature=0.1`
- Score tracking with `update_scores` action (no full-record overwrite)
- Interactive `setup.sh` with `samconfig.toml` generation
- Timeout chain alignment: client 80s < CF origin 85s < Lambda 90s

## In Progress

(none)

## Backlog

### Performance
- [ ] Sync mode optimization (currently ~30s)

### Features
- [ ] Dynamic model switching via SSM Parameter Store (avoid redeploy when changing MODEL_ID)
- [ ] Multi-language GEO content support
- [ ] GEO content versioning
- [ ] A/B testing framework for rewrite strategies
- [ ] CloudWatch Dashboard for score trends

### Operations
- [ ] Cost analysis and optimization (e.g., sampling-based scoring)
- [ ] CI/CD integration for score regression detection
