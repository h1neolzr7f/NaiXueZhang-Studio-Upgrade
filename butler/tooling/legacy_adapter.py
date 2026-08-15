from __future__ import annotations

from .spec import ToolSpec

READ_TOOLS = (
    ("search_gallery", ("sakiko", "tomori", "shared"), "搜索图库"),
    ("inspect_work", ("sakiko", "tomori", "shared"), "读取作品元数据"),
    ("compare_gallery_candidates", ("sakiko", "tomori", "shared"), "比较候选资产"),
    ("inspect_production", ("sakiko", "tomori", "shared"), "查看生产状态"),
    ("list_generated", ("sakiko", "tomori", "shared"), "列出生成结果"),
    ("list_queue", ("sakiko", "tomori", "shared"), "查看待生成队列"),
    ("inspect_capabilities", ("sakiko", "tomori", "shared"), "查看产品能力"),
    ("product_guide", ("sakiko", "shared"), "产品帮助"),
    ("audit_gallery", ("sakiko",), "图库体检"),
)

DRAFT_TOOLS = (
    ("prepare_studio", ("tomori",), "准备生成草稿"),
    ("prepare_remix", ("tomori",), "准备换角草稿"),
    ("prepare_character_reference", ("tomori",), "准备角色参考草稿"),
)

WORKFLOW_ONLY = (
    ("generate_image", "cost", ("tomori",), "generate"),
    ("batch_generate", "cost", ("tomori",), "generate"),
    ("start_crawler", "confirm", ("sakiko",), "crawl"),
    ("delete_generated_item", "destructive", ("sakiko",), "delete"),
    ("run_pipeline", "confirm", ("sakiko", "tomori"), "pipeline"),
    ("prepare_pixiv_submission", "confirm", ("tomori",), "publish_prepare"),
)


def project_legacy_specs() -> list[ToolSpec]:
    specs: list[ToolSpec] = []
    for name, agents, description in READ_TOOLS:
        specs.append(
            ToolSpec(
                name=name,
                version="1",
                description=description,
                risk="read",
                allowed_agents=agents,
                input_schema={"type": "object", "additionalProperties": True},
                legacy_tool=name,
            )
        )
    for name, agents, description in DRAFT_TOOLS:
        specs.append(
            ToolSpec(
                name=name,
                version="1",
                description=description,
                risk="draft",
                allowed_agents=agents,
                input_schema={"type": "object", "additionalProperties": True},
                legacy_tool=name,
            )
        )
    for name, risk, agents, _intent in WORKFLOW_ONLY:
        specs.append(
            ToolSpec(
                name=name,
                version="1",
                description=f"{name} must become a WorkflowRequest",
                risk=risk,
                allowed_agents=agents,
                executor_domain="durable",
                legacy_tool=name,
            )
        )
    return specs
