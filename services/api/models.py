from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class WorkspaceCreate(StrictBody):
    name: str = Field(min_length=1, max_length=100, pattern=r"^[^\x00-\x1f\x7f]+$")


class PortfolioCreate(WorkspaceCreate):
    base_currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")


class PortfolioUpdate(WorkspaceCreate):
    version: int = Field(ge=1, strict=True)


class WorkspaceView(BaseModel):
    id: UUID
    name: str
    role: Literal["owner", "admin", "member", "viewer"]
    created_at: datetime


class PortfolioView(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    base_currency: str
    version: int
    created_at: datetime
    updated_at: datetime


class OnboardingCreate(StrictBody):
    workspace_name: str = Field(min_length=1, max_length=100, pattern=r"^[^\x00-\x1f\x7f]+$")
    portfolio_name: str = Field(min_length=1, max_length=100, pattern=r"^[^\x00-\x1f\x7f]+$")
    base_currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")


class OnboardingView(BaseModel):
    workspace: WorkspaceView
    portfolio: PortfolioView


class WorkspacePage(BaseModel):
    items: list[WorkspaceView]
    next_cursor: UUID | None


class PortfolioPage(BaseModel):
    items: list[PortfolioView]
    next_cursor: UUID | None
