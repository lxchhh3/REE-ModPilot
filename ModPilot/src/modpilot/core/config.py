"""SceneConfig: the names of the things a build works on, stored on the scene.

The legacy tools hard-coded 'MHWilds_Female Armature' and 'MHWilds_Female.mesh' in a dozen
places. Here they live in `scene["modpilot_config"]` (JSON, so it survives .blend checkpoints);
`setup_import_mhwilds` writes the names it actually created, and a step resolves a name from its
own param first, then the config, and fails loudly when neither has it.
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass

from modpilot.core.errors import StepError

KEY = "modpilot_config"


@dataclass(frozen=True)
class SceneConfig:
    target_armature: str | None = "MHWilds_Female Armature"   # the template default, the only place it is written
    source_armature: str | None = None
    mesh_collection: str | None = "MHWilds_Female.mesh"
    mdf2_collection: str | None = None
    chain2_collection: str | None = None
    clsp_collection: str | None = None
    x_preset: str | None = None
    y_preset: str | None = "mhws"


def load_config(scene) -> SceneConfig:
    raw = scene.get(KEY) if hasattr(scene, "get") else None
    if not raw:
        return SceneConfig()
    data = json.loads(raw)
    known = {f.name for f in dataclasses.fields(SceneConfig)}
    return SceneConfig(**{k: v for k, v in data.items() if k in known})


def save_config(scene, cfg: SceneConfig) -> None:
    scene[KEY] = json.dumps(dataclasses.asdict(cfg), ensure_ascii=False)


def resolve(value, cfg: SceneConfig, field: str):
    """`value` if given, else the config's `field`; neither -> StepError precondition."""
    if value not in (None, ""):
        return value
    configured = getattr(cfg, field)
    if configured in (None, ""):
        raise StepError("precondition", f"no {field} given and none in the scene's modpilot_config",
                        details={"field": field})
    return configured
