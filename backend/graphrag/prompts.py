from textwrap import dedent


def build_extraction_prompt(text: str) -> str:
    text = text[:2000]  # keep prompt compact
    return dedent(
        f"""
        从下面的段落抽取结构化的实验知识图谱三元组。请输出 JSON 数组，每个元素包含：
        head, head_type, relation, tail, tail_type, confidence(0-1，可选), attrs(可选，字典)。
        head_type / tail_type 尽量使用: Material, Condition, Equipment, Procedure, Outcome, Parameter, Metric。
        relation 示例：uses, requires, improves, degrades, causes, step_of, measured_by, part_of。
        仅输出 JSON，不要解释。

        段落:
        {text}
        """
    ).strip()


def build_answer_prompt(query: str, context: str, mode: str = "optimize") -> str:
    mode = mode or "optimize"
    mode_instructions = (
        "生成针对目标的实验优化建议，说明哪些条件/参数/设备/材料与目标正相关，推荐的调整方向，并引用来源页码。"
        if mode == "optimize"
        else "汇总实验方法/流程，列出关键步骤、条件和设备，并引用来源页码。"
    )
    return dedent(
        f"""
        你是科研实验设计助手。目标: {query}
        {mode_instructions}
        仅使用提供的图谱证据回答，不要虚构。

        图谱证据:
        {context}
        """
    ).strip()


SYSTEM_PROMPT = "你擅长阅读实验知识图谱并给出简洁、可执行的中文建议，保持条理清晰。"


def build_community_summary_prompt(community_id: str, members: list) -> str:
    return dedent(
        f"""
        将下面社区的成员节点整理成一句简明的主题摘要，突出主要实体和过程。
        社区: {community_id}
        成员: {", ".join(members)}
        输出一段摘要，不要列表。
        """
    ).strip()
