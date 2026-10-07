from dataclasses import dataclass
from typing import Literal
from uuid import UUID


@dataclass(frozen=True)
class CurrentUser:
    user_id: UUID
    username: str
    role: Literal['user', 'admin']


class AuthUnavailable(Exception):
    pass


class UnprovisionedIdentity(Exception):
    pass
