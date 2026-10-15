"""Admin DTOs for exercise catalog Form Studio 3D metadata."""

from pydantic import Field, field_validator

from app.schemas.common import APIModel, Form3dGuideStepOut, Form3dOut


class Form3dUpdateRequest(APIModel):
    enabled: bool | None = None
    clip_id: str | None = Field(default=None, max_length=128)
    character: str | None = Field(default=None, max_length=64)
    animation_url: str | None = Field(default=None, max_length=1024)
    cues: list[str] | None = None
    guide: list[Form3dGuideStepOut] | None = None
    mixamo_query: str | None = Field(default=None, max_length=255)

    @field_validator("animation_url")
    @classmethod
    def _https_or_null(cls, value: str | None) -> str | None:
        if value is None:
            return None
        v = value.strip()
        if not v:
            return None
        if not (v.startswith("https://") or v.startswith("/uploads/")):
            raise ValueError("animationUrl must be absolute https:// or /uploads/…")
        return v


class ExerciseCreateRequest(APIModel):
    id: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    muscle_group: str = Field(default="Full Body", max_length=64)
    equipment: str = Field(default="Bodyweight", max_length=64)
    difficulty: str = Field(default="Beginner", max_length=32)
    cues: list[str] = Field(default_factory=list)
    icon: str = Field(default="figure.strengthtraining.traditional", max_length=128)
    category: str | None = Field(default=None, max_length=64)
    muscles: list[str] = Field(default_factory=list)
    level: str | None = Field(default=None, max_length=32)
    equipment_list: list[str] = Field(default_factory=list)
    instructions: str | None = None
    common_mistakes: list[str] = Field(default_factory=list)
    thumbnail_url: str | None = None
    mixamo_query: str | None = None
    sort_order: int = 0
    form3d: Form3dOut | None = None


class Form3dUploadOut(APIModel):
    animation_url: str
    key: str
    content_type: str
