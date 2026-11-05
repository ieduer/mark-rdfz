import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple
import requests

from app.client.haidian_client import detect_mime_type, format_score_str

logger = logging.getLogger("ai_grader")

# ==============================================================================
# Subject & Prompt Template Catalog (Reference: mark.bdfz.net templates.ts)
# ==============================================================================

SUBJECT_TEMPLATES: List[Dict[str, Any]] = [
    {
        "key": "yw_modern_reading",
        "subject": "语文",
        "name": "语文 · 现代文阅读（分点给分）",
        "description": "适用于现代文/散文/小说阅读题，按采分点逐点判分。",
        "slots": [
            {"key": "question", "label": "题目和题干", "rows": 3, "hint": "原题目和题干（含分值），例如：「请简要分析作者笔下的三种『梦』。（6分）」"},
            {"key": "ref_answer", "label": "参考答案", "rows": 4, "hint": "标准答案文本，逐点列出。"},
            {"key": "rubric", "label": "评分标准（每行一条 point_*）", "rows": 5, "hint": "格式：point_1 | 要点一说明（2分） | 意近即可给分\npoint_2 | 要点二说明（2分） | 结合文本分析给分"}
        ],
        "skeleton": """你是一名经验丰富的语文阅卷老师。请先 OCR 识别图片中学生的手写答案，再按下方规则严格判分。

【题目和题干】
{{question}}

【参考答案】
{{ref_answer}}

【评分标准】
{{rubric}}"""
    },
    {
        "key": "yw_classical_translate",
        "subject": "语文",
        "name": "语文 · 古诗文默写与文言翻译",
        "description": "适用于古诗文默写（错别字扣分）或文言文翻译（关键词+句意给分）。",
        "slots": [
            {"key": "question", "label": "原文 / 默写题干", "rows": 3, "hint": "填写默写题干或文言文待译原句"},
            {"key": "ref_answer", "label": "标准答案 / 标准译文", "rows": 4, "hint": "填写标准默写句或参考译文"},
            {"key": "rubric", "label": "关键采分点（每行一条 point_*）", "rows": 5, "hint": "如：\npoint_1 | 第一空/采分点1（2分） | 有错别字、漏字、添字该空0分\npoint_2 | 第二空/采分点2（2分） | 意思对且无错别字给满分"}
        ],
        "skeleton": """你是一名严谨的语文阅卷老师，请仔细核对图片中学生的古诗文默写或文言翻译字迹并判分。

【原文 / 题干】
{{question}}

【参考答案 / 译文】
{{ref_answer}}

【关键采分点】
{{rubric}}

判分流程：
1. 逐字 OCR 识别学生手写内容（注意甄别形近字、通假字及涂改痕迹，划掉的内容不计入）。
2. 逐条对照采分点判分；古诗文默写每空有错字、别字、漏字、添字均不得分；文言翻译关键词准确且句意通顺给分。"""
    },
    {
        "key": "sx_step_score",
        "subject": "数学/理化",
        "name": "数学 / 物理 / 化学 · 解答题分步得分",
        "description": "按解题关键步骤、公式列写与计算结果分步给分。",
        "slots": [
            {"key": "question", "label": "题目和题干", "rows": 3, "hint": "填写解答题题干及各小问分值"},
            {"key": "ref_answer", "label": "标准解答（含步骤）", "rows": 5, "hint": "粘贴标准解题过程与最终结果"},
            {"key": "rubric", "label": "分步评分细则（每行一条 point_*）", "rows": 5, "hint": "如：\npoint_setup | 列出关键方程/定理（2分） | 缺方程0分\npoint_calc | 化简推导过程（2分） | 过程正确给分\npoint_ans | 最终结果正确（2分） | 结果错0分"}
        ],
        "skeleton": """你是一名经验丰富的理科阅卷老师。请按分步评分细则判分。

【识别说明】
- 数学公式尽量还原为 LaTeX 或清晰表达式，化学方程式保留反应条件与配平系数。
- 允许等价解法（如不同变量名、不同几何/代数路径但推导严密且结果正确）。

【题目和题干】
{{question}}

【标准解答】
{{ref_answer}}

【分步评分细则】
{{rubric}}"""
    },
    {
        "key": "yy_writing",
        "subject": "英语",
        "name": "英语 · 书面表达 / 读写综合",
        "description": "按内容要点、语法词汇准确性、篇章连贯性分维度判分。",
        "slots": [
            {"key": "question", "label": "写作任务说明 (Task)", "rows": 3, "hint": "填写英语作文题目要求与要点"},
            {"key": "ref_answer", "label": "范文 / 要点参考", "rows": 4, "hint": "填写必含内容要点或参考范文"},
            {"key": "rubric", "label": "评分维度（每行一条 point_*）", "rows": 5, "hint": "point_content | 内容要点完整度 | 覆盖所有要点给满分\npoint_lang | 语法与词汇准确性 | 语法准确、句式丰富\npoint_coherence | 篇章结构与连贯性 | 衔接自然、字数达标"}
        ],
        "skeleton": """You are an experienced English writing examiner. Read the handwritten student response in the image and grade it strictly according to the rubric.

【Task】
{{question}}

【Reference / Key Points】
{{ref_answer}}

【Rubric】
{{rubric}}"""
    },
    {
        "key": "ws_material",
        "subject": "政史地/生",
        "name": "政史地生 · 材料分析 / 实验探究题",
        "description": "适用于文科材料概括分析题或理科实验操作结论题。",
        "slots": [
            {"key": "question", "label": "题目与材料要求", "rows": 3, "hint": "填写设问及分值"},
            {"key": "ref_answer", "label": "参考答案", "rows": 4, "hint": "标准答案各要点"},
            {"key": "rubric", "label": "评分标准（每行一条 point_*）", "rows": 5, "hint": "point_1 | 角度一/步骤一（2分） | 言之成理即可\npoint_2 | 角度二/结论二（2分） | 结合材料给分"}
        ],
        "skeleton": """你是一名资深阅卷老师，请先 OCR 识别图片中学生的手写答案，再按评分细则逐点判分。

【题目与设问】
{{question}}

【参考答案】
{{ref_answer}}

【评分标准】
{{rubric}}"""
    },
    {
        "key": "generic",
        "subject": "通用",
        "name": "通用 · 自定义评分指令",
        "description": "适用于任意学科与题型，自由定义题目、答案与采分点。",
        "slots": [
            {"key": "question", "label": "题目说明（可选）", "rows": 2, "hint": "简述题目要求"},
            {"key": "ref_answer", "label": "参考答案", "rows": 4, "hint": "输入标准答案"},
            {"key": "rubric", "label": "给分细则（支持每行 point_* 或自由描述）", "rows": 6, "hint": "如：\npoint_1 | 第一点（2分） | 答出核心概念给2分\npoint_2 | 第二点（2分） | 分析合理给2分"}
        ],
        "skeleton": """请先完整 OCR 识别图片中学生的手写答案，再严格按照下方评分细则给分。

【题目说明】
{{question}}

【参考答案】
{{ref_answer}}

【评分细则】
{{rubric}}"""
    }
]


def extract_point_keys(text: str) -> List[Dict[str, str]]:
    """Extract point_* definitions from rubric text (e.g. 'point_1 | 要点名称 | 说明')."""
    points: List[Dict[str, str]] = []
    seen = set()
    for line in (text or "").splitlines():
        s = line.strip()
        if not s:
            continue
        m = re.match(r"^(point_[A-Za-z0-9_]+)\s*(?:\||｜|:|：|-)\s*([^|｜\n]+)(?:\s*(?:\||｜)\s*(.+))?$", s)
        if m:
            key = m.group(1).strip()
            label = m.group(2).strip()
            rule = (m.group(3) or "").strip()
            if key not in seen:
                seen.add(key)
                points.append({"key": key, "label": label, "rule": rule})
    return points


def render_template_prompt(template_key: str, slots: Dict[str, str], full_score: float = 6.0) -> str:
    tpl = next((t for t in SUBJECT_TEMPLATES if t["key"] == template_key), SUBJECT_TEMPLATES[-1])
    out = tpl["skeleton"]
    for slot in tpl["slots"]:
        k = slot["key"]
        val = (slots.get(k) or "").strip() or "（按试卷作答及常规评分标准判分）"
        out = out.replace(f"{{{{{k}}}}}", val)

    points = extract_point_keys(slots.get("rubric", ""))
    if points:
        pf_lines = []
        for p in points:
            short = p["key"].replace("point_", "", 1)
            pf_lines.append(f'  "{p["key"]}": <数字得分 ({p["label"]})>,\n  "comment_{short}": "该点给分/扣分依据"')
        point_fields_block = ",\n".join(pf_lines) + ","
    else:
        point_fields_block = '  "point_1": <第一采分点数字得分>,\n  "comment_1": "该点给分/扣分依据",'

    out += f"""

【本题满分】{full_score:g} 分

【你要输出的 JSON 结构】（只输出合法 JSON，禁止 ``` 包裹，禁止任何 JSON 之外的文字）：
{{
  "student_answer": "图片中识别出的学生手写原文（保留换行，涂改划掉的不计）",
{point_fields_block}
  "final_score": <所有得分点相加后的最终总分，范围 0 ~ {full_score:g}>,
  "overall_comment": "整体评语（简述得分依据与扣分原因）",
  "is_blank": false,
  "is_excellence": false,
  "needs_arbitration": false
}}"""
    return out


# ==============================================================================
# AI Grader Engine — Latest Gen & Previous 3 Gens Multimodal Vision Catalog (2026)
# ==============================================================================

class AIGrader:
    """
    Multi-provider Vision AI Grader for mark.rdfz.net (Reference: mark.bdfz.net v1.1.88).
    Strictly includes only Vision-capable (图文识别) models from the latest generation
    and the previous 3 generations for Gemini, DeepSeek, Claude, and OpenAI.
    """

    SUPPORTED_MODELS: Dict[str, Dict[str, Any]] = {
        "gemini": {
            "name": "Google Gemini",
            "default_base_url": "https://generativelanguage.googleapis.com/v1beta",
            "default_model": "gemini-3.8-flash",
            "default_thinking": "medium",
            "key_placeholder": "粘贴 Gemini API Key (AIzaSy...)，支持多 Key 逗号分隔自动轮询",
            "thinking_options": [
                {"value": "low", "label": "low（快速）"},
                {"value": "medium", "label": "medium（均衡推荐）"},
                {"value": "high", "label": "high（深度推理，最准）"},
            ],
            "models": [
                {
                    "id": "gemini-4-argon",
                    "name": "Gemini 4 Argon（最新一代旗舰推理视觉 · 2026-10）",
                    "generation": "Gen 4 (最新旗舰)",
                    "supports_thinking": True,
                    "can_read_images": True,
                },
                {
                    "id": "gemini-3.8-flash",
                    "name": "Gemini 3.8 Flash（最新一代高速主力 · 2026-09 推荐）",
                    "generation": "Gen 3.8 (最新主力)",
                    "supports_thinking": True,
                    "can_read_images": True,
                },
                {
                    "id": "gemini-3.7-flash",
                    "name": "Gemini 3.7 Flash（前一代稳定主力 · 2026-08）",
                    "generation": "Gen 3.7 (前一代)",
                    "supports_thinking": True,
                    "can_read_images": True,
                },
                {
                    "id": "gemini-3.6-flash",
                    "name": "Gemini 3.6 Flash（前两代稳定回退 · 2026-07）",
                    "generation": "Gen 3.6 (前两代)",
                    "supports_thinking": True,
                    "can_read_images": True,
                },
                {
                    "id": "gemini-3.5-flash",
                    "name": "Gemini 3.5 Flash（前三代兼容回退）",
                    "generation": "Gen 3.5 (前三代)",
                    "supports_thinking": False,
                    "can_read_images": True,
                },
            ],
        },
        "openai": {
            "name": "OpenAI (GPT)",
            "default_base_url": "https://api.openai.com/v1",
            "default_model": "gpt-6.1-terra",
            "default_thinking": "medium",
            "key_placeholder": "粘贴 OpenAI API Key (sk-...)，支持多 Key 逗号分隔自动轮询",
            "thinking_options": [
                {"value": "none", "label": "none（最快）"},
                {"value": "low", "label": "low"},
                {"value": "medium", "label": "medium（推荐）"},
                {"value": "high", "label": "high"},
                {"value": "xhigh", "label": "xhigh（最强深度推理）"},
            ],
            "models": [
                {
                    "id": "gpt-6.1-terra",
                    "name": "GPT-6.1 Terra（最新一代高速高性价比视觉 · 推荐）",
                    "generation": "GPT-6.1 (最新代)",
                    "supports_thinking": True,
                    "can_read_images": True,
                },
                {
                    "id": "gpt-6.1-sol",
                    "name": "GPT-6.1 Sol（最新一代高阶专业多模态推理）",
                    "generation": "GPT-6.1 (最新代)",
                    "supports_thinking": True,
                    "can_read_images": True,
                },
                {
                    "id": "gpt-6-astra",
                    "name": "GPT-6 Astra（最新一代旗舰多模态推理）",
                    "generation": "GPT-6 (最新旗舰)",
                    "supports_thinking": True,
                    "can_read_images": True,
                },
                {
                    "id": "gpt-5.6",
                    "name": "GPT-5.6（前一代全能多模态主力）",
                    "generation": "GPT-5.6 (前一代)",
                    "supports_thinking": True,
                    "can_read_images": True,
                },
                {
                    "id": "gpt-5.5",
                    "name": "GPT-5.5（前两代多模态推理模型）",
                    "generation": "GPT-5.5 (前两代)",
                    "supports_thinking": True,
                    "can_read_images": True,
                },
                {
                    "id": "gpt-5.4",
                    "name": "GPT-5.4（前三代高分辨率原图视觉旗舰）",
                    "generation": "GPT-5.4 (前三代)",
                    "supports_thinking": True,
                    "can_read_images": True,
                },
                {
                    "id": "gpt-5.4-mini",
                    "name": "GPT-5.4 Mini（前三代轻量高速视觉）",
                    "generation": "GPT-5.4 (前三代)",
                    "supports_thinking": True,
                    "can_read_images": True,
                },
            ],
        },
        "claude": {
            "name": "Anthropic Claude",
            "default_base_url": "https://api.anthropic.com/v1",
            "default_model": "claude-sonnet-5-5",
            "default_thinking": "medium",
            "key_placeholder": "粘贴 Claude API Key (sk-ant-...)，支持多 Key 逗号分隔自动轮询",
            "thinking_options": [
                {"value": "none", "label": "默认自适应 (Adaptive)"},
                {"value": "low", "label": "low（快速）"},
                {"value": "medium", "label": "medium（均衡推荐）"},
                {"value": "high", "label": "high（深度思考）"},
            ],
            "models": [
                {
                    "id": "claude-sonnet-5-5",
                    "name": "Claude Sonnet 5.5（最新一代均衡主力 · 2026-09 推荐）",
                    "generation": "Claude 5.5 (最新代)",
                    "supports_thinking": True,
                    "can_read_images": True,
                },
                {
                    "id": "claude-opus-5-5",
                    "name": "Claude Opus 5.5（最新一代旗舰深度判卷 · 2026-09）",
                    "generation": "Claude 5.5 (最新旗舰)",
                    "supports_thinking": True,
                    "can_read_images": True,
                },
                {
                    "id": "claude-fable-5-1",
                    "name": "Claude Fable 5.1（最新一代高阶长程推理 · 2026-09）",
                    "generation": "Claude 5.1 Fable (最新代)",
                    "supports_thinking": True,
                    "can_read_images": True,
                },
                {
                    "id": "claude-haiku-5-5",
                    "name": "Claude Haiku 5.5（最新一代极速轻量视觉 · 2026-09）",
                    "generation": "Claude 5.5 (最新代)",
                    "supports_thinking": False,
                    "can_read_images": True,
                },
                {
                    "id": "claude-sonnet-5",
                    "name": "Claude Sonnet 5（前一代主力视觉 · 2026-06）",
                    "generation": "Claude 5.0 (前一代)",
                    "supports_thinking": True,
                    "can_read_images": True,
                },
                {
                    "id": "claude-fable-5",
                    "name": "Claude Fable 5（前一代高阶推理视觉）",
                    "generation": "Claude 5.0 (前一代)",
                    "supports_thinking": True,
                    "can_read_images": True,
                },
                {
                    "id": "claude-opus-4-8",
                    "name": "Claude Opus 4.8（前两代旗舰视觉 · 2026-05）",
                    "generation": "Claude 4.8 (前两代)",
                    "supports_thinking": True,
                    "can_read_images": True,
                },
                {
                    "id": "claude-sonnet-4-6",
                    "name": "Claude Sonnet 4.6（前三代稳定兼容视觉）",
                    "generation": "Claude 4.6 (前三代)",
                    "supports_thinking": False,
                    "can_read_images": True,
                },
            ],
        },
        "deepseek": {
            "name": "DeepSeek (官方多模态视觉)",
            "default_base_url": "https://api.deepseek.com",
            "default_model": "deepseek-flash",
            "default_thinking": "high",
            "key_placeholder": "粘贴 DeepSeek API Key (sk-...)，支持多 Key 逗号分隔自动轮询",
            "thinking_options": [
                {"value": "disabled", "label": "关闭（最快）"},
                {"value": "low", "label": "low（轻量思考）"},
                {"value": "high", "label": "high（官方默认，推荐）"},
                {"value": "max", "label": "max（最强推理，较慢）"},
            ],
            "models": [
                {
                    "id": "deepseek-flash",
                    "name": "DeepSeek Flash / V4.1-Flash（最新一代官方原生多模态视觉 · 推荐）",
                    "generation": "V4.1-Flash (最新代)",
                    "supports_thinking": True,
                    "can_read_images": True,
                },
                {
                    "id": "deepseek-v4-flash-vision-exp",
                    "name": "DeepSeek V4 Flash Vision Exp（前一代官方多模态视觉模型）",
                    "generation": "V4-Flash-Vision (前一代)",
                    "supports_thinking": True,
                    "can_read_images": True,
                },
                {
                    "id": "janus-pro-7b",
                    "name": "DeepSeek Janus-Pro 7B（前两代统一多模态理解模型 · 兼容网关）",
                    "generation": "Janus-Pro (前两代)",
                    "supports_thinking": False,
                    "can_read_images": True,
                },
                {
                    "id": "deepseek-vl2",
                    "name": "DeepSeek-VL2（前三代 MoE 视觉理解模型 · 兼容网关）",
                    "generation": "DeepSeek-VL2 (前三代)",
                    "supports_thinking": False,
                    "can_read_images": True,
                },
            ],
        },
    }

    @classmethod
    def get_supported_models(cls) -> Dict[str, Any]:
        return cls.SUPPORTED_MODELS

    @classmethod
    def get_templates(cls) -> List[Dict[str, Any]]:
        return SUBJECT_TEMPLATES

    @staticmethod
    def parse_api_keys(raw_keys: str) -> List[str]:
        """Normalize comma/semicolon/newline/Chinese-comma separated API keys."""
        if not raw_keys:
            return []
        normalized = re.sub(r"[，；;、\r\n\t\s]+", ",", raw_keys.strip())
        return [k.strip() for k in normalized.split(",") if k.strip()]

    @staticmethod
    def _clean_json_text(text: str) -> str:
        text = (text or "").strip()
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            return match.group(0)
        return text

    @staticmethod
    def _snap_to_markdic(score: float, full_score: float, markdic_list: Optional[List[str]] = None) -> float:
        score = max(0.0, min(float(full_score), float(score)))
        if markdic_list:
            valid_nums = []
            for item in markdic_list:
                try:
                    valid_nums.append(float(item))
                except Exception:
                    pass
            if valid_nums:
                return min(valid_nums, key=lambda x: abs(x - score))
        return round(score * 2) / 2.0

    @classmethod
    def _build_prompt(
        cls,
        rubric: str,
        full_score: float,
        markdic_list: Optional[List[str]] = None,
        sub_questions: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        step_hint = ""
        if markdic_list and len(markdic_list) <= 40:
            step_hint = f"\n- 本题合法给分分值集合为: [{', '.join(markdic_list)}]，最终得分必须取自该集合。"

        sub_hint = ""
        sub_json_example = ""
        if sub_questions and len(sub_questions) > 1:
            sub_lines = []
            sub_ex = []
            for sq in sub_questions:
                valid_str = f"，合法分值: [{','.join(sq.get('markdic_list', []))}]" if sq.get("markdic_list") else ""
                sub_lines.append(f"  * 子题 [{sq['index']}] 「{sq['name']}」：满分 {sq['fullmark']} 分{valid_str}")
                sub_ex.append(
                    f'    {{"index": {sq["index"]}, "name": "{sq["name"]}", "score": 0, '
                    f'"max_score": {sq["fullmark"]}, "reason": "给分理由"}}'
                )
            sub_hint = "\n【复合分项小题要求（必须分别给分）】\n" + "\n".join(sub_lines)
            sub_json_example = ',\n  "sub_scores": [\n' + ",\n".join(sub_ex) + "\n  ]"

        # Check if rubric already contains point_* structure from template
        points = extract_point_keys(rubric)
        if points:
            pf_lines = []
            for p in points:
                short = p["key"].replace("point_", "", 1)
                pf_lines.append(f'  "{p["key"]}": 0,\n  "comment_{short}": "该点给分/扣分依据"')
            point_fields_str = ",\n".join(pf_lines) + ","
        else:
            point_fields_str = '  "point_1": 0,\n  "comment_1": "采分点1给分依据",'

        if "【你要输出的 JSON 结构】" in rubric and not sub_json_example:
            return rubric + step_hint

        return f"""你是一位经验丰富、严谨公正的中学阅卷专家。请仔细查看图片中的学生手写答卷，完成字迹识别（OCR）并严格按照评分细则进行逐点评分。

【题目满分】
{full_score:g} 分{step_hint}{sub_hint}

【评分指令与细则】
{rubric}

【输出格式要求】
请严格只输出一个合法的 JSON 对象（不要使用 markdown 代码块包裹，不要输出任何额外解释文字），格式如下：
{{
  "student_answer": "逐字识别出的学生手写原文（保留换行，如空白填『未作答』）",
{point_fields_str}
  "final_score": 0,
  "overall_comment": "简明扼要的总体判分依据与扣分原因",
  "is_blank": false,
  "is_excellence": false,
  "needs_arbitration": false{sub_json_example}
}}

注意：
1. `final_score` 必须是 0 到 {full_score:g} 之间的数字，且等于所有 `point_*`（或 `sub_scores`）得分之和。
2. 如学生答卷完全空白或毫无作答痕迹，请将 `is_blank` 设为 true，`final_score` 设为 0，`overall_comment` 写「未作答」。
3. 如学生字迹极端模糊、图像严重残缺或存在重大争议无法判定，请将 `needs_arbitration` 设为 true。
4. 如学生答案条理极其清晰、堪称满分范本，可将 `is_excellence` 设为 true。"""

    @classmethod
    def _normalize_result(
        cls,
        parsed: Dict[str, Any],
        full_score: float,
        provider: str,
        model: str,
        latency_ms: int,
        markdic_list: Optional[List[str]] = None,
        sub_questions: Optional[List[Dict[str, Any]]] = None,
        rubric: str = ""
    ) -> Dict[str, Any]:
        # Extract student_answer / ocr_text
        student_answer = str(parsed.get("student_answer") or parsed.get("ocr_text") or "").strip()
        overall_comment = str(parsed.get("overall_comment") or parsed.get("comment") or "").strip()

        # Extract point_* scores and comments (mark.bdfz.net format)
        point_scores: Dict[str, float] = {}
        point_comments: Dict[str, str] = {}
        point_labels: Dict[str, str] = {p["key"]: p["label"] for p in extract_point_keys(rubric)}

        for k, v in parsed.items():
            if k.startswith("point_") and k not in ("point_scores", "point_comments"):
                try:
                    point_scores[k] = float(v)
                except Exception:
                    point_scores[k] = 0.0
                short = k.replace("point_", "", 1)
                c_val = parsed.get(f"comment_{short}") or parsed.get(f"{k}_comment") or ""
                point_comments[f"comment_{short}"] = str(c_val).strip()

        # Also support breakdown array if returned by model
        breakdown = parsed.get("breakdown")
        if isinstance(breakdown, list) and not point_scores:
            for idx, item in enumerate(breakdown):
                if isinstance(item, dict):
                    pk = f"point_{idx + 1}"
                    label = str(item.get("point") or f"得分点{idx + 1}")
                    point_labels[pk] = label
                    try:
                        point_scores[pk] = float(item.get("score", 0))
                    except Exception:
                        point_scores[pk] = 0.0
                    point_comments[f"comment_{idx + 1}"] = str(item.get("reason") or "")

        # Build unified breakdown list for UI cards
        unified_breakdown = []
        for pk, pval in point_scores.items():
            short = pk.replace("point_", "", 1)
            unified_breakdown.append({
                "key": pk,
                "point": point_labels.get(pk, pk),
                "score": pval,
                "reason": point_comments.get(f"comment_{short}", "")
            })

        # Normalize composite sub_scores if present
        norm_sub_scores = []
        if sub_questions and len(sub_questions) > 1:
            raw_subs = parsed.get("sub_scores")
            if not isinstance(raw_subs, list):
                raw_subs = []
            for idx, sq in enumerate(sub_questions):
                sq_max = float(sq.get("fullmark", 0) or 0)
                sq_dic = sq.get("markdic_list") or []
                matched = next(
                    (x for x in raw_subs if isinstance(x, dict) and str(x.get("index")) == str(sq["index"])),
                    raw_subs[idx] if idx < len(raw_subs) and isinstance(raw_subs[idx], dict) else None
                )
                raw_val = 0.0
                reason = ""
                if matched:
                    try:
                        raw_val = float(matched.get("score", 0))
                    except Exception:
                        raw_val = 0.0
                    reason = str(matched.get("reason", ""))
                elif idx < len(unified_breakdown):
                    raw_val = float(unified_breakdown[idx].get("score", 0))
                    reason = str(unified_breakdown[idx].get("reason", ""))
                snapped_sub = cls._snap_to_markdic(raw_val, sq_max, sq_dic)
                norm_sub_scores.append({
                    "index": sq["index"],
                    "name": sq["name"],
                    "score": snapped_sub,
                    "score_str": format_score_str(snapped_sub),
                    "max_score": sq_max,
                    "reason": reason
                })
            raw_total = sum(x["score"] for x in norm_sub_scores)
        else:
            raw_score = parsed.get("final_score", parsed.get("score", None))
            if raw_score is None and point_scores:
                raw_total = sum(point_scores.values())
            else:
                try:
                    raw_total = float(raw_score or 0)
                except Exception:
                    raw_total = 0.0
                if point_scores and abs(sum(point_scores.values()) - raw_total) <= 0.01:
                    raw_total = sum(point_scores.values())

        snapped_total = cls._snap_to_markdic(raw_total, full_score, markdic_list)
        is_blank = bool(parsed.get("is_blank", False)) or ("未作答" in overall_comment and snapped_total == 0)
        is_excellence = bool(parsed.get("is_excellence", False)) or (snapped_total >= full_score and full_score > 0)
        needs_arb = bool(parsed.get("needs_arbitration", False))

        flags: List[str] = []
        if is_blank:
            flags.append("空白卷")
        if snapped_total >= full_score and full_score > 0:
            flags.append("满分卷")
        elif snapped_total <= 0:
            flags.append("零分卷")
        if is_excellence:
            flags.append("值得收藏")
        if needs_arb:
            flags.append("建议仲裁")

        return {
            "score": snapped_total,
            "final_score": snapped_total,
            "score_str": format_score_str(snapped_total),
            "full_score": full_score,
            "ocr_text": student_answer,
            "student_answer": student_answer,
            "comment": overall_comment,
            "overall_comment": overall_comment,
            "point_scores": point_scores,
            "point_comments": point_comments,
            "point_labels": point_labels,
            "breakdown": unified_breakdown,
            "sub_scores": norm_sub_scores,
            "is_blank": is_blank,
            "is_excellence": is_excellence,
            "needs_arbitration": needs_arb,
            "flags": flags,
            "provider": provider,
            "model": model,
            "latency_ms": latency_ms,
        }

    @classmethod
    def grade_image(
        cls,
        image_bytes: bytes,
        rubric: str,
        full_score: float,
        provider: str,
        model: str,
        api_key: str,
        thinking: str = "medium",
        base_url: Optional[str] = None,
        markdic_list: Optional[List[str]] = None,
        sub_questions: Optional[List[Dict[str, Any]]] = None,
        mime_type: Optional[str] = None
    ) -> Dict[str, Any]:
        provider = (provider or "gemini").lower().strip()
        if provider not in cls.SUPPORTED_MODELS:
            raise ValueError(f"不支持的 AI 供应商: {provider}")

        keys = cls.parse_api_keys(api_key)
        if not keys:
            raise ValueError(f"请输入 {cls.SUPPORTED_MODELS[provider]['name']} 的 API Key")

        detected_mime = mime_type or detect_mime_type(image_bytes)
        prompt = cls._build_prompt(rubric, full_score, markdic_list=markdic_list, sub_questions=sub_questions)

        last_err = None
        for idx, k in enumerate(keys):
            start_ts = time.time()
            try:
                if provider == "gemini":
                    raw_text = cls._call_gemini(image_bytes, detected_mime, prompt, model, k, thinking, base_url)
                elif provider == "openai":
                    raw_text = cls._call_openai(image_bytes, detected_mime, prompt, model, k, thinking, base_url)
                elif provider == "claude":
                    raw_text = cls._call_claude(image_bytes, detected_mime, prompt, model, k, thinking, base_url)
                elif provider == "deepseek":
                    raw_text = cls._call_deepseek(image_bytes, detected_mime, prompt, model, k, thinking, base_url)
                else:
                    raise ValueError(f"未知的供应商: {provider}")

                latency_ms = int((time.time() - start_ts) * 1000)
                cleaned = cls._clean_json_text(raw_text)
                parsed = json.loads(cleaned)
                return cls._normalize_result(
                    parsed,
                    full_score=full_score,
                    provider=provider,
                    model=model,
                    latency_ms=latency_ms,
                    markdic_list=markdic_list,
                    sub_questions=sub_questions,
                    rubric=rubric,
                )
            except Exception as e:
                last_err = e
                logger.warning(f"AI grade attempt {idx + 1}/{len(keys)} ({provider}/{model}) failed: {e}")
                if idx + 1 < len(keys):
                    time.sleep(0.3)
                    continue
        raise RuntimeError(str(last_err))

    @classmethod
    def _call_gemini(
        cls,
        image_bytes: bytes,
        mime_type: str,
        prompt: str,
        model: str,
        api_key: str,
        thinking: str,
        base_url: Optional[str]
    ) -> str:
        import base64
        b64_img = base64.b64encode(image_bytes).decode("utf-8")
        host = (base_url or cls.SUPPORTED_MODELS["gemini"]["default_base_url"]).rstrip("/")
        url = f"{host}/models/{model}:generateContent"

        is_gen3_or_4 = model.startswith("gemini-3") or model.startswith("gemini-4")
        if is_gen3_or_4:
            image_part: Dict[str, Any] = {
                "inlineData": {"mimeType": mime_type, "data": b64_img},
                "mediaResolution": {"level": "media_resolution_high"}
            }
        else:
            image_part = {"inline_data": {"mime_type": mime_type, "data": b64_img}}

        gen_config: Dict[str, Any] = {}
        supports_thinking = any(
            m["id"] == model and m.get("supports_thinking")
            for m in cls.SUPPORTED_MODELS["gemini"]["models"]
        )
        if supports_thinking and thinking and thinking not in ("none", "disabled", "off"):
            if model.startswith("gemini-3") or model.startswith("gemini-4"):
                t_level = "low" if thinking in ("minimal", "low") else ("high" if thinking in ("high", "xhigh", "max") else "medium")
                gen_config["thinkingConfig"] = {"thinkingLevel": t_level}
            else:
                budget_map = {"minimal": 0, "low": 512, "medium": 1024, "high": 4096}
                gen_config["thinkingConfig"] = {"thinkingBudget": budget_map.get(thinking, 1024)}
        else:
            gen_config["responseMimeType"] = "application/json"

        payload = {
            "contents": [{"parts": [{"text": prompt}, image_part]}],
            "generationConfig": gen_config
        }

        resp = requests.post(
            url,
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            json=payload,
            timeout=75
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Gemini API 报错 (HTTP {resp.status_code}): {resp.text[:300]}")

        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError(f"Gemini 未返回有效候选结果: {resp.text[:250]}")

        parts = candidates[0].get("content", {}).get("parts", [])
        text_out = ""
        for p in reversed(parts):
            if not p.get("thought") and p.get("text"):
                text_out = p["text"].strip()
                break
        if not text_out:
            for p in parts:
                if p.get("text"):
                    text_out = p["text"].strip()
                    break
        if not text_out:
            raise RuntimeError("Gemini 返回内容为空")
        return text_out

    @classmethod
    def _call_deepseek(
        cls,
        image_bytes: bytes,
        mime_type: str,
        prompt: str,
        model: str,
        api_key: str,
        thinking: str,
        base_url: Optional[str]
    ) -> str:
        import base64
        b64_img = base64.b64encode(image_bytes).decode("utf-8")
        data_uri = f"data:{mime_type};base64,{b64_img}"
        host = (base_url or cls.SUPPORTED_MODELS["deepseek"]["default_base_url"]).rstrip("/")
        url = f"{host}/chat/completions" if not host.endswith("/chat/completions") else host

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        is_official_flash = model in ("deepseek-flash", "deepseek-v4-flash-vision-exp")
        user_content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_uri, "detail": "original" if is_official_flash else "high"}}
        ]

        payload: Dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": user_content}],
            "response_format": {"type": "json_object"},
        }

        if is_official_flash:
            if thinking in ("disabled", "none", "minimal", "off"):
                payload["thinking"] = {"type": "disabled"}
                payload["max_tokens"] = 8192
                payload["temperature"] = 0.1
            else:
                effort = "low" if thinking == "low" else ("max" if thinking in ("max", "xhigh") else "high")
                payload["thinking"] = {"type": "enabled"}
                payload["reasoning_effort"] = effort
                payload["max_tokens"] = 32768 if effort == "max" else (16384 if effort == "high" else 8192)
        else:
            payload["max_tokens"] = 4096
            payload["temperature"] = 0.1

        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        if resp.status_code != 200:
            raise RuntimeError(f"DeepSeek API 报错 (HTTP {resp.status_code}): {resp.text[:300]}")

        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        content = str(msg.get("content") or "").strip()
        if not content:
            raise RuntimeError("DeepSeek 未返回最终 JSON 正文")
        return content

    @classmethod
    def _call_claude(
        cls,
        image_bytes: bytes,
        mime_type: str,
        prompt: str,
        model: str,
        api_key: str,
        thinking: str,
        base_url: Optional[str]
    ) -> str:
        import base64
        b64_img = base64.b64encode(image_bytes).decode("utf-8")
        host = (base_url or cls.SUPPORTED_MODELS["claude"]["default_base_url"]).rstrip("/")
        url = f"{host}/messages" if not host.endswith("/messages") else host

        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "prompt-caching-2024-07-31"
        }

        payload: Dict[str, Any] = {
            "model": model,
            "max_tokens": 4096,
            "system": [
                {
                    "type": "text",
                    "text": prompt,
                    "cache_control": {"type": "ephemeral"}
                }
            ],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,
                                "data": b64_img
                            }
                        },
                        {
                            "type": "text",
                            "text": "请严格按系统指令对答卷图片进行 OCR 识别与判分，只输出合法 JSON。"
                        }
                    ]
                }
            ]
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=75)
        if resp.status_code != 200:
            raise RuntimeError(f"Claude API 报错 (HTTP {resp.status_code}): {resp.text[:300]}")

        data = resp.json()
        content_blocks = data.get("content") or []
        text_out = ""
        for block in content_blocks:
            if block.get("type") == "text" and block.get("text"):
                text_out += block.get("text", "")
        if not text_out.strip():
            raise RuntimeError("Claude 返回内容为空")
        return text_out.strip()

    @classmethod
    def _call_openai(
        cls,
        image_bytes: bytes,
        mime_type: str,
        prompt: str,
        model: str,
        api_key: str,
        thinking: str,
        base_url: Optional[str]
    ) -> str:
        import base64
        b64_img = base64.b64encode(image_bytes).decode("utf-8")
        data_uri = f"data:{mime_type};base64,{b64_img}"
        host = (base_url or cls.SUPPORTED_MODELS["openai"]["default_base_url"]).rstrip("/")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        # Use standard chat/completions with high-detail image_url for universal compatibility
        # across official OpenAI and custom gateways, or responses API if required.
        chat_url = f"{host}/chat/completions" if not host.endswith("/chat/completions") else host
        payload: Dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_uri, "detail": "high"}},
                        {"type": "text", "text": "请严格按系统指令评分，只输出合法 JSON。"}
                    ]
                }
            ],
            "response_format": {"type": "json_object"},
            "max_completion_tokens": 4096
        }

        if thinking and thinking not in ("none", "disabled", "off"):
            effort = "high" if thinking in ("high", "xhigh", "max") else ("low" if thinking in ("low", "minimal") else "medium")
            payload["reasoning_effort"] = effort
        else:
            payload["temperature"] = 0.1

        resp = requests.post(chat_url, headers=headers, json=payload, timeout=75)
        if resp.status_code != 200 and not base_url:
            # Fallback to /v1/responses for official OpenAI endpoints if needed
            resp_url = f"{host}/responses"
            r_payload: Dict[str, Any] = {
                "model": model,
                "instructions": prompt,
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_image", "image_url": data_uri, "detail": "high"},
                            {"type": "input_text", "text": "请严格按系统指令评分，只输出合法 JSON。"}
                        ]
                    }
                ],
                "text": {"format": {"type": "json_object"}},
                "max_output_tokens": 4096,
            }
            if thinking and thinking not in ("none", "disabled", "off"):
                r_payload["reasoning"] = {"effort": thinking if thinking != "max" else "xhigh"}
            resp2 = requests.post(resp_url, headers=headers, json=r_payload, timeout=75)
            if resp2.status_code == 200:
                j2 = resp2.json()
                if isinstance(j2.get("output_text"), str) and j2["output_text"].strip():
                    return j2["output_text"].strip()
                for item in j2.get("output") or []:
                    for part in item.get("content") or []:
                        if part.get("text"):
                            return str(part["text"]).strip()

        if resp.status_code != 200:
            raise RuntimeError(f"OpenAI API 报错 (HTTP {resp.status_code}): {resp.text[:300]}")

        data = resp.json()
        return data["choices"][0]["message"]["content"]

    @classmethod
    def generate_rubric_with_ai(
        cls,
        question: str,
        ref_answer: str,
        full_score: float,
        provider: str,
        model: str,
        api_key: str,
        base_url: Optional[str] = None
    ) -> str:
        """Generate structured point_* rubric lines using user's AI key (like mark.bdfz.net #btnGenerateRubric)."""
        keys = cls.parse_api_keys(api_key)
        if not keys:
            raise ValueError("请先填写 API Key")
        k = keys[0]
        prompt = f"""你是一名资深中学阅卷组长。请根据以下题目和参考答案，制定清晰、可操作的逐点评分细则（满分 {full_score:g} 分）。

【题目】
{question or '（见参考答案）'}

【参考答案】
{ref_answer}

请直接输出评分标准文本，每行一个采分点，严格采用如下格式（不要输出任何其他解释或代码块）：
point_1 | 采分点1名称（X分） | 详细给分与扣分依据
point_2 | 采分点2名称（Y分） | 详细给分与扣分依据
...
确保所有采分点分值之和等于 {full_score:g} 分。"""

        return cls._call_text_only(prompt, provider, model, k, base_url).strip()

    @classmethod
    def generate_summary_report(
        cls,
        records: List[Dict[str, Any]],
        que_name: str,
        full_score: float,
        provider: str,
        model: str,
        api_key: str,
        base_url: Optional[str] = None,
        source_progress: Optional[Dict[str, Any]] = None
    ) -> str:
        if not records:
            return "暂无已批阅的答卷记录，请先进行试评或正式评阅后再生成教学诊断报告。"

        keys = cls.parse_api_keys(api_key)
        if not keys:
            raise ValueError("请先输入 API Key")
        k = keys[0]

        scores = [float(r.get("score", 0)) for r in records]
        avg_score = sum(scores) / len(scores)
        max_s = max(scores)
        min_s = min(scores)
        full_cnt = sum(1 for s in scores if s >= full_score and full_score > 0)
        zero_cnt = sum(1 for s in scores if s <= 0)

        samples = []
        for idx, r in enumerate(records[:45]):
            samples.append(
                f"样本#{idx + 1} (得分:{r.get('score')}/{full_score:g}): "
                f"识别作答=\"{str(r.get('ocr_text', ''))[:120]}\" | 评语=\"{str(r.get('comment', ''))[:100]}\""
            )

        src_info = ""
        if source_progress:
            src_info = (
                f"- 源站同题总任务量：{source_progress.get('taskcount', '-')}\n"
                f"- 源站同题已完成：{source_progress.get('wanchengtotal', '-')} ({source_progress.get('reat', 0)}%)\n"
                f"- 源站全组均分：{source_progress.get('avg', '-')}\n"
            )

        prompt = f"""你是一位资深教研员与阅卷质量分析专家。请根据以下刚刚完成的阅卷统计与去标识化样本，撰写一份结构清晰、专业的《AI 阅卷质量与学情教学诊断报告》（使用 Markdown 格式）：

【统计概览】
- 题目名称：{que_name}
- 满分：{full_score:g} 分
- 本次分析样本数：{len(records)} 份
- 平均分：{avg_score:.2f} 分（得分率 {(avg_score / full_score * 100) if full_score > 0 else 0:.1f}%）
- 最高分：{max_s:g} 分 | 最低分：{min_s:g} 分
- 满分卷：{full_cnt} 份 ({full_cnt / len(records) * 100:.1f}%) | 零分卷：{zero_cnt} 份 ({zero_cnt / len(records) * 100:.1f}%)
{src_info}
【学生作答与判分样本】
{chr(10).join(samples)}

请包含以下章节：
1. **📊 整体得分表现与分数段分布特征**
2. **🔍 典型失分原因与高频知识盲区诊断**（结合具体作答表现归纳）
3. **🌟 优秀作答亮点与高分共性特征**
4. **💡 讲评课教学改进建议与针对性突破策略**"""

        return cls._call_text_only(prompt, provider, model, k, base_url)

    @classmethod
    def _call_text_only(
        cls,
        prompt: str,
        provider: str,
        model: str,
        api_key: str,
        base_url: Optional[str] = None
    ) -> str:
        provider = (provider or "gemini").lower().strip()
        if provider == "gemini":
            host = (base_url or cls.SUPPORTED_MODELS["gemini"]["default_base_url"]).rstrip("/")
            url = f"{host}/models/{model}:generateContent"
            resp = requests.post(
                url,
                headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=75
            )
            if resp.status_code != 200:
                raise RuntimeError(f"Gemini 报错: {resp.text[:250]}")
            parts = resp.json()["candidates"][0]["content"]["parts"]
            for p in reversed(parts):
                if not p.get("thought") and p.get("text"):
                    return p["text"]
            return parts[0].get("text", "")

        elif provider == "claude":
            host = (base_url or cls.SUPPORTED_MODELS["claude"]["default_base_url"]).rstrip("/")
            url = f"{host}/messages" if not host.endswith("/messages") else host
            resp = requests.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01"
                },
                json={"model": model, "max_tokens": 4096, "messages": [{"role": "user", "content": prompt}]},
                timeout=75
            )
            if resp.status_code != 200:
                raise RuntimeError(f"Claude 报错: {resp.text[:250]}")
            return resp.json()["content"][0]["text"]

        else:
            default_host = cls.SUPPORTED_MODELS.get(provider, cls.SUPPORTED_MODELS["openai"])["default_base_url"]
            host = (base_url or default_host).rstrip("/")
            url = f"{host}/chat/completions" if not host.endswith("/chat/completions") else host
            resp = requests.post(
                url,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
                json={"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 4096},
                timeout=75
            )
            if resp.status_code != 200:
                raise RuntimeError(f"{provider} 报错: {resp.text[:250]}")
            return resp.json()["choices"][0]["message"]["content"]
