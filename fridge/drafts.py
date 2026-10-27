"""Validate model-authored recipe structure and stock constraints, not culinary safety."""
import hashlib

from .planner import ALIASES, DinnerRequest
from .recipe_schema import Ingredient, RecipeDraft

STAPLES = {"食用油", "盐", "糖", "生抽", "老抽", "醋", "料酒", "淀粉", "胡椒粉", "水", "香油"}
MEAT_WORDS = ("肉", "鸡胸", "鸡腿", "鸡翅", "排骨", "五花", "鱼", "虾", "蟹", "蛤", "贝", "鱿", "肠", "培根", "火腿")


def validate_draft(payload: dict, request: DinnerRequest) -> dict:
    draft = RecipeDraft.model_validate(payload)
    items = [dict(i.model_dump(), name=ALIASES.get(i.name, i.name)) for i in draft.ingredients]
    names = [i["name"] for i in items]
    if len(names) != len(set(names)):
        raise ValueError("同一食材请合并用量，不要重复列出。")
    if not set(names) <= set(request.ingredients):
        raise ValueError("菜谱的主要食材必须全部来自用户现有食材，并使用完全相同的名称。")
    if not set(draft.staples) <= STAPLES:
        raise ValueError("基础调味只能使用：" + "、".join(sorted(STAPLES)))
    if any(any(word in name for word in MEAT_WORDS) for name in names) and draft.vegetarian:
        raise ValueError("荤食不能标记为素食。")
    if request.vegetarian and not draft.vegetarian:
        raise ValueError("用户选择了不吃肉，请只使用适合该条件的食材。")
    rid = "gen-" + hashlib.sha256(draft.name.encode("utf-8")).hexdigest()[:16]
    if rid in request.exclude_ids or draft.name in request.exclude_names:
        raise ValueError("这道菜已被排除，请换一种做法，不要通过改名重复推荐。")
    if draft.minutes > request.minutes:
        raise ValueError("单菜预计时间已经超过本次限制。")
    return dict(draft.model_dump(), id=rid, ingredients=items, servings=request.people,
                emoji="🍳", source="AI 根据现有食材拟定；未联网核实，时间与用量为估算，请按实际情况调整。")
