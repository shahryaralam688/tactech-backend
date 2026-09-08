from app.schemas.common import APIModel


class AboutSocialOut(APIModel):
    facebook: str | None = None
    instagram: str | None = None
    linkedin: str | None = None
    youtube: str | None = None


class AboutOut(APIModel):
    brand_name: str
    tagline: str
    address_lines: list[str]
    phones: list[str]
    social: AboutSocialOut


class FaqItemOut(APIModel):
    id: str
    question: str
    answer: str
