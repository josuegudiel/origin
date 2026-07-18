"""Modelo + carga + migración + persistencia de commands.yaml.

v3: settings con subbloques `tts`, `hotas`, `llm`. Cada comando puede declarar
`steps:` (scripting DSL) además o en vez de `keys:`. `say_es`/`say_en`/`say_key`
para TTS opcional. Backward compatible: archivos v2 cargan sin tocar nada (los
nuevos campos toman defaults).

v2: settings + profiles. Cada comando tiene phrases_es/phrases_en y labels.
v1: settings + commands plano. Se migra a v3 dentro de un perfil `default`.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
VAR_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
# Validación real (incluyendo nombres de tecla soportados) la hace keypress.parse_combo.
KEYCOMBO_RE = re.compile(r"^[a-z0-9_+]+$")
# Operadores aceptados por el evaluador de `if` en script.py.
COND_RE = re.compile(r"^\s*[a-z_][a-z0-9_]*\s*(==|!=|>=|<=|>|<)\s*.+\s*$")
# SEGURIDAD: nombre de voz TTS. Sin `/`, `\` ni `..` → previene path traversal
# que cargaría un `.onnx` arbitrario del disco en piper/onnxruntime.
VOICE_STEM_RE = re.compile(r"^[A-Za-z0-9._-]+$")

MAX_STEPS_PER_COMMAND = 100


class ConfigError(Exception):
    """Error de configuración (formato, validación, versión)."""


# ============================================================================
# Settings (con subbloques v3)
# ============================================================================


class TtsSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    enabled: bool = True
    voice_es: str = "es_ES-mls_10246-low"
    voice_en: str = "en_US-amy-low"
    default_response_when_no_say: bool = True
    cancel_on_ptt: bool = True
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    volume: float = Field(default=1.0, ge=0.0, le=1.5)

    @field_validator("voice_es", "voice_en")
    @classmethod
    def _voice_stem_safe(cls, v: str) -> str:
        # SEGURIDAD: el stem se interpola en un path (`voices/<stem>.onnx`).
        # Rechazar separadores y `..` evita cargar un `.onnx` arbitrario del disco.
        if not VOICE_STEM_RE.match(v):
            raise ValueError(
                f"nombre de voz inválido '{v}': solo letras, dígitos, '.', '_' y '-'"
            )
        return v


class HotasSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    enabled: bool = False
    button_binding: str | None = None   # "<device_index>:<button_name>" o None
    poll_hz: int = Field(default=60, ge=10, le=240)


class LlmSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    enabled: bool = False
    base_url: str = "http://localhost:11434"
    model: str = "llama3.1:8b"
    timeout_ms: int = Field(default=8000, ge=500, le=60_000)
    floor_score: int = Field(default=60, ge=0, le=100)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_commands_per_resolution: int = Field(default=5, ge=1, le=20)

    @field_validator("base_url")
    @classmethod
    def _base_url_safe(cls, v: str) -> str:
        # SEGURIDAD: la transcripción del micrófono viaja en el body del POST a
        # base_url. Restringir el scheme a http/https evita que httpx siga
        # esquemas raros, y bloquear IPs de metadata cloud corta el SSRF clásico.
        # (El aviso de exfiltración a un host no-loopback lo emite llm.preflight.)
        from urllib.parse import urlparse

        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"base_url debe ser http(s), no '{parsed.scheme}': {v}")
        host = (parsed.hostname or "").lower()
        blocked = {"169.254.169.254", "metadata.google.internal", "metadata"}
        if host in blocked:
            raise ValueError(f"base_url apunta a un endpoint de metadata bloqueado: {host}")
        return v


GESTURES = ("nod", "shake", "tilt_left", "tilt_right", "lean_in", "lean_out")


class HeadAxis(BaseModel):
    """Configuración por eje de la pose de cabeza (sens/invert/deadzone)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sensitivity: float = Field(default=1.0, ge=0.0, le=8.0)
    invert: bool = False
    deadzone: float = Field(default=0.0, ge=0.0, le=45.0)


class OpenTrackSettings(BaseModel):
    """Salida UDP hacia OpenTrack (6DoF → head-look en SC y 200+ juegos)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = Field(default=4242, ge=1, le=65535)

    @field_validator("host")
    @classmethod
    def _host_safe(cls, v: str) -> str:
        # SEGURIDAD: la pose de cabeza sale por UDP a host:port. Restringir a
        # loopback/LAN por default evita mandar el stream a un host arbitrario
        # de Internet desde un perfil compartido. Se acepta hostname o IP.
        if not v or "/" in v or "\\" in v or ":" in v:
            raise ValueError(f"host inválido: '{v}'")
        return v


class GestureBinding(BaseModel):
    """Mapea un gesto de cabeza a un comando del perfil (por id)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    gesture: Literal["nod", "shake", "tilt_left", "tilt_right", "lean_in", "lean_out"]
    command_id: str
    enabled: bool = True

    @field_validator("command_id")
    @classmethod
    def _cmd_id_format(cls, v: str) -> str:
        if not ID_RE.match(v):
            raise ValueError(f"command_id inválido '{v}'")
        return v


class HeadTrackSettings(BaseModel):
    """Head tracking por webcam (clon del núcleo de Beam Eye Tracker).

    Estima la pose de la cabeza (yaw/pitch/roll + x/y/z) desde una webcam y la
    manda a OpenTrack (head-look 6DoF) y/o dispara comandos por gestos.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    enabled: bool = False
    camera_index: int = Field(default=0, ge=0, le=16)
    backend: Literal["mediapipe", "mock"] = "mediapipe"
    fps_target: int = Field(default=30, ge=10, le=120)
    # Suavizado exponencial (EMA). 0 = sin suavizado, 0.9 = muy suave/lento.
    smoothing: float = Field(default=0.35, ge=0.0, le=0.95)

    yaw: HeadAxis = Field(default_factory=HeadAxis)
    pitch: HeadAxis = Field(default_factory=HeadAxis)
    roll: HeadAxis = Field(default_factory=HeadAxis)
    pos_x: HeadAxis = Field(default_factory=HeadAxis)
    pos_y: HeadAxis = Field(default_factory=HeadAxis)
    pos_z: HeadAxis = Field(default_factory=HeadAxis)

    opentrack: OpenTrackSettings = Field(default_factory=OpenTrackSettings)
    gestures: list[GestureBinding] = Field(default_factory=list)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    # ===== heredados de v2 =====
    ptt_key: str = "f12"
    profile_switch_hotkey: str = "ctrl+f12"
    ui_language: Literal["es", "en"] = "es"
    active_profile: str = "default"
    whisper_model: Literal["tiny", "base", "small", "medium", "large-v3"] = "small"
    whisper_device: Literal["auto", "cpu", "cuda"] = "auto"
    whisper_compute_type: Literal["auto", "int8", "int8_float16", "float16", "float32"] = "auto"
    active_language: Literal["es", "en"] = "es"
    fuzz_threshold: int = Field(default=75, ge=0, le=100)
    mic_device: int | None = None
    sample_rate: int = Field(default=16000, ge=8000, le=48000)
    max_record_seconds: int = Field(default=8, ge=1, le=60)
    inter_key_delay_ms: int = Field(default=30, ge=0, le=500)
    log_format: Literal["pretty", "json"] = "pretty"
    start_minimized: bool = False
    autostart_windows: bool = False
    theme: Literal["system", "light", "dark"] = "system"

    # ===== v3 =====
    tts: TtsSettings = Field(default_factory=TtsSettings)
    hotas: HotasSettings = Field(default_factory=HotasSettings)
    llm: LlmSettings = Field(default_factory=LlmSettings)
    headtrack: HeadTrackSettings = Field(default_factory=HeadTrackSettings)


# ============================================================================
# Step types (scripting DSL)
# ============================================================================


class KeyStep(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)
    type: Literal["key"] = "key"
    combo: str
    hold_ms: int | None = Field(default=None, ge=0, le=10_000)

    @field_validator("combo")
    @classmethod
    def _combo_format(cls, v: str) -> str:
        if not KEYCOMBO_RE.match(v.lower()):
            raise ValueError(f"combo inválido '{v}'")
        # SEGURIDAD: validación semántica al cargar (no solo formato) — rechaza
        # `win+*` y atajos de sistema en el paso de config, para que un perfil
        # malicioso se rechace al importarlo, no en silencio al ejecutarlo.
        from . import keypress
        err = keypress.validate(v)
        if err:
            raise ValueError(err)
        return v.lower()


class WaitStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["wait"] = "wait"
    ms: int = Field(ge=0, le=30_000)


class SayStep(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)
    type: Literal["say"] = "say"
    text: str | None = None
    text_es: str | None = None
    text_en: str | None = None

    @model_validator(mode="after")
    def _has_text(self) -> SayStep:
        if not (self.text or self.text_es or self.text_en):
            raise ValueError("say: al menos uno de text/text_es/text_en")
        return self


class SayKeyStep(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)
    type: Literal["say_key"] = "say_key"
    key: str


class SetStep(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)
    type: Literal["set"] = "set"
    var: str
    value: str

    @field_validator("var")
    @classmethod
    def _var_format(cls, v: str) -> str:
        if not VAR_RE.match(v):
            raise ValueError(f"var inválida '{v}': snake_case minúsculas")
        return v


class IfStep(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True, populate_by_name=True)
    type: Literal["if"] = "if"
    cond: str
    then: list[Step]
    else_: list[Step] | None = Field(default=None, alias="else")

    @field_validator("cond")
    @classmethod
    def _cond_format(cls, v: str) -> str:
        if not COND_RE.match(v):
            raise ValueError(
                f"condición inválida '{v}': usar 'var <op> valor' con op ∈ ==|!=|>|<|>=|<="
            )
        return v


class GotoStep(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)
    type: Literal["goto"] = "goto"
    label: str


class LabelStep(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)
    type: Literal["label"] = "label"
    name: str


class RepeatStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["repeat"] = "repeat"
    times: int = Field(ge=1, le=20)
    steps: list[Step]


Step = Annotated[
    KeyStep | WaitStep | SayStep | SayKeyStep | SetStep | IfStep | GotoStep | LabelStep | RepeatStep,
    Field(discriminator="type"),
]

# Resolver las recursive refs (IfStep.then, IfStep.else_, RepeatStep.steps).
IfStep.model_rebuild()
RepeatStep.model_rebuild()


def _count_steps(steps: list[Any]) -> int:
    total = 0
    for s in steps:
        total += 1
        if isinstance(s, IfStep):
            total += _count_steps(list(s.then))
            if s.else_:
                total += _count_steps(list(s.else_))
        elif isinstance(s, RepeatStep):
            total += _count_steps(list(s.steps)) * s.times
    return total


# ============================================================================
# Command + Profile
# ============================================================================


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    id: str
    phrases_es: list[str] = Field(default_factory=list)
    phrases_en: list[str] = Field(default_factory=list)
    keys: list[str] = Field(default_factory=list)
    steps: list[Step] | None = None
    label_es: str | None = None
    label_en: str | None = None
    description_es: str | None = None
    description_en: str | None = None
    say_es: str | None = None
    say_en: str | None = None
    say_key: str | None = None

    @field_validator("id")
    @classmethod
    def _id_format(cls, v: str) -> str:
        if not ID_RE.match(v):
            raise ValueError(f"id inválido '{v}': usar snake_case minúsculas/dígitos, 1-32 chars")
        return v

    @field_validator("keys")
    @classmethod
    def _keys_format(cls, v: list[str]) -> list[str]:
        from . import keypress
        for k in v:
            if not KEYCOMBO_RE.match(k.lower()):
                raise ValueError(f"combo inválido '{k}': usar p.ej. 'alt+n', 'l', 'ctrl+shift+x'")
            # SEGURIDAD: rechaza `win+*` y atajos de sistema al cargar (v1/v2).
            err = keypress.validate(k)
            if err:
                raise ValueError(err)
        return [k.lower() for k in v]

    @model_validator(mode="after")
    def _at_least_one_phrase(self) -> Command:
        if not self.phrases_es and not self.phrases_en:
            raise ValueError(
                f"comando '{self.id}': al menos una de phrases_es/phrases_en debe tener entradas"
            )
        if not self.keys and not self.steps:
            raise ValueError(
                f"comando '{self.id}': debe declarar 'keys' o 'steps'"
            )
        # tope duro de pasos (incluye anidados + repeats expandidos)
        if self.steps is not None:
            total = _count_steps(list(self.steps))
            if total > MAX_STEPS_PER_COMMAND:
                raise ValueError(
                    f"comando '{self.id}' supera el tope de {MAX_STEPS_PER_COMMAND} steps (got {total})"
                )
        return self

    def label_for(self, lang: str) -> str:
        if lang == "en":
            return self.label_en or self.label_es or self.id
        return self.label_es or self.label_en or self.id

    def description_for(self, lang: str) -> str:
        if lang == "en":
            return self.description_en or self.description_es or ""
        return self.description_es or self.description_en or ""

    def phrases_for(self, lang: str) -> list[str]:
        return self.phrases_en if lang == "en" else self.phrases_es

    def say_for(self, lang: str) -> str | None:
        if lang == "en":
            return self.say_en or self.say_es
        return self.say_es or self.say_en


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    id: str
    label_es: str | None = None
    label_en: str | None = None
    description_es: str | None = None
    description_en: str | None = None
    commands: list[Command]

    @field_validator("id")
    @classmethod
    def _id_format(cls, v: str) -> str:
        if not ID_RE.match(v):
            raise ValueError(f"id de perfil inválido '{v}'")
        return v

    @model_validator(mode="after")
    def _unique_command_ids(self) -> Profile:
        seen = set()
        for c in self.commands:
            if c.id in seen:
                raise ValueError(f"perfil '{self.id}': command id duplicado '{c.id}'")
            seen.add(c.id)
        return self

    def label_for(self, lang: str) -> str:
        if lang == "en":
            return self.label_en or self.label_es or self.id
        return self.label_es or self.label_en or self.id


class CommandsFileV3(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[2, 3] = 3
    settings: Settings = Field(default_factory=Settings)
    profiles: list[Profile]

    @model_validator(mode="after")
    def _validate_profiles(self) -> CommandsFileV3:
        if not self.profiles:
            raise ValueError("debe existir al menos un perfil")
        ids = [p.id for p in self.profiles]
        if len(ids) != len(set(ids)):
            raise ValueError(f"profile ids duplicados: {ids}")
        if self.settings.active_profile not in ids:
            raise ValueError(
                f"settings.active_profile='{self.settings.active_profile}' no existe en profiles"
            )
        return self

    def get_profile(self, profile_id: str) -> Profile:
        for p in self.profiles:
            if p.id == profile_id:
                return p
        raise KeyError(profile_id)

    def with_settings(self, **changes: Any) -> CommandsFileV3:
        """Cambios flat + cambios anidados a sub-settings (tts, hotas, llm, headtrack).

        Ej: cf.with_settings(active_language="en")
            cf.with_settings(tts={"enabled": True, "voice_es": "..."}}
            cf.with_settings(headtrack={"enabled": True})
        """
        merged = self.settings.model_dump()
        for k, v in changes.items():
            if k in ("tts", "hotas", "llm", "headtrack") and isinstance(v, dict):
                merged[k] = {**merged.get(k, {}), **v}
            else:
                merged[k] = v
        return self.model_copy(update={"settings": Settings(**merged)})

    def to_dump(self) -> dict[str, Any]:
        # `by_alias=True` para que `IfStep.else_` se serialice como `else:` en YAML
        # (alias del campo Pydantic). Sin esto, el YAML auto-saved tenía `else_:`,
        # técnicamente válido por populate_by_name pero inconsistente con el YAML
        # escrito a mano por humanos en commands.preset.yaml.
        return self.model_dump(mode="json", exclude_none=False, by_alias=True)


# Backwards-compat alias: el resto del codebase importa `CommandsFileV2`.
CommandsFileV2 = CommandsFileV3


# ============================================================================
# Carga + migración
# ============================================================================


def load(path: Path) -> CommandsFileV3:
    """Carga commands.yaml. Migra v1→v3 / v2→v3 si hace falta y deja backup."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"YAML inválido en {path}: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: el root debe ser un mapping")
    version = raw.get("version", 1)
    if version == 1:
        migrated = _migrate_v1_to_v3(raw)
        _save_backup(path, "commands.v1.backup.yaml", raw)
        return migrated
    if version == 2:
        # Pre-flight backup, luego carga directa (el schema v3 acepta version: 2).
        _save_backup(path, "commands.v2.backup.yaml", raw)
        try:
            return CommandsFileV3.model_validate(raw)
        except Exception as e:
            raise ConfigError(f"validación v2/v3 falló en {path}: {e}") from e
    if version == 3:
        try:
            return CommandsFileV3.model_validate(raw)
        except Exception as e:
            raise ConfigError(f"validación v3 falló en {path}: {e}") from e
    raise ConfigError(f"versión no soportada en {path}: {version}")


def _save_backup(path: Path, name: str, raw: dict[str, Any]) -> None:
    backup = path.with_name(name)
    if not backup.exists():
        backup.write_text(
            yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )


def _migrate_v1_to_v3(raw: dict[str, Any]) -> CommandsFileV3:
    settings = dict(raw.get("settings", {}))
    if "language" in settings and "active_language" not in settings:
        settings["active_language"] = settings.pop("language")
    settings.setdefault("active_profile", "default")
    settings.setdefault("ui_language", "es")
    settings.setdefault("profile_switch_hotkey", "ctrl+f12")

    commands_v3: list[dict[str, Any]] = []
    for c in raw.get("commands", []):
        cid = c["id"]
        commands_v3.append(
            {
                "id": cid,
                "phrases_es": list(c.get("phrases", [])),
                "phrases_en": [],
                "keys": list(c.get("keys", [])),
                "label_es": cid.replace("_", " ").title(),
                "label_en": cid.replace("_", " ").title(),
            }
        )

    return CommandsFileV3.model_validate(
        {
            "version": 3,
            "settings": settings,
            "profiles": [
                {
                    "id": "default",
                    "label_es": "Por defecto",
                    "label_en": "Default",
                    "description_es": "Perfil migrado desde commands.yaml v1.",
                    "description_en": "Profile migrated from commands.yaml v1.",
                    "commands": commands_v3,
                }
            ],
        }
    )


# ============================================================================
# keys → steps helper (unifica el motor de ejecución)
# ============================================================================


def command_as_steps(cmd: Command, settings: Settings) -> list[Any]:
    """Devuelve los `steps` declarados, o los traduce desde `keys` (+ say opcional).

    El runtime SIEMPRE invoca StepExecutor con el resultado de esta función.
    No hay 2 ramas keys-vs-steps en runtime.
    """
    if cmd.steps is not None:
        return list(cmd.steps)
    out: list[Any] = []
    for i, combo in enumerate(cmd.keys):
        if i > 0:
            out.append(WaitStep(ms=settings.inter_key_delay_ms))
        out.append(KeyStep(combo=combo))
    if settings.tts.enabled:
        # Resolvemos el texto del say con un fallback explícito. Antes el SayStep
        # podía quedar con todos los campos None si el comando no tenía say_es,
        # say_en, ni label_es/en — el validator de SayStep lo rechazaba en runtime.
        say_es = cmd.say_es
        say_en = cmd.say_en
        fallback = (
            (cmd.label_es or cmd.label_en)
            if settings.tts.default_response_when_no_say
            else None
        )
        if say_es or say_en or fallback:
            out.append(SayStep(text=fallback, text_es=say_es, text_en=say_en))
    return out


# ============================================================================
# Persistencia atómica
# ============================================================================


def save_atomic(cf: CommandsFileV3, path: Path) -> None:
    """Escribe a tmp y rename — evita corrupción si el proceso muere a mitad del write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".commands-", suffix=".yaml", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                cf.to_dump(),
                f,
                sort_keys=False,
                allow_unicode=True,
                default_flow_style=False,
            )
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
