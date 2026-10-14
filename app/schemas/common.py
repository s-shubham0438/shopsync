"""Shared response shapes: error envelope and pagination."""

import math
from typing import Annotated

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field


class APIModel(BaseModel):
    """Base for all API schemas; can be built directly from ORM objects."""

    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class ErrorDetail(APIModel):
    loc: list[str | int] | None = Field(
        default=None, description="Path to the offending field, e.g. ['query', 'page']"
    )
    message: str
    type: str | None = Field(default=None, description="Machine-readable error type")


class ErrorBody(APIModel):
    code: str = Field(description="Stable machine-readable code, e.g. 'not_found'")
    message: str = Field(description="Human-readable message, safe to show to users")
    details: list[ErrorDetail] | None = None
    request_id: str | None = Field(default=None, description="Echoes the X-Request-ID header")


class ErrorResponse(APIModel):
    """Every non-2xx response has this shape."""

    error: ErrorBody


# --------------------------------------------------------------------------- #
# Pagination
# --------------------------------------------------------------------------- #
class PageParams:
    """Query-parameter dependency: ``params: Annotated[PageParams, Depends()]``."""

    def __init__(
        self,
        page: Annotated[int, Query(ge=1, description="1-based page number")] = 1,
        page_size: Annotated[int, Query(ge=1, le=100, description="Items per page")] = 20,
    ) -> None:
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class Page[T](APIModel):
    items: list[T]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    pages: int = Field(ge=0)

    @classmethod
    def build(cls, items: list[T], total: int, params: PageParams) -> Page[T]:
        return cls(
            items=items,
            total=total,
            page=params.page,
            page_size=params.page_size,
            pages=math.ceil(total / params.page_size) if total else 0,
        )
