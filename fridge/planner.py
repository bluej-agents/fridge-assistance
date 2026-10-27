"""Deterministic validation and quantities shared by demo and agent tools."""
import json
import math
import re
from copy import deepcopy
from itertools import combinations
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .recipe_schema import RetainedRecipe

RECIPES = json.loads(Path(__file__).with_name("recipes.json").read_text(encoding="utf-8"))
BY_ID = {r["id"]: r for r in RECIPES}
ALIASES = {"西红柿": "番茄", "包菜": "卷心菜", "蒜": "大蒜"}


class DinnerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ingredients: list[str] = Field(min_length=1, max_length=40)
    people: int = Field(default=2, ge=1, le=6)
    minutes: int = Field(default=30, ge=15, le=120)
    vegetarian: bool = False
    exclude_ids: list[str] = Field(default_factory=list, max_length=20)
    exclude_names: list[str] = Field(default_factory=list, max_length=20)
    mode: Literal["demo", "agent"] = "demo"
    keep_recipe: RetainedRecipe | None = None
    keep_index: int | None = Field(default=None, ge=0, le=1, strict=True)

    @model_validator(mode="after")
    def check_retained_fields(self):
        if (self.keep_recipe is None) != (self.keep_index is None):
            raise ValueError("换菜时须同时指定保留的菜谱及其位置。")
        if self.keep_recipe is not None and self.keep_recipe.servings != self.people:
            raise ValueError("用餐人数已变化，请重新安排菜单后再换菜。")
        return self

    @field_validator("ingredients")
    @classmethod
    def normalize(cls, values):
        result = []
        for value in values:
            value = value.strip()
            if not value or len(value) > 24:
                raise ValueError("请填写简短的食材名称，每项不超过 24 字。")
            value = ALIASES.get(value, value)
            if value not in result:
                result.append(value)
        return result

    @field_validator("exclude_ids")
    @classmethod
    def validate_exclusions(cls, values):
        if any(value not in BY_ID and not re.fullmatch(r"gen-[0-9a-f]{16}", value) for value in values):
            raise ValueError("换菜列表包含未知菜谱。")
        return list(dict.fromkeys(values))

    @field_validator("exclude_names")
    @classmethod
    def validate_names(cls, values):
        if any(not value.strip() or len(value) > 40 for value in values):
            raise ValueError("换菜名称不合适。")
        return list(dict.fromkeys(value.strip() for value in values))


def candidates(request: DinnerRequest, recipes=None) -> list[dict]:
    available = set(request.ingredients)
    return [dict(r, matched=[x["name"] for x in r["ingredients"] if x["name"] in available])
            for r in (RECIPES if recipes is None else recipes) if r["id"] not in request.exclude_ids
            and r["name"] not in request.exclude_names
            and any(x["name"] in available for x in r["ingredients"])
            and (not request.vegetarian or r["vegetarian"])
            and r["minutes"] <= request.minutes]


def retained_recipe(request: DinnerRequest) -> dict | None:
    """Revalidate a bounded snapshot; it is client data, not an authenticated history."""
    snapshot = request.keep_recipe
    if snapshot is None:
        return None
    if snapshot.id in BY_ID:
        # Built-in recipes use canonical data, including their original portions
        # and seasonings; never substitute client-provided edits for that source.
        recipe = deepcopy(BY_ID[snapshot.id])
        if snapshot.name != recipe["name"]:
            raise ValueError("保留菜谱与编号不匹配，请重新安排菜单。")
    else:
        if request.mode != "agent" or not re.fullmatch(r"gen-[0-9a-f]{16}", snapshot.id):
            raise ValueError("保留菜谱编号无效，请重新安排菜单。")
        from .drafts import validate_draft
        recipe = validate_draft(snapshot.model_dump(exclude={"id", "servings"}), request)
        if recipe["id"] != snapshot.id:
            raise ValueError("保留菜谱与编号不匹配，请重新安排菜单。")
    if not candidates(request, [recipe]):
        raise ValueError("保留的菜不符合当前食材、饮食或换菜条件，请重新安排菜单。")
    if request.mode == "agent" and any(i["name"] not in request.ingredients for i in recipe["ingredients"]):
        raise ValueError("保留菜谱的主要食材已不在冰箱中，请重新安排菜单。")
    if recipe["minutes"] + 5 > request.minutes:
        raise ValueError("保留这道菜后剩余时间不足，请增加时间或重新安排菜单。")
    return recipe


def build_plan(request: DinnerRequest, recipe_ids: list[str], recipes=None) -> dict:
    if len(recipe_ids) != 2 or len(set(recipe_ids)) != 2:
        raise ValueError("请选两道不同的菜。")
    book = dict(BY_ID) if recipes is None else {r["id"]: r for r in recipes}
    kept = retained_recipe(request)
    if kept is not None:
        if kept["id"] not in recipe_ids:
            raise ValueError("换菜时必须保留另一道菜，不能重新生成整份菜单。")
        # The server restores the retained recipe and slot even if model IDs are reversed.
        recipe_ids = [rid for rid in recipe_ids if rid != kept["id"]]
        recipe_ids.insert(request.keep_index, kept["id"])
        book[kept["id"]] = kept
    eligible = {r["id"] for r in candidates(request, list(book.values()))}
    if not set(recipe_ids) <= eligible:
        raise ValueError("菜谱不符合当前限制或已被排除。")
    if len({book[rid]["name"] for rid in recipe_ids}) != 2:
        raise ValueError("请选两道不同的菜。")
    total = sum(book[r]["minutes"] for r in recipe_ids)
    if total > request.minutes:
        raise ValueError("按顺序烹饪的预计总时间超过限制。")
    available = set(request.ingredients)
    dishes, totals, staples = [], {}, set()
    for rid in recipe_ids:
        recipe = book[rid]
        items = []
        for item in recipe["ingredients"]:
            amount = item["amount"] * request.people / recipe["servings"]
            amount = math.ceil(amount) if item["unit"] in ("个", "瓣") else max(0.1, round(amount, 1))
            entry = dict(item, amount=amount, available=item["name"] in available)
            items.append(entry)
            key = (item["name"], item["unit"])
            totals[key] = totals.get(key, 0) + amount
        dishes.append(dict(deepcopy(recipe), ingredients=items))
        staples.update(recipe["staples"])
    used = sorted({name for name, _ in totals} & available)
    if not used:
        raise ValueError("这组菜没有用到现有食材，请补充其他食材或调整限制。")
    if request.mode == "agent" and any(name not in available for name, _ in totals):
        raise ValueError("请围绕现有食材安排，两道菜均不能要求新增主要食材；基础调味另列。")
    shopping, stock_check = [], []
    for (name, unit), amount in sorted(totals.items()):
        item = {"name": name, "amount": amount, "unit": unit}
        (stock_check if name in available else shopping).append(item)
    return {
        "dishes": dishes, "people": request.people, "minutes": total,
        "shopping": shopping, "stock_check": stock_check,
        "staples": sorted(staples), "used": used,
        "unused": sorted(available - set(used)),
        "note": "已有食材仅按名称匹配，数量请对照核实。时间为顺序烹饪估算，用餐主食另行准备。",
    }


def demo_plan(request: DinnerRequest) -> dict:
    options = []
    kept = retained_recipe(request)
    pairs = ([kept, r] for r in candidates(request) if r["id"] != kept["id"]) if kept else combinations(candidates(request), 2)
    for pair in pairs:
        try:
            plan = build_plan(request, [r["id"] for r in pair])
        except ValueError:
            continue
        # Minimize new ingredient types, then maximize existing ingredient coverage.
        score = (len(plan["shopping"]), -len(plan["used"]), plan["minutes"], tuple(r["id"] for r in pair))
        options.append((score, plan))
    if not options:
        if kept:
            raise ValueError("暂时没有能与保留菜搭配的替代菜，原菜单已保留。可换另一道菜或调整条件后重新安排。")
        raise ValueError("内置菜谱中暂时没有符合条件的两道菜。试试增加可用时间、补充食材或重置换菜。")
    plan = min(options, key=lambda item: item[0])[1]
    trace = ([{"kind": "retained", "recipe_id": kept["id"], "title": "保留另一道菜",
               "detail": "保留原菜谱及其位置，只替换所选的另一道菜。"}] if kept else [])
    return {"mode": "demo", "plan": plan, "trace": trace + [
        {"kind": "demo", "title": "本地示例规则（未调用大模型）",
         "detail": f"比较了 {len(options)} 组可行搭配，优先减少补购种类，再尽量使用现有食材。"},
        {"kind": "validation", "title": "用量与条件检查", "detail": plan["note"]}
    ]}
