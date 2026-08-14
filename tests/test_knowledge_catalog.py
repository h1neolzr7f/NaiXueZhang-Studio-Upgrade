from pathlib import Path

import pytest

from knowledge_catalog import KnowledgeCatalog, KnowledgeRefreshCancelled
from software_help import answer_software_question


def test_builtin_knowledge_is_retrievable_with_source_and_zero_model_calls(tmp_path: Path) -> None:
    root = tmp_path / "project"
    docs = root / "docs"
    docs.mkdir(parents=True)
    (docs / "nai-character-slots.md").write_text(
        "# NAI 角色槽\n\n画师、画风、场景和质量词不得自动进入 NAI 角色槽。\n",
        encoding="utf-8",
    )

    catalog = KnowledgeCatalog(db_path=tmp_path / "knowledge.db", source_root=root)

    receipt = catalog.refresh_builtin_sources()
    result = catalog.search("画师和场景会自动进入 NAI 角色槽吗？")

    assert receipt["documents"] == 1
    assert receipt["chunks"] == 1
    assert result["model_calls"] == 0
    assert result["items"][0]["source"] == "docs/nai-character-slots.md"
    assert "不得自动进入 NAI 角色槽" in result["items"][0]["text"]


def test_refresh_skips_unchanged_sources_and_updates_only_changed_content(tmp_path: Path) -> None:
    root = tmp_path / "project"
    docs = root / "docs"
    docs.mkdir(parents=True)
    guide = docs / "generation.md"
    guide.write_text("# 生图费用\n\n确认前不会调用 NAI。\n", encoding="utf-8")
    catalog = KnowledgeCatalog(db_path=tmp_path / "knowledge.db", source_root=root)

    first = catalog.refresh_builtin_sources()
    second = catalog.refresh_builtin_sources()
    guide.write_text("# 生图费用\n\n只有确认生成后才会调用 NAI 并可能消耗 Anlas。\n", encoding="utf-8")
    third = catalog.refresh_builtin_sources()

    assert first["inserted"] == 1
    assert second["unchanged"] == 1
    assert second["inserted"] == 0
    assert second["updated"] == 0
    assert third["updated"] == 1
    assert "确认生成后" in catalog.search("什么时候消耗 Anlas")["items"][0]["text"]


def test_software_help_uses_local_knowledge_before_a_model_for_specific_questions(tmp_path: Path) -> None:
    root = tmp_path / "project"
    docs = root / "docs"
    docs.mkdir(parents=True)
    (docs / "nai-anima-adaptation.md").write_text(
        "# NAI 多角色规则\n\n人数写入 Base；角色槽使用 girl、boy 或 other，最多六个角色槽。\n",
        encoding="utf-8",
    )
    catalog = KnowledgeCatalog(db_path=tmp_path / "knowledge.db", source_root=root)
    catalog.refresh_builtin_sources()

    result = answer_software_question(
        "NAI V4.5 的 Base 和角色槽人数怎么写？",
        knowledge_catalog=catalog,
    )

    assert result["provider"] == "local_knowledge"
    assert result["model_calls"] == 0
    assert result["page"] == "/references"
    assert "人数写入 Base" in result["answer"]
    assert result["sources"] == ["docs/nai-anima-adaptation.md"]


def test_generic_question_word_does_not_turn_an_unrelated_document_into_an_answer(tmp_path: Path) -> None:
    root = tmp_path / "project"
    docs = root / "docs"
    docs.mkdir(parents=True)
    (docs / "nai.md").write_text(
        "# NAI 使用\n\n这个页面说明 NAI 角色槽怎么使用。\n",
        encoding="utf-8",
    )
    catalog = KnowledgeCatalog(db_path=tmp_path / "knowledge.db", source_root=root)
    catalog.refresh_builtin_sources()

    result = catalog.search("打印机怎么连接？")

    assert result["items"] == []
    assert result["model_calls"] == 0


def test_default_sources_include_user_guide_and_disclaimer(tmp_path: Path) -> None:
    from knowledge_catalog import DEFAULT_SOURCE_PATHS

    root = Path(__file__).resolve().parents[1]
    catalog = KnowledgeCatalog(db_path=tmp_path / "knowledge.db", source_root=root)
    files = {path.relative_to(root).as_posix() for path in catalog._source_files()}

    assert "docs/user-guide.md" in DEFAULT_SOURCE_PATHS
    assert "docs/user-guide.md" in files
    assert "DISCLAIMER.md" in files
    assert "RESPONSIBLE_USE.md" in files
    receipt = catalog.refresh_builtin_sources()
    found = catalog.search("凑企鹅是互联网上高松灯的二创称呼")
    assert receipt["documents"] >= 4
    assert found["items"]
    assert any("user-guide" in str(item["source"]) for item in found["items"])


def test_software_help_teaches_assistant_desks_and_beginner_steps() -> None:
    assistants = answer_software_question("客服小祥和助手凑企鹅有什么区别")
    beginner = answer_software_question("新手小白怎么开始用")

    assert assistants["topic"] == "assistants"
    assert "工具白名单" in assistants["answer"]
    assert beginner["topic"] == "beginner"
    assert "设置" in beginner["answer"]
    assert beginner["page"].startswith("/butler")


def test_knowledge_status_tracks_version_sources_and_last_refresh(tmp_path: Path) -> None:
    root = tmp_path / "project"
    docs = root / "docs"
    docs.mkdir(parents=True)
    (docs / "guide.md").write_text("# 使用说明\n\n在配置中心一次设置。\n", encoding="utf-8")
    catalog = KnowledgeCatalog(db_path=tmp_path / "knowledge.db", source_root=root)

    before = catalog.status()
    receipt = catalog.refresh_builtin_sources()
    after = catalog.status()

    assert before["state"] == "never_built"
    assert before["documents"] == 0
    assert receipt["state"] == "ready"
    assert after["state"] == "ready"
    assert after["schema_version"] >= 1
    assert after["index_version"]
    assert after["documents"] == 1
    assert after["chunks"] == 1
    assert after["sources"][0]["source"] == "docs/guide.md"
    assert after["last_completed_at"]
    assert after["last_error"] == ""


def test_failed_refresh_keeps_previous_index_and_records_a_bounded_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "README.md").write_text("# 帮助\n\n原有内容。\n", encoding="utf-8")
    catalog = KnowledgeCatalog(db_path=tmp_path / "knowledge.db", source_root=root)
    catalog.refresh_builtin_sources()

    def fail_sources() -> list[Path]:
        raise OSError("模拟读取失败")

    monkeypatch.setattr(catalog, "_source_files", fail_sources)
    with pytest.raises(OSError, match="模拟读取失败"):
        catalog.refresh_builtin_sources()

    status = catalog.status()
    assert status["state"] == "failed"
    assert status["documents"] == 1
    assert status["chunks"] == 1
    assert status["last_error"] == "模拟读取失败"


def test_content_version_changes_only_when_trusted_content_changes(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    guide = root / "README.md"
    guide.write_text("# 帮助\n\n第一版。\n", encoding="utf-8")
    catalog = KnowledgeCatalog(db_path=tmp_path / "knowledge.db", source_root=root)

    catalog.refresh_builtin_sources()
    first = catalog.status()["content_version"]
    catalog.refresh_builtin_sources()
    unchanged = catalog.status()["content_version"]
    guide.write_text("# 帮助\n\n第二版。\n", encoding="utf-8")
    catalog.refresh_builtin_sources()
    changed = catalog.status()["content_version"]

    assert first
    assert unchanged == first
    assert changed != first


def test_refresh_reports_monotonic_source_progress(tmp_path: Path) -> None:
    root = tmp_path / "project"
    docs = root / "docs"
    docs.mkdir(parents=True)
    (docs / "a.md").write_text("# A\n\n第一份。\n", encoding="utf-8")
    (docs / "b.md").write_text("# B\n\n第二份。\n", encoding="utf-8")
    catalog = KnowledgeCatalog(db_path=tmp_path / "knowledge.db", source_root=root)
    events: list[dict] = []

    receipt = catalog.refresh_builtin_sources(on_progress=lambda event: events.append(dict(event)))

    assert events[0]["processed"] == 0
    assert events[-1]["processed"] == events[-1]["total"] == 2
    assert [event["processed"] for event in events] == sorted(
        event["processed"] for event in events
    )
    assert receipt["processed"] == receipt["total"] == 2


def test_cancelled_refresh_keeps_the_previous_usable_index(tmp_path: Path) -> None:
    root = tmp_path / "project"
    docs = root / "docs"
    docs.mkdir(parents=True)
    first = docs / "a.md"
    second = docs / "b.md"
    first.write_text("# A\n\n旧版甲。\n", encoding="utf-8")
    second.write_text("# B\n\n旧版乙。\n", encoding="utf-8")
    catalog = KnowledgeCatalog(db_path=tmp_path / "knowledge.db", source_root=root)
    catalog.refresh_builtin_sources()
    previous_version = catalog.status()["content_version"]
    first.write_text("# A\n\n新版甲。\n", encoding="utf-8")
    second.write_text("# B\n\n新版乙。\n", encoding="utf-8")
    events: list[dict] = []

    with pytest.raises(KnowledgeRefreshCancelled):
        catalog.refresh_builtin_sources(
            on_progress=lambda event: events.append(dict(event)),
            should_cancel=lambda: bool(events and events[-1]["processed"] >= 1),
        )

    status = catalog.status()
    assert status["state"] == "cancelled"
    assert status["usable"] is True
    assert status["content_version"] == previous_version
    assert "旧版甲" in catalog.search("旧版甲")["items"][0]["text"]
