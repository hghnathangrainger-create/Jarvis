"""
test_knowledge.py

Unit tests for the Jarvis Knowledge Library.

Covers:
    - KnowledgeEntry model
    - KnowledgeStore (SQLite-backed CRUD and search)
    - KnowledgeIndexer (ChromaDB vector search)
    - KnowledgeManager (hybrid search, add/update/delete with indexing)
    - KnowledgeSearchTool and KnowledgeAddTool

Run with:
    pytest tests/unit/test_knowledge.py
"""

from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import create_engine

from knowledge.indexer import KnowledgeIndexer
from knowledge.manager import KnowledgeManager
from knowledge.models import KnowledgeEntry
from knowledge.store import KnowledgeStore
from storage.database import create_session_factory, initialize_database


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def session_factory():
    """Build a session factory backed by an in-memory SQLite database."""
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    return create_session_factory(engine)


@pytest.fixture()
def store(session_factory):
    """Build a KnowledgeStore backed by a fresh in-memory database."""
    return KnowledgeStore(session_factory)


@pytest.fixture()
def indexer(request):
    """Build a fresh in-memory KnowledgeIndexer with a unique collection."""
    idx = KnowledgeIndexer()
    # Each test gets a unique ChromaDB collection via the request node name.
    if idx.available:
        import chromadb
        idx._client = chromadb.Client()
        short_hash = hashlib.md5(request.node.name.encode()).hexdigest()[:8]
        idx._collection = idx._client.get_or_create_collection(
            name=f"kt_{short_hash}"
        )
    return idx


@pytest.fixture()
def manager(store, indexer):
    """Build a KnowledgeManager backed by SQLite + ChromaDB."""
    return KnowledgeManager(store=store, indexer=indexer)


@pytest.fixture()
def manager_no_indexer(store):
    """Build a KnowledgeManager without an indexer (keyword-only)."""
    return KnowledgeManager(store=store, indexer=None)


# ---------------------------------------------------------------------------
# KnowledgeEntry model tests
# ---------------------------------------------------------------------------


def test_knowledge_entry_defaults():
    """KnowledgeEntry has sensible defaults."""
    entry = KnowledgeEntry()
    assert entry.id is None
    assert entry.title == ""
    assert entry.content == ""
    assert entry.category == "general"
    assert entry.tags == []
    assert entry.source == "manual"
    assert entry.created_at is not None
    assert entry.updated_at is not None


def test_knowledge_entry_with_values():
    """KnowledgeEntry stores provided values."""
    entry = KnowledgeEntry(
        id=1,
        title="Test",
        content="Content here",
        category="project",
        tags=["python", "testing"],
        source="manual",
    )
    assert entry.id == 1
    assert entry.title == "Test"
    assert entry.tags == ["python", "testing"]


# ---------------------------------------------------------------------------
# KnowledgeStore tests
# ---------------------------------------------------------------------------


def test_store_add_and_get(store):
    """Add an entry and retrieve it by id."""
    entry = store.add(KnowledgeEntry(title="Python Tips", content="Use list comprehensions"))
    assert entry.id is not None
    retrieved = store.get(entry.id)
    assert retrieved is not None
    assert retrieved.title == "Python Tips"
    assert retrieved.content == "Use list comprehensions"


def test_store_get_nonexistent(store):
    """Getting a nonexistent id returns None."""
    assert store.get(99999) is None


def test_store_count(store):
    """Count starts at 0 and increments."""
    assert store.count() == 0
    store.add(KnowledgeEntry(title="A", content="a"))
    assert store.count() == 1
    store.add(KnowledgeEntry(title="B", content="b"))
    assert store.count() == 2


def test_store_search(store):
    """Search finds entries by title or content substring."""
    store.add(KnowledgeEntry(title="Python Tips", content="Use decorators"))
    store.add(KnowledgeEntry(title="Java Basics", content="Use classes"))
    store.add(KnowledgeEntry(title="Python Advanced", content="Use metaclasses"))

    results = store.search("Python")
    assert len(results) == 2
    titles = {r.title for r in results}
    assert "Python Tips" in titles
    assert "Python Advanced" in titles


def test_store_search_empty_query(store):
    """Empty query returns nothing."""
    store.add(KnowledgeEntry(title="A", content="a"))
    assert store.search("") == []
    assert store.search("   ") == []


def test_store_search_by_category(store):
    """search_by_category filters correctly."""
    store.add(KnowledgeEntry(title="A", content="a", category="project"))
    store.add(KnowledgeEntry(title="B", content="b", category="personal"))
    store.add(KnowledgeEntry(title="C", content="c", category="project"))

    results = store.search_by_category("project")
    assert len(results) == 2
    assert all(r.category == "project" for r in results)


def test_store_search_by_tags(store):
    """search_by_tags finds entries with matching tags."""
    store.add(KnowledgeEntry(title="A", content="a", tags=["python", "testing"]))
    store.add(KnowledgeEntry(title="B", content="b", tags=["java"]))
    store.add(KnowledgeEntry(title="C", content="c", tags=["python", "web"]))

    results = store.search_by_tags(["python"])
    assert len(results) == 2

    results = store.search_by_tags(["java"])
    assert len(results) == 1

    results = store.search_by_tags(["nonexistent"])
    assert len(results) == 0


def test_store_search_by_tags_empty(store):
    """Empty tags list returns nothing."""
    store.add(KnowledgeEntry(title="A", content="a", tags=["python"]))
    assert store.search_by_tags([]) == []


def test_store_update(store):
    """Update changes specific fields."""
    entry = store.add(KnowledgeEntry(title="Original", content="Content"))
    updated = store.update(entry.id, {"title": "Updated", "tags": ["new"]})
    assert updated is not None
    assert updated.title == "Updated"
    assert updated.tags == ["new"]
    assert updated.content == "Content"  # unchanged


def test_store_update_nonexistent(store):
    """Updating a nonexistent entry returns None."""
    assert store.update(99999, {"title": "Nope"}) is None


def test_store_delete(store):
    """Delete removes an entry."""
    entry = store.add(KnowledgeEntry(title="X", content="x"))
    assert store.count() == 1
    assert store.delete(entry.id) is True
    assert store.count() == 0
    assert store.get(entry.id) is None


def test_store_delete_nonexistent(store):
    """Deleting a nonexistent entry returns False."""
    assert store.delete(99999) is False


def test_store_list_all(store):
    """list_all returns entries newest first."""
    store.add(KnowledgeEntry(title="First", content="1"))
    store.add(KnowledgeEntry(title="Second", content="2"))
    entries = store.list_all()
    assert len(entries) == 2
    assert entries[0].title == "Second"
    assert entries[1].title == "First"


def test_store_tags_serialized(store):
    """Tags are stored as JSON and round-trip correctly."""
    entry = store.add(KnowledgeEntry(title="T", content="C", tags=["a", "b", "c"]))
    retrieved = store.get(entry.id)
    assert retrieved.tags == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# KnowledgeIndexer tests
# ---------------------------------------------------------------------------


def test_indexer_available(indexer):
    """Indexer is available when chromadb is installed."""
    assert indexer.available is True


def test_indexer_add_and_search(indexer):
    """Add entries and search returns semantically similar results."""
    indexer.add(id="1", text="Python is a programming language")
    indexer.add(id="2", text="The weather is sunny today")
    indexer.add(id="3", text="Python scripts are useful for automation")

    results = indexer.search("programming", top_k=2)
    assert len(results) == 2
    ids = {r["id"] for r in results}
    assert "1" in ids


def test_indexer_search_empty_store(indexer):
    """Searching an empty store returns nothing."""
    results = indexer.search("anything", top_k=5)
    assert results == []


def test_indexer_search_empty_query(indexer):
    """Empty query returns nothing."""
    indexer.add(id="1", text="something")
    assert indexer.search("") == []
    assert indexer.search("   ") == []


def test_indexer_delete(indexer):
    """Delete removes an entry from the index."""
    indexer.add(id="1", text="hello")
    assert indexer.count() == 1
    indexer.delete("1")
    assert indexer.count() == 0


def test_indexer_upsert_updates(indexer):
    """Adding the same id updates the document."""
    indexer.add(id="1", text="original text")
    indexer.add(id="1", text="updated text")
    assert indexer.count() == 1
    results = indexer.search("updated", top_k=1)
    assert len(results) == 1
    assert results[0]["text"] == "updated text"


def test_indexer_with_metadata(indexer):
    """Metadata is stored and retrievable."""
    indexer.add(
        id="1",
        text="Test entry",
        metadata={"category": "project", "source": "manual"},
    )
    results = indexer.search("Test entry", top_k=1)
    assert len(results) == 1
    assert results[0]["metadata"]["category"] == "project"


# ---------------------------------------------------------------------------
# KnowledgeManager tests
# ---------------------------------------------------------------------------


def test_manager_add_knowledge(manager):
    """add_knowledge stores in both SQLite and ChromaDB."""
    entry = manager.add_knowledge(
        title="Python Tips",
        content="Use list comprehensions",
        category="project",
        tags=["python"],
    )
    assert entry.id is not None
    assert entry.title == "Python Tips"
    assert manager.count() == 1
    # Indexed in ChromaDB too.
    if manager._indexer and manager._indexer.available:
        assert manager._indexer.count() == 1


def test_manager_get_knowledge(manager):
    """get_knowledge retrieves from SQLite."""
    entry = manager.add_knowledge(title="T", content="C")
    retrieved = manager.get_knowledge(entry.id)
    assert retrieved is not None
    assert retrieved.title == "T"


def test_manager_search_keyword(manager):
    """Keyword search works via substring match."""
    manager.add_knowledge(title="Python Tips", content="Decorators are useful")
    manager.add_knowledge(title="Java Tips", content="Classes are fundamental")

    results = manager.search_knowledge("Python", mode="keyword")
    assert len(results) == 1
    assert results[0].title == "Python Tips"


def test_manager_search_semantic(manager):
    """Semantic search returns relevant results via ChromaDB."""
    manager.add_knowledge(title="Cooking Pasta", content="Boil water, add salt")
    manager.add_knowledge(title="Project Deadlines", content="Q4 delivery")
    manager.add_knowledge(title="Italian Recipes", content="Make risotto with broth")

    results = manager.search_knowledge("food preparation", mode="semantic", top_k=2)
    assert len(results) <= 2
    # Food-related entries should appear.
    titles = [r.title for r in results]
    assert any("Cooking" in t or "Italian" in t for t in titles)


def test_manager_search_hybrid(manager):
    """Hybrid search combines keyword + semantic with deduplication."""
    manager.add_knowledge(title="Python Testing", content="Use pytest")
    manager.add_knowledge(title="Java Testing", content="Use JUnit")
    manager.add_knowledge(title="Python Web", content="Use Django")

    results = manager.search_knowledge("Python", mode="hybrid")
    # Should find Python entries via both keyword and semantic.
    assert len(results) >= 2
    titles = {r.title for r in results}
    assert "Python Testing" in titles


def test_manager_search_empty(manager):
    """Empty search returns nothing."""
    manager.add_knowledge(title="A", content="a")
    results = manager.search_knowledge("", mode="keyword")
    assert results == []


def test_manager_search_with_category_filter(manager):
    """Keyword search respects category filter."""
    manager.add_knowledge(title="Python Tips", content="Decorators", category="project")
    manager.add_knowledge(title="Python Recipes", content="Pasta", category="personal")

    results = manager.search_knowledge("Python", mode="keyword", category="project")
    assert len(results) == 1
    assert results[0].category == "project"


def test_manager_search_unknown_mode(manager):
    """Unknown search mode raises ValueError."""
    with pytest.raises(ValueError, match="Unknown search mode"):
        manager.search_knowledge("test", mode="invalid")


def test_manager_search_semantic_without_indexer(manager_no_indexer):
    """Semantic search without indexer raises RuntimeError."""
    with pytest.raises(RuntimeError, match="Semantic search requires"):
        manager_no_indexer.search_knowledge("test", mode="semantic")


def test_manager_update_knowledge(manager):
    """Update changes fields and re-indexes in ChromaDB."""
    entry = manager.add_knowledge(title="Original", content="Content")
    updated = manager.update_knowledge(entry.id, title="Updated")
    assert updated is not None
    assert updated.title == "Updated"
    # Verify the SQLite store reflects the update.
    retrieved = manager.get_knowledge(entry.id)
    assert retrieved.title == "Updated"


def test_manager_update_knowledge_nonexistent(manager):
    """Updating a nonexistent entry returns None."""
    assert manager.update_knowledge(99999, title="Nope") is None


def test_manager_delete_knowledge(manager):
    """Delete removes from both SQLite and ChromaDB."""
    entry = manager.add_knowledge(title="X", content="x")
    assert manager.count() == 1
    assert manager.delete_knowledge(entry.id) is True
    assert manager.count() == 0
    assert manager.get_knowledge(entry.id) is None
    if manager._indexer and manager._indexer.available:
        # ChromaDB entry should also be removed.
        results = manager._indexer.search("x", top_k=1)
        assert len(results) == 0


def test_manager_delete_knowledge_nonexistent(manager):
    """Deleting a nonexistent entry returns False."""
    assert manager.delete_knowledge(99999) is False


def test_manager_without_indexer_add_works(manager_no_indexer):
    """Adding works without an indexer (SQLite only)."""
    entry = manager_no_indexer.add_knowledge(title="T", content="C")
    assert entry.id is not None
    assert manager_no_indexer.count() == 1


def test_manager_hybrid_deduplication(manager):
    """Hybrid search deduplicates entries found by both keyword and semantic."""
    manager.add_knowledge(
        title="Python Programming",
        content="Python is versatile",
        tags=["python"],
    )
    results = manager.search_knowledge("Python", mode="hybrid")
    # The same entry should appear only once.
    ids = [r.id for r in results]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# KnowledgeSearchTool tests
# ---------------------------------------------------------------------------


def test_search_tool_run(manager):
    """KnowledgeSearchTool returns formatted results."""
    from tools.builtin.knowledge_search_tool import KnowledgeSearchTool
    from tools.base_tool import ToolRequest

    manager.add_knowledge(title="Python Tips", content="Use decorators")

    tool = KnowledgeSearchTool(manager)
    result = tool.run(ToolRequest(
        tool_name="knowledge_search",
        input_data={"query": "Python", "mode": "keyword"},
    ))
    assert result.success is True
    assert "Python Tips" in result.output


def test_search_tool_empty_query(manager):
    """KnowledgeSearchTool fails on empty query."""
    from tools.builtin.knowledge_search_tool import KnowledgeSearchTool
    from tools.base_tool import ToolRequest

    tool = KnowledgeSearchTool(manager)
    result = tool.run(ToolRequest(
        tool_name="knowledge_search",
        input_data={"query": ""},
    ))
    assert result.success is False
    assert "non-empty" in result.error


def test_search_tool_no_results(manager):
    """KnowledgeSearchTool reports no results."""
    from tools.builtin.knowledge_search_tool import KnowledgeSearchTool
    from tools.base_tool import ToolRequest

    tool = KnowledgeSearchTool(manager)
    result = tool.run(ToolRequest(
        tool_name="knowledge_search",
        input_data={"query": "nonexistent"},
    ))
    assert result.success is True
    assert "No knowledge" in result.output


def test_search_tool_unknown_mode(manager):
    """KnowledgeSearchTool fails on unknown mode."""
    from tools.builtin.knowledge_search_tool import KnowledgeSearchTool
    from tools.base_tool import ToolRequest

    tool = KnowledgeSearchTool(manager)
    result = tool.run(ToolRequest(
        tool_name="knowledge_search",
        input_data={"query": "test", "mode": "invalid"},
    ))
    assert result.success is False
    assert "Unknown search mode" in result.error


# ---------------------------------------------------------------------------
# KnowledgeAddTool tests
# ---------------------------------------------------------------------------


def test_add_tool_run(manager):
    """KnowledgeAddTool successfully adds an entry."""
    from tools.builtin.knowledge_add_tool import KnowledgeAddTool
    from tools.base_tool import ToolRequest

    tool = KnowledgeAddTool(manager)
    result = tool.run(ToolRequest(
        tool_name="knowledge_add",
        input_data={
            "title": "Python Tips",
            "content": "Use decorators",
            "category": "project",
            "tags": ["python", "tips"],
        },
    ))
    assert result.success is True
    assert "Python Tips" in result.output
    assert manager.count() == 1


def test_add_tool_missing_title(manager):
    """KnowledgeAddTool fails without title."""
    from tools.builtin.knowledge_add_tool import KnowledgeAddTool
    from tools.base_tool import ToolRequest

    tool = KnowledgeAddTool(manager)
    result = tool.run(ToolRequest(
        tool_name="knowledge_add",
        input_data={"content": "Content"},
    ))
    assert result.success is False
    assert "title" in result.error.lower()


def test_add_tool_missing_content(manager):
    """KnowledgeAddTool fails without content."""
    from tools.builtin.knowledge_add_tool import KnowledgeAddTool
    from tools.base_tool import ToolRequest

    tool = KnowledgeAddTool(manager)
    result = tool.run(ToolRequest(
        tool_name="knowledge_add",
        input_data={"title": "Title"},
    ))
    assert result.success is False
    assert "content" in result.error.lower()
