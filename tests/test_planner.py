import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from fridge.planner import DinnerRequest, build_plan, demo_plan


def example(**changes):
    data = json.loads(Path("examples/dinner.json").read_text(encoding="utf-8"))
    data.update(changes)
    return DinnerRequest(**data)


def test_example_uses_stock_without_new_ingredients():
    result = demo_plan(example())
    assert result["mode"] == "demo"
    assert result["plan"]["shopping"] == []
    assert result["plan"]["minutes"] <= 30
    assert set(result["plan"]["used"]) == {"鸡蛋", "番茄", "白菜"}


def test_quantities_aggregate_and_round_indivisible_foods():
    plan = build_plan(example(people=3), ["tomato-eggs", "tomato-soup"])
    amounts = {i["name"]: i["amount"] for i in plan["stock_check"]}
    assert amounts == {"番茄": 750, "鸡蛋": 7}


def test_missing_food_is_aggregated_across_dishes():
    plan = build_plan(example(ingredients=["鸡蛋"]), ["tomato-eggs", "tomato-soup"])
    assert plan["shopping"] == [{"name": "番茄", "amount": 500, "unit": "克"}]


def test_swap_removes_excluded_dish_and_revalidates():
    first = demo_plan(example())["plan"]
    excluded = first["dishes"][0]["id"]
    changed = demo_plan(example(exclude_ids=[excluded]))["plan"]
    assert excluded not in {r["id"] for r in changed["dishes"]}
    assert changed["minutes"] <= 30


@pytest.mark.parametrize("ids", [["tomato-eggs", "tomato-eggs"], ["invented", "cabbage"], ["chicken-mushroom", "cabbage"]])
def test_invalid_or_disallowed_recipes_are_rejected(ids):
    with pytest.raises(ValueError):
        build_plan(example(), ids)


def test_time_limit_and_unmatched_food_do_not_return_fictional_success():
    with pytest.raises(ValueError):
        demo_plan(example(minutes=15))
    with pytest.raises(ValueError):
        demo_plan(example(ingredients=["苹果"]))


def test_aliases_deduplicate_without_guessing_quantities():
    assert example(ingredients=["西红柿", "番茄", " 鸡蛋 "]).ingredients == ["番茄", "鸡蛋"]


@pytest.mark.parametrize("patch", [{"people": 0}, {"people": 7}, {"ingredients": []}, {"ingredients": [" "]}, {"mode": "fake"}, {"exclude_ids": ["invented"]}])
def test_bad_input(patch):
    with pytest.raises(ValidationError):
        example(**patch)
