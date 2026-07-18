"""Registro de perfiles + matcher cacheado del perfil activo.

Envuelve un `CommandsFileV2` inmutable y guarda el `active_profile_id` mutable.
Re-construye el `IntentMatcher` solo cuando cambia el perfil activo o la config.
"""
from __future__ import annotations

import threading
from collections.abc import Iterator

from .config import CommandsFileV2, Profile
from .intent import IntentMatcher


class ProfileRegistry:
    def __init__(self, cf: CommandsFileV2, active_id: str | None = None) -> None:
        self._lock = threading.RLock()
        self._cf = cf
        self._active_id = active_id or cf.settings.active_profile
        self._matcher_cache: tuple[str, IntentMatcher] | None = None

    @property
    def config(self) -> CommandsFileV2:
        return self._cf

    @property
    def active_id(self) -> str:
        with self._lock:
            return self._active_id

    def __iter__(self) -> Iterator[Profile]:
        return iter(self._cf.profiles)

    def ids(self) -> list[str]:
        return [p.id for p in self._cf.profiles]

    def active(self) -> Profile:
        with self._lock:
            return self._cf.get_profile(self._active_id)

    def matcher(self) -> IntentMatcher:
        with self._lock:
            if self._matcher_cache is None or self._matcher_cache[0] != self._active_id:
                self._matcher_cache = (
                    self._active_id,
                    IntentMatcher(self.active().commands),
                )
            return self._matcher_cache[1]

    def set_active(self, profile_id: str) -> bool:
        with self._lock:
            if profile_id == self._active_id:
                return True
            try:
                self._cf.get_profile(profile_id)
            except KeyError:
                return False
            self._active_id = profile_id
            self._matcher_cache = None
            return True

    def cycle_next(self) -> str:
        with self._lock:
            ids = self.ids()
            idx = ids.index(self._active_id) if self._active_id in ids else -1
            new_id = ids[(idx + 1) % len(ids)]
            self._active_id = new_id
            self._matcher_cache = None
            return new_id

    def replace_config(self, new_cf: CommandsFileV2) -> None:
        with self._lock:
            self._cf = new_cf
            # Si el perfil activo desapareció, fallback al active_profile del nuevo settings,
            # y si tampoco existe, al primero.
            ids = [p.id for p in new_cf.profiles]
            if self._active_id not in ids:
                self._active_id = (
                    new_cf.settings.active_profile if new_cf.settings.active_profile in ids
                    else ids[0]
                )
            self._matcher_cache = None
