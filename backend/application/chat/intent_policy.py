"""Pure intent matching used to choose Research Agent capabilities."""

from __future__ import annotations

import re


def mentions_terms(text: str, terms: tuple[str, ...]) -> bool:
    """Match terms without matching English words inside a larger word."""

    normalized_text = text.casefold()
    for term in terms:
        normalized = term.casefold().strip()
        if not normalized:
            continue
        if re.search(r"[a-z0-9]", normalized):
            pattern = rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])"
            if re.search(pattern, normalized_text):
                return True
        elif normalized in normalized_text:
            return True
    return False


def has_plan_intent(
    text: str,
    *,
    plan_terms: tuple[str, ...],
    plan_noun_terms: tuple[str, ...],
    plan_action_terms: tuple[str, ...],
) -> bool:
    """Recognize a plan action without activating on a bare noun."""

    if mentions_terms(text, plan_terms):
        return True
    return mentions_terms(text, plan_noun_terms) and mentions_terms(
        text,
        plan_action_terms,
    )


def has_document_reference(text: str) -> bool:
    """Treat an explicit paper/document identifier as a reading anchor."""

    return re.search(
        r"(?<![a-z0-9])(?:p|paper|doc|document)[-_ ]?\d+[a-z0-9_-]*(?![a-z0-9])",
        text.casefold(),
    ) is not None


COLLECTION_READ_CAPABILITIES = {
    "get_collection_context",
    "browse_collection_papers",
}
SOURCE_READ_CAPABILITIES = {
    *COLLECTION_READ_CAPABILITIES,
    "search_sources",
    "inspect_document_sources",
    "read_source",
    "inspect_table",
}
SOURCE_GROUNDED_CAPABILITIES = {
    *COLLECTION_READ_CAPABILITIES,
    "search_sources",
    "read_source",
    "inspect_table",
}
PROCESS_CAPABILITIES = {
    "get_collection_context",
    "inspect_research_process",
    "inspect_objective_analysis",
}
OBJECTIVE_CAPABILITIES = {
    "get_collection_context",
    "browse_collection_papers",
    "preview_research_scope",
    "propose_objective_drafts",
}
FINDING_CAPABILITIES = {
    *SOURCE_READ_CAPABILITIES,
    "query_published_findings",
    "inspect_published_finding",
    "inspect_objective_analysis",
    "assess_objective_quality",
    "create_finding_draft",
    "create_evidence_draft",
    "derive_objective",
}
FINDING_READ_CAPABILITIES = {
    "get_collection_context",
    "query_published_findings",
    "inspect_published_finding",
    "inspect_objective_analysis",
    "assess_objective_quality",
}
RESEARCH_PLAN_CAPABILITIES = {
    "get_collection_context",
    "query_published_findings",
    "inspect_published_finding",
    "assess_objective_quality",
    "inspect_research_plans",
    "propose_research_plan",
}
RESEARCH_PLAN_READ_CAPABILITIES = {
    "get_collection_context",
    "query_published_findings",
    "inspect_published_finding",
    "assess_objective_quality",
    "inspect_research_plans",
}
WRITE_CAPABILITIES = {
    "start_research_process",
    "create_objective_candidate",
    "confirm_objective",
    "start_objective_analysis",
    "record_finding_feedback",
    "curate_finding",
    "create_finding_version",
    "create_evidence_version",
    "publish_agent_objective_analysis",
    "create_research_plan",
    "revise_research_plan",
}

NO_TOOL_PHRASES = (
    "不用查",
    "不要查",
    "无需查",
    "不查论文",
    "不用检索",
    "不要检索",
    "不用操作",
    "不要操作",
    "without searching",
    "do not search",
    "don't search",
    "without tools",
)
NO_WRITE_PHRASES = (
    "只读", "read-only", "不要写入", "不写入",
    "不要保存",
    "不保存",
    "先不要保存",
    "不要直接修改",
    "不要修改",
    "不要发布",
    "不发布",
    "先不要发布",
    "without saving",
    "do not save",
    "don't save",
    "without modifying",
    "do not modify",
    "don't modify",
    "without publishing",
    "do not publish",
    "don't publish",
    "不要创建",
    "不创建",
    "do not create",
    "don't create",
)
PAPER_TERMS = (
    "论文",
    "文献",
    "collection",
    "paper",
    "摘要",
    "标题",
    "文件名",
    "作者",
    "article",
    "literature",
    "source",
    "表格",
    "图注",
    "阅读",
    "读取",
)
COMPARISON_TERMS = (
    "比较",
    "是否都支持",
    "可比",
    "compare",
    "supports",
    "support",
    "comparable",
)
SOURCE_GROUNDED_TERMS = (
    "根据这些论文",
    "根据论文",
    "基于这些论文",
    "基于论文",
    "文献中",
    "文献依据",
    "论文依据",
    "原文依据",
    "搜索相关论文",
    "检索相关论文",
    "搜索论文",
    "检索论文",
    "说说你的看法",
    "谈谈你的看法",
    "谈谈看法",
    "你的判断",
    "谈谈判断",
    "给出判断",
    "提出思路",
    "给出思路",
    "研究启发",
    "based on these papers",
    "based on the papers",
    "from the literature",
    "literature-based",
    "literature based",
    "what do you think",
)
SOURCE_DETAIL_TERMS = (
    "原文",
    "正文",
    "来源",
    "来源证据",
    "数值",
    "数据",
    "实验条件",
    "测试条件",
    "表格",
    "图注",
    "方法",
    "结果",
    "方法部分",
    "结果部分",
    "深入",
    "精读",
    "核对",
    "验证数字",
    "逐段",
    "表 ",
    "图 ",
    "一起看",
    "evidence",
    "method",
    "result",
    "table",
    "figure",
    "inspect",
    "read",
    "check",
)
OBJECTIVE_TERMS = (
    "研究目标",
    "研究问题",
    "目标",
    "目标草稿",
    "问题草稿",
    "候选目标",
    "objective",
    "research question",
    "follow-up question",
    "propose a focused question",
    "propose a research question",
    "draft a question",
    "suggest research questions",
    "派生",
    "推导",
    "derive",
    "derive the next",
)
FINDING_TERMS = (
    "结论",
    "证据",
    "finding",
    "evidence",
    "conclusion",
    "reviewed evidence",
    "conclusion",
    "quality",
    "gap",
    "gaps",
    "支持",
    "反例",
    "依据",
    "证据缺口",
    "冲突",
    "相反",
    "不一致",
    "候选机制",
    "一篇论文",
    "另一篇",
)
FINDING_RECORD_TERMS = (
    "已发布",
    "研究结论",
    "已有分析",
    "分析结果",
    "证据缺口",
    "依据",
    "published finding",
    "published conclusion",
    "existing analysis",
    "quality ledger",
    "evidence gap",
)
PLAN_TERMS = (
    "研究方案",
    "实验方案",
    "实验设计",
    "下一步实验",
    "怎么验证",
    "如何验证",
    "research plan",
    "experiment plan",
    "experimental plan",
    "follow-up experiment",
    "follow up experiment",
)
PLAN_NOUN_TERMS = ("plan", "plans", "方案")
PLAN_ACTION_TERMS = (
    "draft",
    "save",
    "create",
    "propose",
    "revise",
    "update",
    "edit",
    "modify",
    "inspect",
    "read",
    "review",
    "list",
    "view",
    "拟定",
    "提出",
    "保存",
    "创建",
    "修订",
    "修改",
    "查看",
    "读取",
    "列出",
)
PLAN_READ_TERMS = (
    "查看",
    "读取",
    "列出",
    "当前方案",
    "已有方案",
    "已保存的方案",
    "saved plan",
    "existing plan",
    "list plans",
    "inspect plan",
)
PROCESS_TERMS = (
    "当前状态",
    "目前状态",
    "现在的状态",
    "current status",
    "当前情况",
    "现在怎么样",
    "进度",
    "论文处理状态",
    "文档处理状态",
    "任务处理状态",
    "collection 处理状态",
    "分析状态",
    "研究状态",
    "目标状态",
    "任务状态",
    "collection 状态",
    "objective 状态",
    "处理到",
    "处理完",
    "为什么失败",
    "失败原因",
    "处理失败",
    "为什么慢",
    "哪里了",
    "progress",
    "how far",
    "process status",
    "processing status",
    "analysis status",
    "collection status",
    "objective status",
    "task status",
    "why failed",
    "analysis failed",
    "processing failed",
    "start understanding",
    "理解这些论文",
    "准备这些论文",
    "form research questions",
)
PERSIST_TERMS = (
    "保存",
    "创建",
    "记录",
    "写入",
    "发布",
    "persist",
    "save",
    "create",
    "record",
    "publish",
)
def _write_targets(text: str) -> set[str]:
    targets: set[str] = set()
    if mentions_terms(text, ("反馈", "标注", "feedback")):
        targets.add("record_finding_feedback")
    if mentions_terms(text, ("人工修订", "human revision", "curation", "curate")):
        targets.add("curate_finding")
    elif mentions_terms(text, ("修订", "revision", "revise")):
        targets.add(
            "create_evidence_version"
            if mentions_terms(text, ("evidence", "证据")) else "create_finding_version"
        )
    if mentions_terms(text, ("分析", "analysis")):
        targets.update({"start_objective_analysis", "publish_agent_objective_analysis"})
    if mentions_terms(text, ("方案", "计划", "plan")):
        targets.difference_update({"curate_finding", "create_finding_version", "create_evidence_version"})
        targets.update({"create_research_plan", "revise_research_plan"})
    if mentions_terms(text, ("新版本", "new version", "新 finding", "新finding", "独立", "new finding")):
        if not targets.intersection({"start_objective_analysis", "publish_agent_objective_analysis"}):
            targets.discard("curate_finding")
            targets.add("create_evidence_version" if mentions_terms(text, ("evidence", "证据")) else "create_finding_version")
    return targets


def _write_request_scope(text: str) -> tuple[str, set[str]]:
    # Negation belongs to an action, not every write mentioned in the message.
    # Unscoped no-save/read-only requests still prohibit all persistence.
    negations = "|".join(re.escape(term) for term in sorted(NO_WRITE_PHRASES, key=len, reverse=True))
    clauses = re.split(rf"[，。；,;.!?\n]|\bbut\b|但是|(?={negations})", text, flags=re.IGNORECASE)
    affirmative: list[str] = []
    forbidden: set[str] = set()
    for clause in clauses:
        if not mentions_terms(clause, NO_WRITE_PHRASES):
            affirmative.append(clause)
            continue
        if mentions_terms(clause, ("只读", "read-only", "任何", "anything")):
            forbidden.update(WRITE_CAPABILITIES)
        elif mentions_terms(clause, ("修改", "modify", "modifying")) and mentions_terms(
            clause, ("原", "旧", "original", "old"),
        ):
            # Immutable authorship preserves the original by contract.
            forbidden.add("curate_finding")
        elif targets := _write_targets(clause):
            forbidden.update(targets)
        elif mentions_terms(clause, ("保存", "saving", "save", "写入")):
            forbidden.update(WRITE_CAPABILITIES)
        elif mentions_terms(clause, ("发布", "publish", "publishing")):
            forbidden.update({"create_finding_version", "create_evidence_version", "publish_agent_objective_analysis"})
        else:
            forbidden.update(WRITE_CAPABILITIES)
    return " ".join(affirmative), forbidden


def capability_names_for_intent(
    user_text: str,
    *,
    has_source_context: bool,
    prior_tool_names: set[str | None],
) -> set[str]:
    def mentions(terms: tuple[str, ...]) -> bool:
        return mentions_terms(user_text, terms)

    allowed: set[str] = set()
    # Generic English words such as "method" or "result" also occur in
    # ordinary technical conversation. They only indicate Source reading
    # when the request carries a research anchor (or an attached Source).
    research_anchor = mentions(
        (
            "论文",
            "文献",
            "collection",
            "paper",
            "papers",
            "摘要",
            "标题",
            "article",
            "literature",
            "source",
            "原文",
            "来源",
            "表格",
            "table",
            "figure",
            "evidence",
            "实验",
            "research",
            "阅读",
            "读取",
        )
    )
    generic_source_detail = mentions(
        ("method", "methods", "result", "results", "read", "inspect", "check")
    )
    document_reference = has_document_reference(user_text)
    paper_intent = mentions(PAPER_TERMS) and (
        has_source_context or research_anchor
    )
    source_intent = mentions(SOURCE_DETAIL_TERMS) and (
        has_source_context
        or research_anchor
        or document_reference
        or not generic_source_detail
    )
    objective_intent = mentions(OBJECTIVE_TERMS) or "整理" in user_text
    finding_intent = mentions(FINDING_TERMS)
    finding_record_intent = mentions(FINDING_RECORD_TERMS)
    plan_intent = has_plan_intent(
        user_text,
        plan_terms=PLAN_TERMS,
        plan_noun_terms=PLAN_NOUN_TERMS,
        plan_action_terms=PLAN_ACTION_TERMS,
    )
    process_intent = mentions(PROCESS_TERMS)
    source_grounded_intent = mentions(SOURCE_GROUNDED_TERMS)

    if paper_intent:
        allowed.update(COLLECTION_READ_CAPABILITIES)
    if has_source_context or source_intent:
        allowed.update(SOURCE_READ_CAPABILITIES)
    if paper_intent and source_grounded_intent:
        allowed.update(SOURCE_GROUNDED_CAPABILITIES)
    if objective_intent:
        allowed.update(OBJECTIVE_CAPABILITIES)
        if mentions(
            (
                "派生",
                "推导",
                "从证据缺口形成",
                "从结论形成下一",
                "下一轮研究目标",
                "derive",
                "derive objective",
                "derive a new objective",
            )
        ):
            allowed.add("derive_objective")
    if plan_intent:
        allowed.update(RESEARCH_PLAN_CAPABILITIES)
    elif finding_intent:
        # Reviewing a conclusion is a read first. Draft and mutation
        # capabilities are added only by their explicit action branches
        # below, so a question about a gap cannot expose write schemas.
        paper_comparison = paper_intent and mentions_terms(
            user_text, ("冲突", "相反", "不一致", "候选机制")
        )
        if finding_record_intent:
            allowed.update(FINDING_READ_CAPABILITIES)
        if has_source_context or source_intent or paper_comparison:
            allowed.update(SOURCE_READ_CAPABILITIES)
    if process_intent:
        allowed.update(PROCESS_CAPABILITIES)

    continuation_intent = mentions(
        ("继续", "再看", "再读", "追加", "排除", "一起看", "continue", "also")
    )
    if continuation_intent:
        for tool_name in prior_tool_names:
            if tool_name in SOURCE_READ_CAPABILITIES:
                allowed.update(SOURCE_READ_CAPABILITIES)
            elif tool_name in OBJECTIVE_CAPABILITIES:
                allowed.update(OBJECTIVE_CAPABILITIES)
            elif tool_name in FINDING_CAPABILITIES:
                allowed.update(FINDING_READ_CAPABILITIES)
            elif tool_name in RESEARCH_PLAN_CAPABILITIES:
                allowed.update(RESEARCH_PLAN_READ_CAPABILITIES)
            elif tool_name in PROCESS_CAPABILITIES:
                allowed.update(PROCESS_CAPABILITIES)

    write_text, forbidden_writes = _write_request_scope(user_text)
    def write_mentions(terms: tuple[str, ...]) -> bool:
        return mentions_terms(write_text, terms)

    persist_intent = write_mentions(PERSIST_TERMS)
    if persist_intent and objective_intent and not _write_targets(write_text).intersection({
        "record_finding_feedback", "curate_finding", "create_finding_version",
    }):
        allowed.add("create_objective_candidate")
    confirm_requested = write_mentions(
        (
            "确认目标",
            "确认这个目标",
            "confirm objective",
            "confirm the reviewed question",
            "confirm this question",
        )
    ) and not mentions(
        (
            "不要确认",
            "不确认",
            "先不要确认",
            "without confirming",
            "do not confirm",
            "don't confirm",
        )
    )
    if confirm_requested:
        allowed.add("confirm_objective")
    analysis_explicitly_deferred = mentions(
        (
            "不要启动分析",
            "不启动分析",
            "先不要启动分析",
            "without starting analysis",
            "do not start analysis",
            "don't start analysis",
        )
    )
    if (
        write_mentions(("开始分析", "启动分析", "分析这个目标", "start analysis"))
        and not analysis_explicitly_deferred
    ):
        allowed.update(PROCESS_CAPABILITIES)
        allowed.add("start_objective_analysis")
    if not analysis_explicitly_deferred and write_mentions(
        (
            "analyze this",
            "分析这个研究问题",
            "分析这个目标",
            "开始分析",
            "启动分析",
        )
    ):
        allowed.add("start_objective_analysis")
    if write_mentions(
        (
            "start understanding",
            "开始理解",
            "开始了解",
            "form research questions",
        )
    ):
        allowed.add("start_research_process")
    if write_mentions(("准备论文", "处理论文", "重新处理", "重试论文", "prepare papers")):
        allowed.add("start_research_process")
    if persist_intent and plan_intent:
        allowed.add("create_research_plan")
    if plan_intent and write_mentions(("修改", "修订", "调整", "revise", "update")):
        allowed.add("revise_research_plan")
    if finding_intent and persist_intent:
        finding_writes = {
                "record_finding_feedback",
                "curate_finding",
                "create_finding_version",
        }
        targets = _write_targets(write_text)
        allowed.update(finding_writes.intersection(targets) if targets else finding_writes)
    if finding_intent and mentions(
        ("结论草案", "修订草案", "finding draft", "draft finding")
    ):
        allowed.add("create_finding_draft")
    if finding_intent and write_mentions(("标记", "标为", "mark")):
        allowed.add("record_finding_feedback")
    evidence_write_intent = write_mentions(
        (
            "记录证据",
            "保存证据",
            "修订证据",
            "record evidence",
            "save evidence",
            "revise evidence",
            "correct evidence",
            "update evidence",
        )
    ) or (
        persist_intent and write_mentions(("evidence", "证据"))
        and (not _write_targets(write_text) or "create_evidence_version" in _write_targets(write_text))
    )
    if evidence_write_intent:
        allowed.add("create_evidence_version")
    if write_mentions(("发布分析", "保存分析")) or (
        write_mentions(("publish",)) and write_mentions(("analysis",))
    ):
        allowed.add("publish_agent_objective_analysis")
    allowed.difference_update(forbidden_writes)
    return allowed
