# Issue #29 — Document categories and category summaries

## What was built

- **`plg categorise`** groups the indexed documents into named categories:
  - **Grouping:** each document's vector is the normalised mean of its chunk embeddings, and HDBSCAN (scikit-learn) clusters them with `min_cluster_size = PLG_CATEGORY_MIN_SIZE` (3). Outliers are *uncategorised*.
  - **Naming:** one Haiku call (node `categorise`, forced `name_categories` tool) names every cluster. It also writes a one-line description and a short summary. The input is the cluster's titles and the opening of its most central documents.
  - **Lock:** it takes the same index lock as `plg sync`.
- **The output goes three ways:**
  1. `.plg/categories.json` (`Categorisation`): what the Library and the `category_summary` specialist read. It is replaced atomically.
  2. Chunk metadata: `SearchStore.set_category` sets `category` on every chunk. The existing `SearchFilter.category` pre-filter now has data, and `plg sync` keeps a re-indexed document's category.
  3. The entity graph: new ontology classes `DocumentCategory` and `LibraryDocument`, with `IN_CATEGORY` edges written through `GraphWriter`.
  - **IDs:** a category's ID is `CAT-` + a hash of its members. A group whose members are unchanged keeps its ID *and its name*, because Haiku is asked only about new groups. So re-running over an unchanged index changes nothing and calls no model.
  - **PII:** what Haiku wrote (it read excerpts) is passed through the tracing PII masker (NRIC/FIN, email, phone, tenant contact names) before it is saved, because every officer sees it.
  - **Write order:** the graph is written first, because it validates everything. A refusal then leaves the chunk categories and the file as they were.
- **`GET /categories`** returns the saved categorisation overlaid with the index's current documents (live titles and status; documents indexed since are uncategorised). It needs a signed-in user.
- **The Library page (`/library`)** in the web app:
  - It lists the categories, each with its description and document count. Expanding a category shows its summary and documents; superseded documents are marked, and each opens in a whole-document viewer. Uncategorised documents come last.
  - It is reached through the BFF route `/api/categories`, and every page's nav has a "Library" link.
- **The `category_summary` intent** is a new route label with a deterministic specialist (no Claude call):
  - It matches the question to a category by name and description words.
  - Merge answers from that category's saved summary and document list.
  - If no category matches, it lists the categories there are. Before any categorisation, it says to run `plg categorise`.

## How it fits the whole

- **Library:** officers can browse the corpus by topic instead of by source system.
- **Overview questions:** "Summarise the rental arrears category" gets an answer without a full knowledge search.
- **Search:** categories also live in the chunk metadata, so a knowledge search can be scoped to one.
- **Graph:** categories also live in the entity graph, so graph tooling can see which documents belong together.
- **Freshness:** the categorisation is batch output, like `plg sync`, so an administrator schedules it after the sync.

## Modules

| Path | New / modified | Role |
|---|---|---|
| `src/plg/categories/model.py` | New | `Categorisation`, `Category`, `CategoryDocument`; `overlay`; load / save (atomic) |
| `src/plg/categories/categorise.py` | New | Document vectors, HDBSCAN, Haiku naming (`name_categories`), writes file + chunk categories + graph |
| `src/plg/categories/ask.py` | New | `category_summary`: `match`, `answer` (summary + documents / category list / not categorised) |
| `ontology/plg.yaml` + `src/plg/ontology/generated/*` | Modified | `LibraryDocument`, `DocumentCategory`, `document_category` → `IN_CATEGORY` |
| `src/plg/search/store.py`, `lance.py` | Modified | `set_category` |
| `src/plg/ingest/sync.py` | Modified | Re-indexed chunks keep their category |
| `src/plg/config.py` | Modified | `categories_file`, `category_min_size` |
| `src/plg/cli.py` | Modified | `plg categorise` |
| `src/plg/graph/build.py`, `state.py` | Modified | `category_summary` intent, route prompt, node + edges |
| `src/plg/api/app.py` | Modified | `GET /categories`; index opened once and shared with the document viewer |
| `pyproject.toml`, `uv.lock` | Modified | `scikit-learn` dependency |
| `scripts/record_sse_fixtures.py` | Modified | `categories` scenario → `web/src/test/fixtures/categories.json` |
| `web/src/app/api/categories/route.ts` (+ test) | New | BFF relay |
| `web/src/app/library/page.tsx`, `LibraryScreen.tsx`, `library.module.css` (+ test) | New | Library categories view |
| `web/src/app/SourceViewer.tsx` | Modified | `DocumentViewer` (whole document, no highlight) |
| `web/src/lib/server/plg-api.ts`, `lib/events.ts`, `test/sse.ts`, page navs | Modified | `listCategories`, types, fixture, Library links |
| `tests/test_categories_api.py` | New | CLI → file, chunk metadata + filter, graph, idempotent re-run, `GET /categories`, `category_summary` |
| `tests/test_sync.py`, `tests/test_search_store_contract.py` | Modified | Category kept on re-index; `set_category` contract |

## Workflow

```
plg sync ─▶ LanceDB chunks (vectors)
plg categorise ─▶ sync_lock ─▶ document_vectors (mean of chunk vectors) ─▶ HDBSCAN ─▶ clusters (+ outliers)
                    └▶ Haiku name_categories (titles + central excerpts) ─▶ Category {CAT-<hash>, name, description, summary}
                         ├▶ .plg/categories.json
                         ├▶ store.set_category (chunk metadata; SearchFilter.category)
                         └▶ GraphWriter: DocumentCategory + LibraryDocument nodes, IN_CATEGORY edges

browser /library ─▶ BFF /api/categories ─▶ GET /categories ─▶ categories.json overlaid with store.documents()
                                     └▶ DocumentViewer ─▶ /api/documents/{id}

"Summarise the rental arrears category" ─▶ route: category_summary ─▶ category_summary_node
     ─▶ categories.json ─▶ match by name ─▶ traced finding (summary + documents) ─▶ merge streams the answer
```

## Next steps

- **Stale graph edges:** the graph is append-only. When a category's members change, the old `DocumentCategory` node and its `IN_CATEGORY` edges stay, so the categories file and chunk metadata are the truth. A graph "retire" operation would tidy this.
- **Lexical matching:** `category_summary` matches the question by words in the names. A question that paraphrases a name ("late rent" for "Rental arrears") lists the categories instead. Matching by embedding is the obvious upgrade.
- **Summaries as overviews:** summaries are written from titles and excerpts when the category is formed, and carry no citations. For what a document actually says, the officer asks knowledge.
- **Outliers:** HDBSCAN leaves a share of documents uncategorised (about a quarter on the real index). Assigning outliers to their nearest category, if close enough, would fill the Library.
- **Scoping knowledge searches:** the knowledge agent doesn't yet offer a `category` filter to Claude.
- **Citations:** the `category_summary` finding is traced but carries no citations, the same pattern as `tasks`. Its summary is Haiku's overview, not checked against sources.
- **Duplicated nodes:** a document now has both a `LibraryDocument` node and (for policies, SOPs and circulars) a lineage node. Nothing links the two yet.
