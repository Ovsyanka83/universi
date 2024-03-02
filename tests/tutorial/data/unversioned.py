from pydantic import Field

from .head.users import UserCreateRequest


class InternalUserCreateRequest(UserCreateRequest):
    addresses_to_create: list[str] = Field(default_factory=list)
