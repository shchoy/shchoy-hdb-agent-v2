"""Document categories (issue #29): `plg categorise` groups the indexed corpus, the Library lists the groups
(`GET /categories`) and an officer asks for a summary of one (`category_summary`).

The corpus is the session's synced poc-data index (hashing embedder), copied so categorising never touches the shared
one. HDBSCAN and PLG Records are real; Haiku's naming is scripted: each cluster is named after its first title.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from plg import cli
from plg.categories.categorise import NAME_REQUEST, NODE
from plg.config import Settings
from plg.entities.local import LocalGraphStore
from plg.llm import AgentMessage, AgentTurn, ScriptedLLMClient, tool_call, turn
from plg.search.lance import LanceSearchStore
from plg.search.models import SearchFilter
from tests.conftest import USER, Api, CountingEmbedder, open_store, route

POL_V1 = "docs/PLG-POL-003_Rental_Arrears_Management_Policy_v1.0.docx"
POL_V2 = "docs/PLG-POL-003_Rental_Arrears_Management_Policy_v2.0.docx"
CLUSTER = re.compile(r"^Cluster (\d+) \((\d+) documents\)\nDocuments:\n- (.+?) \(", re.M)


def name_after_first_title(messages: list[AgentMessage]) -> AgentTurn:
    content = messages[-1]["content"]
    assert not isinstance(content, str)
    listing = str(content[1]["text"])
    return turn(tool_call("name_categories", categories=[
        {"cluster": int(n), "name": f"{title} and related", "description": f"Documents like {title}.",
         "summary": f"Cluster {n} gathers {size} documents such as {title}."}
        for n, size, title in CLUSTER.findall(listing)
    ]))


def naming_llm() -> ScriptedLLMClient:
    llm = ScriptedLLMClient()
    llm.script_turns(NODE, NAME_REQUEST, name_after_first_title)
    return llm


@dataclass
class Categorised:
    index: Path
    embedder: CountingEmbedder
    categories_file: Path
    graph_dir: Path
    output: str

    def env(self) -> dict[str, str]:
        return {
            "PLG_SEARCH_DB": str(self.index), "PLG_EMBED_DIM": str(self.embedder.dim),
            "PLG_CATEGORIES_FILE": str(self.categories_file), "PLG_GRAPH_DIR": str(self.graph_dir),
        }

    def run(self, llm: ScriptedLLMClient | None = None) -> Result:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(cli, "make_llm", lambda _settings: llm or naming_llm())
            result = CliRunner().invoke(cli.app, ["categorise"], env=self.env())
        assert result.exit_code == 0, result.output
        return result

    def store(self) -> LanceSearchStore:
        return open_store(self.index, self.embedder)

    def view(self, api: Api) -> dict[str, Any]:
        response = api.client.get("/categories", headers=USER)
        assert response.status_code == 200
        return dict(response.json())


@pytest.fixture(scope="module")
def categorised(
    synced_corpus: tuple[Path, CountingEmbedder, str], tmp_path_factory: pytest.TempPathFactory
) -> Categorised:
    source, embedder, _ = synced_corpus
    root = tmp_path_factory.mktemp("categorised")
    shutil.copytree(source, root / "index")
    run = Categorised(root / "index", embedder, root / "categories.json", root / "graph", "")
    run.output = run.run().output
    return run


@pytest.fixture
def library_api(make_api: Callable[..., Api], categorised: Categorised) -> Api:
    return make_api(store=categorised.store(), categories_file=categorised.categories_file)


def category_of(view: dict[str, Any], doc_id: str) -> dict[str, Any]:
    (found,) = [c for c in view["categories"] if doc_id in {d["doc_id"] for d in c["documents"]}]
    return found


def doc_id(store: LanceSearchStore, path: str) -> str:
    return next(d.doc_id for d in store.documents() if d.source_path == path)


# ---------------------------------------------------------------- plg categorise


def test_categorise_groups_every_indexed_document_into_named_categories_or_none(
    categorised: Categorised, library_api: Api
) -> None:
    view = categorised.view(library_api)

    listed = [d["doc_id"] for c in view["categories"] for d in c["documents"]] + [
        d["doc_id"] for d in view["uncategorised"]
    ]
    assert sorted(listed) == sorted(d.doc_id for d in categorised.store().documents())  # each exactly once
    assert len(view["categories"]) >= 3 and view["categorised_at"]
    for category in view["categories"]:
        assert category["id"].startswith("CAT-") and category["name"].endswith(" and related")
        assert category["summary"].startswith("Cluster ") and len(category["documents"]) >= 3
    assert f"into {len(view['categories'])} categories" in categorised.output


def test_two_versions_of_a_policy_fall_in_the_same_category(categorised: Categorised, library_api: Api) -> None:
    store, view = categorised.store(), categorised.view(library_api)

    assert category_of(view, doc_id(store, POL_V1))["id"] == category_of(view, doc_id(store, POL_V2))["id"]


def test_each_chunk_carries_its_category_and_search_can_filter_on_it(
    categorised: Categorised, library_api: Api
) -> None:
    store = categorised.store()
    category = category_of(categorised.view(library_api), doc_id(store, POL_V2))
    members = {d["doc_id"] for d in category["documents"]}

    assert {c.category for c in store.chunks(doc_id(store, POL_V2))} == {category["id"]}
    hits = store.search("rental arrears", categorised.embedder.embed_query("rental arrears"),
                        filters=SearchFilter(category=category["id"]), limit=20)
    assert hits and {h.chunk.doc_id for h in hits} <= members


def test_categories_are_in_the_entity_graph(categorised: Categorised, library_api: Api) -> None:
    graph = LocalGraphStore.from_dirs(categorised.graph_dir / "spine", categorised.graph_dir / "delta")
    category = category_of(categorised.view(library_api), doc_id(categorised.store(), POL_V2))

    node = graph.node(category["id"])
    assert node is not None and (node.label, node.name) == ("DocumentCategory", category["name"])
    context = graph.entity_context(category["id"], hops=1)
    assert context is not None
    members = {e.start for e in context.edges if e.type == "IN_CATEGORY" and e.end == category["id"]}
    assert members == {d["doc_id"] for d in category["documents"]}
    assert {n.label for n in context.nodes} == {"LibraryDocument"}


def test_re_categorising_an_unchanged_index_changes_nothing(categorised: Categorised, library_api: Api) -> None:
    before = categorised.view(library_api)
    llm = ScriptedLLMClient()  # nothing scripted: any naming call would fail

    result = categorised.run(llm)

    assert llm.sent == []  # known categories keep their names; Haiku is asked only about new groups
    assert "0 changed category" in result.output
    assert categorised.view(library_api)["categories"] == before["categories"]


def test_tenant_pii_in_what_haiku_wrote_is_masked_before_it_is_saved(
    categorised: Categorised, make_api: Callable[..., Api], tmp_path: Path
) -> None:
    def leaky(messages: list[AgentMessage]) -> AgentTurn:
        named = name_after_first_title(messages)
        for c in named.content[0]["input"]["categories"]:
            c["summary"] += " Contact Devi Nair on 9391 3713 or devi@nanyangmart.example.com."
        return named

    llm = ScriptedLLMClient()
    llm.script_turns(NODE, NAME_REQUEST, leaky)
    fresh = Categorised(categorised.index, categorised.embedder, tmp_path / "c.json", tmp_path / "graph", "")
    fresh.run(llm)

    view = fresh.view(make_api(store=fresh.store(), categories_file=fresh.categories_file))
    summaries = " ".join(c["summary"] for c in view["categories"])
    assert "[tenant contact]" in summaries and "[phone]" in summaries and "[email]" in summaries
    assert "Devi Nair" not in summaries and "9391 3713" not in summaries


def test_categorise_without_an_index_says_to_sync_first(tmp_path: Path) -> None:
    env = {"PLG_SEARCH_DB": str(tmp_path / "empty"), "PLG_EMBED_DIM": "128"}

    result = CliRunner().invoke(cli.app, ["categorise"], env=env)

    assert result.exit_code == 1
    assert "plg sync" in result.stderr


# ---------------------------------------------------------------- GET /categories


def test_the_library_lists_categories_only_to_signed_in_officers(library_api: Api) -> None:
    assert library_api.client.get("/categories").status_code == 401


def test_before_any_categorisation_every_document_is_uncategorised(
    make_api: Callable[..., Api], categorised: Categorised, tmp_path: Path
) -> None:
    api = make_api(store=categorised.store(), categories_file=tmp_path / "none.json")

    view = categorised.view(api)

    assert (view["categorised_at"], view["categories"]) == (None, [])
    assert len(view["uncategorised"]) == len(categorised.store().documents())


# ---------------------------------------------------------------- category_summary


@pytest.fixture
def summary_api(make_api: Callable[..., Api], llm: ScriptedLLMClient, categorised: Categorised) -> Api:
    return make_api(store=categorised.store(), categories_file=categorised.categories_file)


def test_a_category_summary_answers_from_the_categorisation(
    summary_api: Api, llm: ScriptedLLMClient, categorised: Categorised
) -> None:
    category = category_of(categorised.view(summary_api), doc_id(categorised.store(), POL_V2))
    question = f"Summarise the {category['name']} category for me."
    route(llm, question, "category_summary")
    llm.script("merge", question, "Here is that category.")
    thread = summary_api.create_thread()

    stream = summary_api.run(thread, question)

    assert stream.text == "Here is that category."
    finding = llm.streamed[-1].system
    assert category["summary"] in finding
    assert all(d["title"] in finding for d in category["documents"])


def test_a_summary_of_an_unknown_category_lists_the_categories_there_are(
    summary_api: Api, llm: ScriptedLLMClient, categorised: Categorised
) -> None:
    question = "Summarise the zebra crossings category."
    route(llm, question, "category_summary")
    llm.script("merge", question, "There is no such category.")

    summary_api.run(summary_api.create_thread(), question)

    finding = llm.streamed[-1].system
    assert all(c["name"] in finding for c in categorised.view(summary_api)["categories"])


def test_before_any_categorisation_a_category_summary_says_so(
    make_api: Callable[..., Api], llm: ScriptedLLMClient, tmp_path: Path
) -> None:
    api = make_api(categories_file=tmp_path / "none.json")
    question = "Summarise the rental arrears category."
    route(llm, question, "category_summary")
    llm.script("merge", question, "Not yet.")

    api.run(api.create_thread(), question)

    assert "plg categorise" in llm.streamed[-1].system


def test_settings_default_categories_file_is_beside_the_other_state() -> None:
    assert Settings().categories_file.parent == Settings().threads_db.parent


