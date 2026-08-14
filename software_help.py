"""Deterministic, zero-token help for every user-facing Gallery workflow."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from knowledge_catalog import KnowledgeCatalog, get_knowledge_catalog


@dataclass(frozen=True)
class HelpTopic:
    id: str
    title: str
    page: str
    signals: tuple[str, ...]
    answer: str


TOPICS = (
    HelpTopic(
        "configuration",
        "统一配置、API 与账号",
        "/settings",
        ("配置", "api", "key", "token", "账号", "密码", "模型", "中转站", "grok", "novelai", "pixiv登录"),
        "把 API Base、模型、Key、NAI Token 或 Pixiv 账号资料交给客服小祥，或打开「设置」。小祥会先脱敏识别、列出将修改的项目并请求确认；确认后写入统一配置。Key、Token 和密码不会写进聊天记录。通行密钥、验证码或站点风控仍需要你在弹出的登录页完成。接口地址、代理和端口请到 /settings#ai-service 手工填写。",
    ),
    HelpTopic(
        "gallery",
        "图库搜索与作品详情",
        "/",
        ("图库", "搜索", "筛选", "标签", "prompt", "作品详情", "收藏", "三图库"),
        "在“图库”用标题、标签或 Prompt 搜索；高级筛选可限制时间和排序。点作品进入详情可查看全部图片与本地 Prompt。网站、法典、Q 群作品使用独立图库身份，不会串号。搜索和查看只读本地数据，不消耗 Token。",
    ),
    HelpTopic(
        "queue",
        "待生成队列",
        "/queue",
        ("待生成", "队列", "清单", "加入列表", "移出列表"),
        "在图库或详情页把作品加入「待生成」，再交给助手凑企鹅批量处理。只有凑企鹅能改队列；客服小祥可以查看。修改前会给出目标数量并请求确认。整理队列本身不识图、不消耗 NAI。",
    ),
    HelpTopic(
        "remix",
        "换角色与换画风",
        "/remix",
        ("换画风", "画风", "换角", "替换角色", "角色替换", "remix", "批量换"),
        "打开「换角」页选择作品、页面和预设，或把任务交给助手凑企鹅。预检复用手动工具的同一配方链，不会调用识图；只有确认生成后才会消耗 NAI。批量任务会显示逐项进度、失败原因和交付报告。采集和改设置请切回客服小祥。",
    ),
    HelpTopic(
        "director",
        "NAI 批量导演",
        "/director",
        ("批量导演", "导演工具", "director", "去背景", "线稿", "草图", "上色", "表情", "情绪", "去杂乱"),
        "“批量导演”是独立桌面功能。生成结果默认和起号流水线一样按系列显示：普通点击选整组，Ctrl+点击可增加或取消多个系列；切到“单张”可逐图挑选。网站、法典、Q 群三图库仍按精确图片身份选择。单次最多 40 张，超过上限的系列会提示切到单张挑选。选好后先点“零费用预检”核对来源、预计调用和输出数；预览不会请求 NAI。真正执行前必须勾选计费确认，完成后保留进度和交付报告。",
    ),
    HelpTopic(
        "generation",
        "生图与批量生成",
        "/studio",
        ("生图", "生成图片", "批量生成", "steps", "scale", "sampler", "尺寸", "种子"),
        "在「工作台」设置尺寸、steps、scale、sampler、seed 和每作品张数，或把出图任务交给助手凑企鹅。她可直接复用图库已有 Prompt/标签组批，不需要先识图。真正提交 NAI 前必须确认；完成后任务中心会报告成功、失败和费用记录，失败或未完成项可以单独重试。",
    ),
    HelpTopic(
        "generated",
        "生成结果与回收站",
        "/generated",
        ("生成结果", "生成图库", "回收站", "删除图片", "恢复图片", "重试失败"),
        "「生成库」按来源系列整理图片并显示生成参数。删除会先进入 30 天回收站，15 秒内可立即撤销；恢复时不会覆盖同名文件。失败任务可只重试失败和未完成项，成功结果不会重复生成。删成果和补后处理找客服小祥；继续出图找助手凑企鹅。",
    ),
    HelpTopic(
        "pipeline",
        "后处理",
        "/pipeline",
        ("后处理", "超分", "打码", "元数据", "审核", "final"),
        "后处理按全局设置补跑超分、必要打码和元数据清理；已经完成的步骤可跳过。投稿只使用核验后的 final 文件。客服小祥能执行并跟踪后处理，但真实上传仍停在投稿页由你核对。",
    ),
    HelpTopic(
        "pixiv",
        "Pixiv 投稿准备",
        "/pixiv",
        ("pixiv", "投稿", "发布", "上传", "标题", "简介", "分级", "r18"),
        "在「发布」选择生成系列，准备标题、简介、标签、分级和后处理结果。助手凑企鹅可以整理完整投稿草稿，但不会替你跳过最终确认；实际上传固定使用当前高亮账号，并在提交前显示账号、图片数、分级和处理状态。",
    ),
    HelpTopic(
        "butler",
        "智能助手与任务中心",
        "/butler",
        ("小镜", "智能管家", "智能助手", "任务中心", "进度", "聊天记录", "常用任务", "执行报告", "客服小祥", "凑企鹅"),
        "屏幕左右边缘可划开两位助手：左侧客服小祥负责维护和教学，右侧助手凑企鹅负责出图。提问会直接回答并保留聊天记录，不会创建任务；只有明确交代操作时才进入任务流。写入、生成、账号配置和投稿准备会按安全边界确认。越权工具会被拦下，请切换对应助手。",
    ),
    HelpTopic(
        "assistants",
        "两位助手的职责分工",
        "/butler",
        ("助手分工", "谁负责", "越权", "切换助手", "客服", "小祥", "凑企鹅", "高松灯"),
        "客服小祥：图库体检、采集、收藏、后处理、设置、排障、知识库，以及教你怎么用软件。助手凑企鹅：选材、换角、出图、导演、待生成队列和投稿准备。两人共用同一套 API，但工具白名单不重叠到对方的生产动作；生图不会从客服台发出，采集也不会从生成台发出。",
    ),
    HelpTopic(
        "beginner",
        "小白入门",
        "/butler?agent=sakiko",
        ("新手", "入门", "小白", "第一次", "从哪开始", "怎么开始"),
        "三步即可：1) 在设置里填 AI 模型和 NAI Token；2) 用「爬虫」或「自选库」让图库有第一批图；3) 在图库收藏或加入待生成，再把出图任务交给助手凑企鹅。用法、报错和采集问左侧客服小祥；出图参数问右侧凑企鹅。完整说明在本地知识库 docs/user-guide.md。",
    ),
    HelpTopic(
        "crawler",
        "采集与爬虫",
        "/progress",
        ("采集", "爬虫", "抓取", "启动采集", "搜索词", "榜单"),
        "打开「爬虫」配置搜索标签、画师或榜单。无 Pixiv 账号可用公网通道；有账号再填用户 ID。请求间隔建议 ≥1 秒。主图库为空时禁止启动采集，请先用 AITag 发现或自选库导入。启动、停止和改范围由客服小祥确认后执行。",
    ),
    HelpTopic(
        "references",
        "角色与画风资料库",
        "/references",
        ("参考库", "角色资料", "画风资料", "animadex"),
        "「参考库」只管理本地角色事实和独立画风，不会调用生成接口。助手凑企鹅可按资料准备 Studio 槽位；画师、场景和质量词不会自动写进角色槽。",
    ),
    HelpTopic(
        "codex",
        "自选库导入",
        "/codex",
        ("自选库", "导入本地", "拖入图片", "codex"),
        "在「图库」切到自选库或 Q群 后，可把本地图片或文件夹拖进页面；独立「自选库」页同样可以导入。软件只收带 NovelAI 元数据的图，每一批自动进一个「拖入」文件夹，文件夹可合并后再加入批量换角。拖入本身不调用 NovelAI。",
    ),
    HelpTopic(
        "tags",
        "分类图谱",
        "/nai-tags",
        ("分类", "标签图谱", "nai标签", "分面"),
        "「分类」从已验证作品的 NovelAI 提示词提取角色、画师、动作等分面，用来筛选后再进工作台或换角。它不是 Pixiv 标签列表。",
    ),
    HelpTopic(
        "maintenance",
        "图库维护与跳过清单",
        "/maintenance",
        ("维护", "跳过清单", "staging", "迁移", "孤儿"),
        "「维护」查看容量、缩略图、孤儿文件和永久跳过清单。预览不会改文件；确认迁移或清理前会给出回执。这是客服小祥的职责范围。",
    ),
    HelpTopic(
        "compliance",
        "合规与来源",
        "/compliance",
        ("合规", "黑名单", "排除作者", "责任", "免责"),
        "「合规与来源」只保存在本机：作者排除、作品禁止新增、来源同步和责任说明。本项目与 pixiv、NovelAI 无官方关系。清理默认移到本地回收区，不会远程删你的电脑文件。",
    ),
    HelpTopic(
        "knowledge",
        "本地知识库",
        "/settings#knowledgeCatalog",
        ("知识库", "使用说明", "重建知识", "帮助文档"),
        "客服小祥回答用法时先查固定主题，再检索程序内置文档（README、用户指南、免责声明等），不调用模型、不读取你的图库文件。可在设置页增量重建知识库；没有路径或 URL 参数。",
    ),
    HelpTopic(
        "vision",
        "识图与图库体检",
        "/butler",
        ("识图", "看图", "哪张好看", "比较图片", "图片评价", "图库体检", "质量检查"),
        "默认图库体检只做本地技术检查，不调用识图。只有你明确要求判断画面、比较哪张更好看或分析图片时，才会发送压缩缩略图给已配置的视觉模型；上游拒绝时会保留本地报告并明确说明。",
    ),
    HelpTopic(
        "operations",
        "运行状态与排错",
        "/ops",
        ("运行状态", "系统状态", "为什么失败", "报错", "排错", "健康", "日志", "运行情况"),
        "先在「运营」查看服务、数据库、生成、后处理和采集状态。也可以把报错原文交给客服小祥；她会结合本地任务证据解释失败位置，不会把未知外部结果说成成功，也不会自动重放可能已经扣费的操作。",
    ),
)

def _knowledge_page(source: str) -> str:
    folded = str(source or "").casefold()
    if "nai" in folded or "anima" in folded or "reference" in folded:
        return "/references"
    if "disclaimer" in folded or "responsible" in folded or "security" in folded:
        return "/compliance"
    if "pixiv" in folded or "publish" in folded:
        return "/pixiv"
    if "remix" in folded:
        return "/remix"
    if "studio" in folded:
        return "/studio"
    if "user-guide" in folded or "readme" in folded:
        return "/butler?agent=sakiko"
    return "/butler"


def looks_like_help_question(value: Any) -> bool:
    text = "".join(str(value or "").lower().split())
    if not text or len(text) > 500:
        return False
    question_signals = ("怎么", "如何", "在哪", "哪里", "什么是", "为什么", "能不能", "会不会", "可以吗", "教程", "怎么用", "使用方法", "操作方法", "帮助", "入门", "小白", "新手")
    return any(signal in text for signal in question_signals)


def looks_like_question(value: Any) -> bool:
    """Recognize answer-seeking language before it can enter the task planner."""

    text = " ".join(str(value or "").strip().split()).casefold()
    if not text or len(text) > 2_000:
        return False
    compact = text.replace(" ", "")
    if "?" in text or "？" in text:
        return True
    signals = (
        "怎么", "如何", "为什么", "什么", "哪些", "哪个", "哪张", "哪里", "在哪",
        "是否", "能不能", "能否", "可不可以", "会不会", "有没有", "多少", "怎么样",
        "怎样", "怎么看", "解释", "说明一下", "介绍一下", "告诉我", "给我建议", "评价一下",
        "what ", "why ", "how ", "where ", "which ", "can ", "could ", "should ",
    )
    if any(signal in compact for signal in signals):
        return True
    return compact.endswith(("吗", "呢", "么"))


def answer_software_question(
    value: Any,
    *,
    knowledge_catalog: KnowledgeCatalog | None = None,
) -> dict[str, Any]:
    question = " ".join(str(value or "").strip().split())
    if not question:
        raise ValueError("请输入软件使用问题")
    folded = question.casefold()
    scored = [
        (sum(2 if signal in folded else 0 for signal in topic.signals), index, topic)
        for index, topic in enumerate(TOPICS)
    ]
    score, _, topic = max(scored, key=lambda row: (row[0], -row[1]))
    if score <= 0:
        try:
            knowledge = (knowledge_catalog or get_knowledge_catalog()).search(
                question,
                limit=3,
                char_budget=1_200,
            )
        except (OSError, sqlite3.Error):
            knowledge = {"items": []}
        items = list(knowledge.get("items") or [])
        if items:
            sources = list(dict.fromkeys(str(item.get("source") or "") for item in items if item.get("source")))
            first = items[0]
            heading = str(first.get("heading") or first.get("title") or "本地说明").strip()
            excerpt = str(first.get("text") or "").strip()
            return {
                "ok": True,
                "topic": "knowledge",
                "title": heading,
                "page": _knowledge_page(str(first.get("source") or "")),
                "answer": f"{heading}：{excerpt}" if heading else excerpt,
                "provider": "local_knowledge",
                "model_calls": 0,
                "sources": sources,
            }
        return {
            "ok": True,
            "topic": "overview",
            "title": "软件使用导航",
            "page": "/butler",
            "answer": (
                "客服小祥可以回答图库搜索、采集、收藏、后处理、设置、排障和软件用法；"
                "助手凑企鹅负责换角、出图、导演和投稿准备。"
                "你可以直接说“我现在看到什么、想完成什么”，我会给出具体入口、步骤、"
                "是否消耗 Token 以及哪些动作需要确认。"
            ),
            "provider": "local_topic",
            "model_calls": 0,
            "sources": [],
        }
    return {
        "ok": True,
        "topic": topic.id,
        "title": topic.title,
        "page": topic.page,
        "answer": topic.answer,
        "provider": "local_topic",
        "model_calls": 0,
        "sources": [],
    }


def catalogue() -> list[dict[str, str]]:
    return [{"id": item.id, "title": item.title, "page": item.page} for item in TOPICS]


_PRODUCT_GUIDE_QUESTIONS = {
    "采集": "怎么启动采集",
    "生成": "怎么生图会不会消耗 Token",
    "投稿": "怎么准备 Pixiv 投稿",
    "设置": "API 和账号怎么配置",
    "故障": "为什么失败怎么排错",
    "入门": "新手小白怎么开始用",
    "换角": "怎么换角换画风",
    "助手": "客服小祥和助手凑企鹅有什么区别",
}


def product_guide(topic: Any = "全部") -> dict[str, Any]:
    """Deterministic usage guide used by the sakiko product_guide tool."""

    label = str(topic or "全部").strip() or "全部"
    if label in {"全部", "all", "*"}:
        guide = "\n\n".join(f"{item.title}（{item.page}）\n{item.answer}" for item in TOPICS)
        return {"ok": True, "topic": "全部", "guide": guide, "page": "/butler?agent=sakiko"}
    question = _PRODUCT_GUIDE_QUESTIONS.get(label, label)
    result = answer_software_question(question)
    return {
        "ok": True,
        "topic": label,
        "guide": str(result.get("answer") or ""),
        "page": str(result.get("page") or "/butler"),
    }
