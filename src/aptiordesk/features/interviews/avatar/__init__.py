"""Coordinated interviewer-avatar behavior and rendering."""

from .assets import DEFAULT_AVATAR_ID, avatar_catalog, get_avatar, prepare_avatar
from .controller import AvatarController, AvatarState
from .picker import AvatarPickerDialog
from .stage import AvatarStage

__all__ = [
    "AvatarController",
    "AvatarPickerDialog",
    "AvatarStage",
    "AvatarState",
    "DEFAULT_AVATAR_ID",
    "avatar_catalog",
    "get_avatar",
    "prepare_avatar",
]
