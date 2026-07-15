from __future__ import annotations

import re

_VED_PATTERN = re.compile(
    r"\bVED\b|volumetric\s+energy\s+density|体积能量密度",
    re.IGNORECASE,
)
_VED_MANIPULATION_PATTERN = re.compile(
    r"\b(?:vary|change|adjust|increase|decrease|compare|sweep|"
    r"low|moderate|medium|high|level|levels|gradient|matrix)\b|"
    r"改变|变化|调节|增加|降低|比较|水平|梯度|矩阵",
    re.IGNORECASE,
)
_COMPONENT_CHANGE_PATTERN = re.compile(
    r"\b(?:vary|varied|varying|change|changed|changing|adjust|adjusted|"
    r"adjusting|increase|increased|increasing|decrease|decreased|"
    r"decreasing|compare|compared|comparing|sweep|swept)\b|"
    r"改变|变化|调节|增加|降低|比较",
    re.IGNORECASE,
)
_FIXED_PATTERN = re.compile(
    r"\b(?:hold|held|holding|keep|kept|keeping|maintain|maintained|"
    r"maintaining|fix|fixed|constant|controlled|unchanged|same)\b|"
    r"保持|固定|恒定|不变|相同|控制",
    re.IGNORECASE,
)
_PROPOSED_CHOICE_PATTERN = re.compile(
    r"(?:Proposed\s+design\s+choice|拟议设计选择)\s*[:：]\s*(.+)",
    re.IGNORECASE,
)
_CLAUSE_BOUNDARY_PATTERN = re.compile(
    r"[;；。\n]+|"
    r",\s*(?=(?:hold|keep|maintain|fix|vary|change|adjust|increase|decrease)\b)|"
    r"，\s*(?=(?:保持|固定|改变|调节|增加|降低))|"
    r"\bwhile\b|\bwhereas\b|"
    r"\band\s+(?=(?:hold|keep|maintain|fix|vary|change|adjust|increase|decrease)\b)|"
    r"同时(?=(?:保持|固定|改变|调节|增加|降低))",
    re.IGNORECASE,
)
_VED_COMPONENT_PATTERNS = {
    "laser_power": re.compile(r"\blaser\s+power\b|激光功率", re.IGNORECASE),
    "scan_speed": re.compile(
        r"\bscan(?:ning)?\s+speed\b|扫描速度",
        re.IGNORECASE,
    ),
    "hatch_spacing": re.compile(
        r"\b(?:hatch|scan)\s+spacing\b|道间距|扫描间距",
        re.IGNORECASE,
    ),
    "layer_thickness": re.compile(
        r"\blayer\s+thickness\b|层厚",
        re.IGNORECASE,
    ),
}
_VED_ISOLATION_PATTERN = re.compile(
    r"\bisolat(?:e|es|ed|ing)\s+(?:an?\s+|the\s+)?"
    r"(?:(?:effect|impact)\s+of\s+)?"
    r"(?:(?:universal|independent|direct)\s+)?"
    r"(?:VED(?:-only)?|volumetric\s+energy\s+density)"
    r"(?:\s+(?:effect|impact))?|"
    r"(?:\bVED(?:-only)?\b|volumetric\s+energy\s+density)"
    r"\s+(?:effect|impact)\s+(?:is|was|can\s+be)\s+isolat(?:ed|able)|"
    r"(?:隔离|独立识别|分离)(?:了|出)?(?:体积能量密度|VED)"
    r"(?:的)?(?:单变量|独立|直接|普适)?(?:效应|影响)?",
    re.IGNORECASE,
)
_NEGATION_BEFORE_PATTERN = re.compile(
    r"(?:\bnot\b|\bnever\b|\bcannot\b|\bcan['’]t\b)"
    r"(?:\s+\w+){0,3}\s*$|(?:不能|不可|无法|并非|不)\s*$",
    re.IGNORECASE,
)
_VARIABLE_LABELS = ("Variable matrix", "变量矩阵", "变量")
_MEASUREMENT_LABELS = (
    "Measurements",
    "Measurement",
    "测量",
    "测试指标",
    "表征",
)
_CONTROL_LABELS = ("Controls", "Control", "控制", "对照")
_RISK_LABELS = (
    "Risks or limits",
    "Risk or limit",
    "风险或限制",
    "风险与限制",
    "风险",
    "限制",
)


def ved_design_is_scientifically_consistent(content: str) -> bool:
    """Return whether a VED design has operational and causal boundaries."""

    if has_affirmative_ved_isolation_claim(content):
        return False

    variable_section = _section(content, _VARIABLE_LABELS, _MEASUREMENT_LABELS)
    if not variable_section or not _VED_PATTERN.search(variable_section):
        return True

    proposed_choices = [
        match.group(1).strip()
        for line in variable_section.splitlines()
        if (match := _PROPOSED_CHOICE_PATTERN.search(line))
    ]
    design_text = "\n".join(proposed_choices) or variable_section
    mentions_constituent = any(
        pattern.search(design_text) for pattern in _VED_COMPONENT_PATTERNS.values()
    )
    if not _VED_MANIPULATION_PATTERN.search(design_text) or not (
        _VED_PATTERN.search(design_text) or mentions_constituent
    ):
        return True

    changed = _components_with_action(design_text, _COMPONENT_CHANGE_PATTERN)
    controls = _section(content, _CONTROL_LABELS, _RISK_LABELS)
    fixed = _components_with_action(
        "\n".join((design_text, controls)),
        _FIXED_PATTERN,
    )
    components = set(_VED_COMPONENT_PATTERNS)
    return bool(changed) and not changed.intersection(fixed) and (
        changed.union(fixed) == components
    )


def has_affirmative_ved_isolation_claim(content: str) -> bool:
    for match in _VED_ISOLATION_PATTERN.finditer(content):
        prefix = content[max(0, match.start() - 48) : match.start()]
        if not _NEGATION_BEFORE_PATTERN.search(prefix):
            return True
    return False


def proposed_design_choice_has_unsupported_detail(item: str) -> bool:
    if any(character.isdigit() for character in item):
        return True
    acronyms = re.findall(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*\b", item)
    return any(acronym != "VED" for acronym in acronyms)


def proposed_design_choices_are_source_independent(content: str) -> bool:
    return all(
        not proposed_design_choice_has_unsupported_detail(match.group(1))
        for line in content.splitlines()
        if (match := _PROPOSED_CHOICE_PATTERN.search(line))
    )


def _section(
    content: str,
    start_labels: tuple[str, ...],
    end_labels: tuple[str, ...],
) -> str:
    start = "|".join(re.escape(label) for label in start_labels)
    end = "|".join(re.escape(label) for label in end_labels)
    start_match = re.search(
        rf"^\s*(?:#+\s*)?(?:\*\*)?(?:{start})(?:\*\*)?\s*[:：]?",
        content,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if start_match is None:
        return ""
    end_match = re.search(
        rf"^\s*(?:#+\s*)?(?:\*\*)?(?:{end})(?:\*\*)?\s*[:：]?",
        content[start_match.end() :],
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if end_match is None:
        return content[start_match.end() :].strip()
    return content[
        start_match.end() : start_match.end() + end_match.start()
    ].strip()


def _components_with_action(text: str, action_pattern: re.Pattern[str]) -> set[str]:
    components: set[str] = set()
    for clause in _CLAUSE_BOUNDARY_PATTERN.split(text):
        if not action_pattern.search(clause):
            continue
        components.update(
            name
            for name, pattern in _VED_COMPONENT_PATTERNS.items()
            if pattern.search(clause)
        )
    return components
