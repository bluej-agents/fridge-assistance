"""Bounded recipe data shared by model drafts and single-dish replacement requests."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Ingredient(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=24)
    amount: float = Field(gt=0, le=10000, allow_inf_nan=False)
    unit: Literal["克", "毫升", "个", "瓣"]


class RecipeDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=40)
    minutes: int = Field(ge=5, le=120)
    vegetarian: bool
    ingredients: list[Ingredient] = Field(min_length=1, max_length=12)
    staples: list[str] = Field(default_factory=list, max_length=11)
    steps: list[str] = Field(min_length=2, max_length=10)

    @field_validator("steps")
    @classmethod
    def check_steps(cls, values):
        if any(not step.strip() or len(step) > 300 for step in values):
            raise ValueError("每条步骤须为 1–300 字。")
        return [step.strip() for step in values]


class RetainedRecipe(RecipeDraft):
    id: str = Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9-]*$")
    # Ingredient amounts are the displayed quantities for this many people.
    servings: int = Field(ge=1, le=6)
