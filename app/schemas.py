from typing import Literal

from pydantic import BaseModel, Field

NO_DATA = "данных нет"


class ProductInput(BaseModel):
    name: str
    manufacturer: str = ""
    product_type: str = ""
    category: str = ""
    sku: str = ""
    url: str = ""
    specs: dict[str, str] = Field(default_factory=dict)
    description: str = ""


class MissingField(BaseModel):
    field: str
    reason: str


class KeySpec(BaseModel):
    name: str
    value: str
    source: str


class Commercial(BaseModel):
    summary: str
    target_customers: list[str]
    tasks: list[str]


class LLMCard(BaseModel):
    data_conflicts: list[str]
    key_specs: list[KeySpec]
    seo_title: str
    seo_description: str
    search_queries: list[str]
    commercial: Commercial


SpecStatus = Literal["ok", "corrected", "from_text", "no_data"]


class SpecLine(BaseModel):
    name: str
    value: str
    source: str
    status: SpecStatus


class Quality(BaseModel):
    needs_review: bool
    attempts: int
    seo_title_length: int
    seo_description_length: int
    warnings: list[str]
    repaired_issues: list[str]


class ProductRef(BaseModel):
    name: str
    manufacturer: str
    sku: str
    url: str


class CardResult(BaseModel):
    product: ProductRef
    seo_title: str
    seo_description: str
    key_specs: list[SpecLine]
    search_queries: list[str]
    commercial: Commercial
    missing_fields: list[MissingField]
    data_conflicts: list[str]
    quality: Quality
    model: str
    generated_at: str
