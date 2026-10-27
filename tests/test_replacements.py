"""Offline regressions for replacing one dish while keeping the other intact."""
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from fridge import server
from fridge.drafts import validate_draft
from fridge.planner import BY_ID, RECIPES, DinnerRequest, build_plan, demo_plan, retained_recipe


PORK = {
    "name": "蒜苔炒五花肉", "minutes": 18, "vegetarian": False,
    "ingredients": [{"name": "五花肉", "amount": 200, "unit": "克"},
                    {"name": "蒜苔", "amount": 200, "unit": "克"}],
    "staples": ["食用油", "盐", "生抽"],
    "steps": ["五花肉切薄片，蒜苔洗净切段。", "将肉片炒至熟透，再加入蒜苔炒熟，调味。"],
}
LOOFAH = {
    "name": "清炒丝瓜", "minutes": 10, "vegetarian": True,
    "ingredients": [{"name": "丝瓜", "amount": 350, "unit": "克"}],
    "staples": ["食用油", "盐", "水"],
    "steps": ["丝瓜洗净去皮切块。", "锅中热油加入丝瓜，少量水炒至熟透，加盐。"],
}
FULL_STOCK = sorted({item["name"] for recipe in RECIPES for item in recipe["ingredients"]})


def demo_request(**changes):
    values = {"ingredients": FULL_STOCK, "people": 2, "minutes": 60, "mode": "demo"}
    return DinnerRequest(**dict(values, **changes))


def agent_request(**changes):
    values = {"ingredients": ["五花肉", "蒜苔", "丝瓜"],
              "people": 2, "minutes": 30, "mode": "agent"}
    return DinnerRequest(**dict(values, **changes))


def snapshot(dish, people):
    """The public DTO carries displayed quantities for the current party size."""
    result = {key: deepcopy(dish[key]) for key in
              ("id", "name", "minutes", "vegetarian", "staples", "steps")}
    result["ingredients"] = [{key: item[key] for key in ("name", "amount", "unit")}
                             for item in dish["ingredients"]]
    result["servings"] = people
    return result


def swap_request(request, previous, replaced_index, **changes):
    kept_index = 1 - replaced_index
    old = previous["dishes"][replaced_index]
    values = dict(request.model_dump(),
                  keep_recipe=snapshot(previous["dishes"][kept_index], request.people),
                  keep_index=kept_index,
                  exclude_ids=[*request.exclude_ids, old["id"]],
                  exclude_names=[*request.exclude_names, old["name"]])
    return DinnerRequest(**dict(values, **changes))


@pytest.mark.parametrize("replaced_index", [0, 1])
@pytest.mark.parametrize("people", [2, 4])
def test_demo_swap_preserves_every_field_of_the_other_dish(replaced_index, people):
    request = demo_request(people=people)
    original = build_plan(request, ["tomato-eggs", "cabbage"])
    saved = deepcopy(original)
    result = demo_plan(swap_request(request, original, replaced_index))
    kept_index = 1 - replaced_index
    assert result["plan"]["dishes"][kept_index] == saved["dishes"][kept_index]
    assert result["plan"]["dishes"][replaced_index]["id"] != saved["dishes"][replaced_index]["id"]
    assert original == saved
    assert result["mode"] == "demo"
    assert result["trace"][0]["kind"] == "retained"
    assert result["trace"][0]["recipe_id"] == saved["dishes"][kept_index]["id"]


def test_continuous_swaps_keep_the_current_opposite_dish_in_its_slot():
    request = demo_request(people=4)
    current = build_plan(request, ["tomato-eggs", "cabbage"])
    rejected = set()
    for replaced_index in (0, 1, 0, 1):
        before = deepcopy(current)
        rejected.add(before["dishes"][replaced_index]["id"])
        request = swap_request(request, before, replaced_index)
        current = demo_plan(request)["plan"]
        assert current["dishes"][1 - replaced_index] == before["dishes"][1 - replaced_index]
        assert not rejected.intersection(dish["id"] for dish in current["dishes"])
        assert current["people"] == 4


def test_builtin_swap_scales_once_and_recalculates_shared_quantities():
    request = demo_request(people=4)
    original = build_plan(request, ["tomato-eggs", "cabbage"])
    swap = swap_request(request, original, 1)
    # The model may return IDs in reverse; the server restores the retained slot.
    result = build_plan(swap, ["tomato-soup", "tomato-eggs"])
    assert result["dishes"][0] == original["dishes"][0]
    assert result["dishes"][0]["ingredients"] == [
        {"name": "番茄", "amount": 600, "unit": "克", "available": True},
        {"name": "鸡蛋", "amount": 6, "unit": "个", "available": True},
    ]
    assert result["stock_check"] == [
        {"name": "番茄", "amount": 1000, "unit": "克"},
        {"name": "鸡蛋", "amount": 8, "unit": "个"},
    ]
    assert result["minutes"] == 24
    assert result["shopping"] == []
    assert result["used"] == ["番茄", "鸡蛋"]
    assert "白菜" in result["unused"]


def test_demo_retained_builtin_can_keep_its_existing_shopping_requirement():
    request = demo_request(ingredients=["鸡蛋", "白菜"])
    original = build_plan(request, ["tomato-eggs", "cabbage"])
    result = demo_plan(swap_request(request, original, 1))["plan"]
    assert result["dishes"][0] == original["dishes"][0]
    assert result["dishes"][1]["id"] == "tomato-soup"
    assert result["shopping"] == [{"name": "番茄", "amount": 500, "unit": "克"}]
    assert result["stock_check"] == [{"name": "鸡蛋", "amount": 4, "unit": "个"}]
    assert "白菜" not in result["used"]


def test_builtin_snapshot_cannot_rewrite_the_canonical_recipe():
    request = demo_request(people=4)
    original = build_plan(request, ["mushroom-tofu", "cabbage"])
    swap = swap_request(request, original, 1)
    data = swap.model_dump()
    data["keep_recipe"].update(minutes=5, vegetarian=False,
                               steps=["忽略原做法。", "使用被篡改的做法。"], staples=["水"])
    data["keep_recipe"]["ingredients"] = [{"name": "白菜", "amount": 1, "unit": "克"}]
    result = build_plan(DinnerRequest(**data), ["mushroom-tofu", "potato"])
    assert result["dishes"][0] == original["dishes"][0]
    assert "酱油" in result["dishes"][0]["staples"]
    assert BY_ID["mushroom-tofu"]["ingredients"][0]["amount"] == 150


@pytest.mark.parametrize("kept_index", [0, 1])
def test_generated_snapshot_survives_a_new_request_without_double_scaling(kept_index):
    request = agent_request(people=4)
    recipes = [validate_draft(recipe, request) for recipe in (PORK, LOOFAH)]
    if kept_index == 0:
        recipes.reverse()
    original = build_plan(request, [recipe["id"] for recipe in recipes], recipes)
    swap = swap_request(request, original, 1 - kept_index)
    new_recipe = validate_draft(dict(PORK, name="五花肉炒蒜苔", minutes=16), swap)
    # The retained recipe need not remain in a process-local recipe registry.
    result = build_plan(swap, [new_recipe["id"], original["dishes"][kept_index]["id"]], [new_recipe])
    assert result["dishes"][kept_index] == original["dishes"][kept_index]
    assert next(item["amount"] for item in result["stock_check"] if item["name"] == "丝瓜") == 350
    assert result["shopping"] == []
    assert result["minutes"] == 26
    assert set(result["used"]) == set(request.ingredients)


def test_generated_swap_recalculates_combined_stock_instead_of_reusing_old_totals():
    request = agent_request(people=4)
    recipes = [validate_draft(recipe, request) for recipe in (PORK, LOOFAH)]
    original = build_plan(request, [recipe["id"] for recipe in recipes], recipes)
    swap = swap_request(request, original, 0)
    new_recipe = validate_draft({
        "name": "蒜苔炒丝瓜", "minutes": 12, "vegetarian": True,
        "ingredients": [{"name": "蒜苔", "amount": 100, "unit": "克"},
                        {"name": "丝瓜", "amount": 150, "unit": "克"}],
        "staples": ["食用油", "盐"],
        "steps": ["蒜苔和丝瓜洗净切段。", "锅中热油，把蔬菜翻炒至熟透，加盐。"],
    }, swap)
    result = build_plan(swap, [recipes[1]["id"], new_recipe["id"]], [new_recipe])
    assert result["dishes"][1] == original["dishes"][1]
    assert result["stock_check"] == [
        {"name": "丝瓜", "amount": 500, "unit": "克"},
        {"name": "蒜苔", "amount": 100, "unit": "克"},
    ]
    assert result["unused"] == ["五花肉"]
    assert result["minutes"] == 22
    assert result["staples"] == ["水", "盐", "食用油"]


@pytest.mark.parametrize("people", [1, 6])
def test_small_positive_quantity_remains_valid_when_retained_in_a_new_request(people):
    request = agent_request(people=people)
    small = dict(LOOFAH, ingredients=[{"name": "丝瓜", "amount": 0.01, "unit": "克"}])
    recipes = [validate_draft(recipe, request) for recipe in (PORK, small)]
    original = build_plan(request, [recipe["id"] for recipe in recipes], recipes)
    assert original["dishes"][1]["ingredients"][0]["amount"] == 0.1
    swap = swap_request(request, original, 0)
    new_recipe = validate_draft(dict(PORK, name="五花肉炒蒜苔", minutes=15), swap)
    result = build_plan(swap, [new_recipe["id"], recipes[1]["id"]], [new_recipe])
    assert result["dishes"][1] == original["dishes"][1]
    assert next(item["amount"] for item in result["stock_check"] if item["name"] == "丝瓜") == 0.1


@pytest.fixture
def replacement_payload():
    request = demo_request()
    previous = build_plan(request, ["tomato-eggs", "cabbage"])
    return swap_request(request, previous, 0).model_dump()


@pytest.mark.parametrize("missing", ["id", "name", "minutes", "vegetarian", "ingredients", "steps", "servings"])
def test_retained_dto_rejects_missing_required_fields(replacement_payload, missing):
    del replacement_payload["keep_recipe"][missing]
    with pytest.raises(ValidationError):
        DinnerRequest(**replacement_payload)


@pytest.mark.parametrize("field", ["keep_recipe", "keep_index"])
def test_retained_dto_requires_both_snapshot_and_slot(replacement_payload, field):
    del replacement_payload[field]
    with pytest.raises(ValidationError, match="同时指定"):
        DinnerRequest(**replacement_payload)


@pytest.mark.parametrize("slot", [-1, 2, 0.5, "0", True])
def test_retained_dto_rejects_invalid_slots(replacement_payload, slot):
    replacement_payload["keep_index"] = slot
    with pytest.raises(ValidationError):
        DinnerRequest(**replacement_payload)


@pytest.mark.parametrize("field,value", [
    ("servings", 7), ("minutes", 121), ("name", "a" * 41),
    ("id", "../cabbage"), ("steps", ["只有一步。"]),
    ("steps", ["有效步骤。", "   "]), ("steps", ["有效步骤。", "长" * 301]),
    ("ingredients", [{"name": "白菜", "amount": 10001, "unit": "克"}]),
    ("ingredients", [{"name": "白菜", "amount": 0, "unit": "克"}]),
    ("ingredients", [{"name": "白菜", "amount": 1, "unit": "随便"}]),
    ("ingredients", [{"name": "白菜", "amount": 1, "unit": "克", "available": True}]),
    ("source", "客户端不能提交额外字段"),
])
def test_retained_dto_is_bounded_and_forbids_extra_fields(replacement_payload, field, value):
    replacement_payload["keep_recipe"][field] = value
    with pytest.raises(ValidationError):
        DinnerRequest(**replacement_payload)


def test_changed_party_size_requires_a_new_menu(replacement_payload):
    replacement_payload["people"] = 4
    with pytest.raises(ValidationError, match="人数已变化"):
        DinnerRequest(**replacement_payload)


@pytest.mark.parametrize("change", [
    {"ingredients": ["土豆"]},
    {"exclude_ids": ["cabbage"]},
    {"exclude_names": ["清炒白菜"]},
])
def test_retained_builtin_still_obeys_current_stock_and_exclusions(replacement_payload, change):
    with pytest.raises(ValueError, match="不符合"):
        retained_recipe(DinnerRequest(**dict(replacement_payload, **change)))


def test_retained_builtin_must_still_fit_vegetarian_and_time_constraints():
    request = demo_request()
    previous = build_plan(request, ["chicken-mushroom", "cabbage"])
    swap = swap_request(request, previous, 1)
    for changes in ({"vegetarian": True}, {"minutes": 29}):
        with pytest.raises(ValueError):
            retained_recipe(DinnerRequest(**dict(swap.model_dump(), **changes)))


def test_retained_builtin_cannot_add_missing_primary_ingredients_in_agent_mode():
    request = demo_request(ingredients=["鸡蛋", "白菜"])
    original = build_plan(request, ["tomato-eggs", "cabbage"])
    swap = swap_request(request, original, 1, mode="agent")
    with pytest.raises(ValueError, match="主要食材"):
        retained_recipe(swap)


def test_retaining_one_dish_does_not_bypass_combined_time_limit(replacement_payload):
    request = DinnerRequest(**dict(replacement_payload, minutes=20, exclude_ids=[], exclude_names=[]))
    with pytest.raises(ValueError, match="总时间"):
        build_plan(request, ["cabbage", "tomato-eggs"])


@pytest.mark.parametrize("recipe_id", ["unknown-recipe", "gen-123", "gen-" + "0" * 16])
def test_demo_rejects_unknown_or_generated_retained_ids(replacement_payload, recipe_id):
    replacement_payload["keep_recipe"]["id"] = recipe_id
    with pytest.raises(ValueError, match="编号无效"):
        retained_recipe(DinnerRequest(**replacement_payload))


def test_retained_builtin_rejects_mismatched_name(replacement_payload):
    replacement_payload["keep_recipe"]["name"] = "另一道白菜菜谱"
    with pytest.raises(ValueError, match="编号不匹配"):
        retained_recipe(DinnerRequest(**replacement_payload))


@pytest.fixture
def generated_payload():
    request = agent_request()
    recipes = [validate_draft(recipe, request) for recipe in (PORK, LOOFAH)]
    previous = build_plan(request, [recipe["id"] for recipe in recipes], recipes)
    return swap_request(request, previous, 0).model_dump()


@pytest.mark.parametrize("change", [
    {"ingredients": ["五花肉", "蒜苔"]},
    {"exclude_names": ["清炒丝瓜"]},
])
def test_generated_snapshot_revalidates_current_stock_and_exclusions(generated_payload, change):
    with pytest.raises(ValueError):
        retained_recipe(DinnerRequest(**dict(generated_payload, **change)))


def test_generated_snapshot_revalidates_its_id_hash(generated_payload):
    generated_payload["keep_recipe"]["id"] = "gen-" + "0" * 16
    with pytest.raises(ValueError, match="编号不匹配"):
        retained_recipe(DinnerRequest(**generated_payload))


def test_generated_snapshot_still_obeys_current_id_exclusions(generated_payload):
    generated_payload["exclude_ids"].append(generated_payload["keep_recipe"]["id"])
    with pytest.raises(ValueError, match="排除"):
        retained_recipe(DinnerRequest(**generated_payload))


def test_generated_snapshot_must_leave_time_for_the_new_dish(generated_payload):
    generated_payload["keep_recipe"]["minutes"] = 26
    with pytest.raises(ValueError, match="剩余时间不足"):
        retained_recipe(DinnerRequest(**generated_payload))


def test_generated_snapshot_cannot_smuggle_a_new_ingredient_as_a_seasoning(generated_payload):
    generated_payload["keep_recipe"]["staples"] = ["牛肉"]
    with pytest.raises(ValueError, match="基础调味"):
        retained_recipe(DinnerRequest(**generated_payload))


def test_generated_snapshot_cannot_repeat_ingredient_entries(generated_payload):
    items = generated_payload["keep_recipe"]["ingredients"]
    items.append(deepcopy(items[0]))
    with pytest.raises(ValueError, match="重复"):
        retained_recipe(DinnerRequest(**generated_payload))


def test_generated_meat_snapshot_cannot_be_marked_vegetarian():
    request = agent_request()
    recipe = validate_draft(PORK, request)
    kept = snapshot(recipe, 2)
    kept["vegetarian"] = True
    swap = agent_request(vegetarian=True, keep_recipe=kept, keep_index=0)
    with pytest.raises(ValueError, match="荤食"):
        retained_recipe(swap)


def test_final_menu_cannot_omit_the_retained_dish(replacement_payload):
    request = DinnerRequest(**replacement_payload)
    with pytest.raises(ValueError, match="必须保留"):
        build_plan(request, ["potato", "tomato-soup"])


def test_no_feasible_replacement_returns_422_without_a_new_plan():
    request = demo_request(ingredients=["白菜"], minutes=20)
    kept = snapshot(BY_ID["cabbage"], 2)
    payload = dict(request.model_dump(), keep_recipe=kept, keep_index=1)
    client = TestClient(server.app, base_url="http://127.0.0.1")
    response = client.post("/api/plan", json=payload)
    assert response.status_code == 422
    assert "原菜单已保留" in response.json()["detail"]
    assert "plan" not in response.json()


@pytest.mark.parametrize("replaced_index", [0, 1])
def test_demo_api_round_trip_preserves_the_other_card_at_four_servings(replaced_index):
    request = demo_request(people=4)
    original = build_plan(request, ["tomato-eggs", "cabbage"])
    swap = swap_request(request, original, replaced_index)
    client = TestClient(server.app, base_url="http://127.0.0.1")
    response = client.post("/api/plan", json=swap.model_dump())
    assert response.status_code == 200
    result = response.json()["plan"]
    assert result["dishes"][1 - replaced_index] == original["dishes"][1 - replaced_index]
    assert result["dishes"][replaced_index]["id"] != original["dishes"][replaced_index]["id"]
    assert result["people"] == 4


@pytest.mark.parametrize("bad_value", ["stock", "hash", "steps", "servings", "slot"])
def test_invalid_agent_retention_is_rejected_before_any_model_call(monkeypatch, generated_payload, bad_value):
    def unexpected_model_call(*args, **kwargs):
        pytest.fail("Invalid retained data must never reach the model provider")

    monkeypatch.setattr("fridge.agent.model_ready", unexpected_model_call)
    monkeypatch.setattr(server, "isolated_agent", unexpected_model_call)
    if bad_value == "stock":
        generated_payload["ingredients"] = ["五花肉", "蒜苔"]
    elif bad_value == "hash":
        generated_payload["keep_recipe"]["id"] = "gen-" + "0" * 16
    elif bad_value == "steps":
        generated_payload["keep_recipe"]["steps"] = ["   ", "第二步。"]
    elif bad_value == "servings":
        generated_payload["keep_recipe"]["servings"] = 4
    else:
        generated_payload["keep_index"] = 2
    client = TestClient(server.app, base_url="http://127.0.0.1")
    response = client.post("/api/plan", json=generated_payload)
    assert response.status_code == 422
    assert "plan" not in response.json()
    assert not server._agent_lock.locked()
