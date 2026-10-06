from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


RiskLevel = Literal["Low", "Medium", "High"]
AnomalyStatus = Literal["Open", "Reviewed", "Resolved"]
class ClientCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    industry: str = Field(min_length=2, max_length=100)
    risk: RiskLevel = "Low"

    @field_validator("name", "industry")
    @classmethod
    def trim_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be blank")
        return value


class ClientUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=120)
    industry: str | None = Field(default=None, min_length=2, max_length=100)
    risk: RiskLevel | None = None

    @field_validator("name", "industry")
    @classmethod
    def trim_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be blank")
        return value


class TransactionStatusUpdate(BaseModel):
    status: Literal["Matched"]


class AnomalyStatusUpdate(BaseModel):
    status: AnomalyStatus


class ReportCreate(BaseModel):
    client_id: str = Field(min_length=1, max_length=20)
    report_type: str = Field(min_length=2, max_length=100)
    financial_year: str = Field(min_length=4, max_length=20)


class ChatRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=20)
    question: str = Field(min_length=1, max_length=1000)

    @field_validator("question")
    @classmethod
    def trim_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Question cannot be blank")
        return value


class SettingsUpdate(BaseModel):
    fullName: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    role: str = Field(min_length=1, max_length=80)
    firmName: str = Field(min_length=1, max_length=160)
    officeEmail: str = Field(min_length=3, max_length=254)
    officeLocation: str = Field(min_length=1, max_length=160)
    emailNotifications: bool
    riskAlerts: bool
    reportNotifications: bool
    twoFactor: bool
    theme: Literal["light", "system"]
    layout: Literal["Comfortable", "Compact"]

    @field_validator("fullName", "role", "firmName", "officeLocation")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be blank")
        return value

    @field_validator("email", "officeEmail")
    @classmethod
    def validate_email_shape(cls, value: str) -> str:
        value = value.strip()
        if value.count("@") != 1 or "." not in value.rsplit("@", 1)[-1]:
            raise ValueError("Enter a valid email address")
        return value
