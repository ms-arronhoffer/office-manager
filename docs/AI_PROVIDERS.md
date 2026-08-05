# AI Provider Configuration

Portfolio Desk supports Gemini, OpenAI, and OpenRouter for AI-assisted lease ingestion, maintenance triage, reporting, and portfolio questions. Provider selection is deployment-wide. Generation and embeddings can use different providers.

## Architecture

The application keeps feature prompts and document orchestration in `backend/app/services/ai_service.py`. That service normalizes provider authentication, request payloads, responses, usage metadata, retries, and errors. Existing AI endpoints continue to expose the selected model in their responses. `GET /api/v1/ai/status` also reports the generation and embedding providers.

Supported generation providers:

| Provider | `AI_PROVIDER` | API key | Model example |
| --- | --- | --- | --- |
| Google Gemini | `gemini` | `GEMINI_API_KEY` | `gemini-3.1-flash-lite` |
| OpenAI | `openai` | `OPENAI_API_KEY` | `gpt-4.1-mini` |
| OpenRouter | `openrouter` | `OPENROUTER_API_KEY` | `anthropic/claude-sonnet-4` |

Use model identifiers available to your account. Model availability, pricing, context limits, structured-output behavior, vision support, and retention policies are provider controlled and can change independently of this app.

## Common Settings

```dotenv
AI_PROVIDER=openai
AI_MODEL=gpt-4.1-mini
AI_MODEL_FAST=gpt-4.1-nano

AI_EMBED_PROVIDER=openai
AI_EMBED_MODEL=text-embedding-3-small
AI_EMBED_DIMENSIONS=768

AI_TIMEOUT_SECONDS=60
AI_MAX_RETRIES=2
AI_RETRY_BASE_SECONDS=0.5
```

`AI_MODEL_FAST` is optional. When blank, low-cost tasks use `AI_MODEL`.

`AI_EMBED_DIMENSIONS` must remain `768`. The existing PostgreSQL columns and HNSW indexes are `vector(768)`. The application validates returned vectors and rejects a mismatched provider response before it reaches storage.

## OpenAI

1. Create an OpenAI project and API key.
2. Configure project billing and usage limits.
3. Store the key in the deployment secret store, not in source control.
4. Configure generation and embeddings:

```dotenv
AI_PROVIDER=openai
AI_MODEL=gpt-4.1-mini
AI_MODEL_FAST=gpt-4.1-nano
OPENAI_API_KEY=replace-with-secret
OPENAI_API_BASE=https://api.openai.com/v1

AI_EMBED_PROVIDER=openai
AI_EMBED_MODEL=text-embedding-3-small
AI_EMBED_DIMENSIONS=768
```

The embedding request explicitly asks OpenAI for 768 dimensions so existing search indexes remain compatible.

## OpenRouter

OpenRouter uses an OpenAI-compatible chat-completions API. Model IDs include a provider namespace.

```dotenv
AI_PROVIDER=openrouter
AI_MODEL=anthropic/claude-sonnet-4
AI_MODEL_FAST=openai/gpt-4.1-mini
OPENROUTER_API_KEY=replace-with-secret
OPENROUTER_API_BASE=https://openrouter.ai/api/v1
OPENROUTER_SITE_URL=https://portfolio.example.com
OPENROUTER_APP_NAME=Portfolio Desk
```

`OPENROUTER_SITE_URL` and `OPENROUTER_APP_NAME` are sent as `HTTP-Referer` and `X-Title` attribution headers.

OpenRouter embeddings can be selected independently from the Gemini document fallback. Use an embedding model exposed by your OpenRouter account:

```dotenv
AI_EMBED_PROVIDER=openrouter
AI_EMBED_MODEL=openai/text-embedding-3-small
AI_EMBED_DIMENSIONS=768

# Gemini remains available only for scanned/image-only PDF transcription.
GEMINI_API_KEY=replace-with-secret
GEMINI_MODEL=gemini-3.1-flash-lite
```

Embedding availability varies by OpenRouter model and route. If the selected
OpenRouter embedding model does not support a 768-dimension request, use OpenAI
directly for embeddings or migrate the pgvector schema before changing width.

## Gemini Compatibility

Existing installations do not need to change immediately. When `AI_PROVIDER` is blank, the application uses the legacy Gemini settings:

```dotenv
AI_PROVIDER=
GEMINI_API_KEY=replace-with-secret
GEMINI_MODEL=gemini-3.1-flash-lite
GEMINI_EMBED_MODEL=gemini-embedding-001
```

Setting `AI_PROVIDER=gemini` explicitly is preferred for new deployments.

## Document Capabilities

Text-bearing PDF, Word, spreadsheet, CSV, and text documents are extracted locally and sent as text, which works across all providers.

Images are sent as data URLs to OpenAI-compatible models. Select a model with vision support when image ingestion is required.

Scanned or image-only PDFs use Gemini's inline PDF processing. When OpenAI or OpenRouter is selected for generation, Portfolio Desk automatically uses the separately configured `GEMINI_API_KEY` and `GEMINI_MODEL` for transcription, then returns extracted text to the normal provider-neutral workflow. This fallback does not change `AI_EMBED_PROVIDER`; OpenRouter embeddings remain on OpenRouter. Without Gemini fallback credentials, upload an OCR or text-bearing PDF instead.

Structured-output features require a model that supports JSON-object response format through the selected endpoint. Test a candidate model against lease parsing and ticket triage before production rollout.

## Deployment

The provider variables are passed through `docker-compose.yml`, `docker-compose_local.yml`, and `docker-compose.prod.yml`. Restart the backend after changing provider configuration:

```powershell
docker compose -f docker-compose.prod.yml up -d --force-recreate backend
```

Confirm the active configuration with an authenticated request to:

```text
GET /api/v1/ai/status
```

The response includes `configured`, `provider`, `model`, `embedding_provider`, and `embedding_model`. It never returns API keys.

## Switching Embedding Models

Changing the embedding provider or model changes vector semantics even when the width remains 768. Rebuild the organization knowledge indexes after a change so stored document vectors and query vectors come from the same model. Until reindexing completes, keyword search remains available.

Do not set a dimension other than 768 without a database migration that:

1. Drops the existing HNSW indexes.
2. Recreates both embedding columns at the new width.
3. Clears incompatible JSON and pgvector embeddings.
4. Recreates the HNSW indexes.
5. Reindexes every organization.

## Rollout and Rollback

Recommended rollout order:

1. Deploy the provider-neutral code while retaining Gemini configuration.
2. Configure the new provider in staging.
3. Verify status, lease parsing, triage, reports, token metering, and RAG.
4. Rebuild embeddings if the embedding model changed.
5. Promote the same secret and model settings to production.

To roll back, restore the previous `AI_PROVIDER`, model, and API key settings, restart the backend, and rebuild embeddings if the embedding model changed.

Provider keys must remain deployment secrets. Logs and error responses are designed not to include credentials, but provider request content may contain lease or operational data. Review the selected provider's data-use and retention terms before enabling it for production documents.
