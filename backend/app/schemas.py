import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class ServiceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)


class ServiceOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str
    created_at: datetime


class MeOutput(BaseModel):
    user_id: uuid.UUID
    name: str
    email: str
    workspace_id: uuid.UUID
    workspace_name: str
    csrf_token: str


class SetupOutput(BaseModel):
    service_count: int
    github_connected: bool = False
    runbook_ready: bool = False
