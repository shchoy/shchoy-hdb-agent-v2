# Issue #34: Hosted Voyage reranker to cut search latency

## What was built
Search can now rerank its 50 hybrid candidates with Voyage's hosted reranker instead of the local ONNX cross-encoder (4 to 6 s per search on CPU). The backend is chosen by `PLG_RERANK_BACKEND` (`voyage`, the default, or `local`). If Voyage fails (HTTP error, rate limit, network error, or an unreadable reply) the search keeps the hybrid order and logs a warning instead of failing the run.

## Module map
| Module | Change |
|---|---|
| `src/plg/config.py` | `rerank_backend` (`voyage` \| `local`), `voyage_rerank_model` (`rerank-2.5`). Both overridable via `PLG_*`. |
| `src/plg/search/rerank.py` | `VoyageReranker` (POST `{voyage_base_url}/rerank`, documents = `chunk.fts_text`, scores mapped back by `index`, sorted best first, fallback on error); `make_reranker(settings)` factory (Voyage needs `VOYAGE_API_KEY`); `open_searcher` uses it. |
| `src/plg/cli.py` | `plg search` builds its reranker through the shared factory; docstring no longer says cross-encoder. |
| `tests/test_voyage_reranker.py` | New: request shape, score mapping, empty input, 429/500/network/malformed-reply fallback, backend selection, missing key. Uses `httpx2.MockTransport`, no network. |
| `CLAUDE.md`, `START.md` | Updated for the new settings, backend choice and latency note. |

Existing tests and `scripts/record_sse_fixtures.py` build `CrossEncoderReranker` directly, so they are unchanged and stay offline.

## Verification
`uv run pytest`: 143 passed before the final malformed-reply fix; the reranker and CLI test files (14 tests) and `uv run mypy` pass after it. Not run against the real Voyage API.

## Next steps
- Run with a real `VOYAGE_API_KEY` and record per-search and per-stage latency in #34 (the acceptance item still open; needs timing instrumentation).
- Tune `search_candidates` (20 to 30) and pass `top_k` to the API; neither was done.
- Review judgement calls: `cli.make_reranker` is a thin wrapper over `rerank.make_reranker` (could be removed); the Voyage URL/header setup duplicates `VoyageEmbedder`; the `VOYAGE_API_KEY` check is repeated; a 401 from a bad key now degrades quietly to the hybrid order.
- Data egress: chunk text now goes to Voyage on every search by default. Confirm that is acceptable, or set `PLG_RERANK_BACKEND=local`.
