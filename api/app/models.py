"""Pydantic request/response schemas for the API."""

from pydantic import BaseModel, Field


class StudentCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=8)


class ResetPasswordRequest(BaseModel):
    password: str = Field(min_length=8)


class DeleteStudentRequest(BaseModel):
    confirm_username: str


class StudentPublic(BaseModel):
    student_id: str
    username: str
    active: bool
