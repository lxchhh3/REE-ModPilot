"""modpilot.call: run one step inside Blender and report it.

    parse params strictly -> snapshot -> run the step with add-on popups captured -> snapshot
    -> report (plain JSON, printed as MODPILOT_REPORT=...)

Any failure raises StepError (printed as MODPILOT_ERROR=... first, so a bridge that returns only
stdout still carries it); an error popup from an add-on fails the call; a plain exception becomes
StepError("internal") with its traceback. Before each call the package's source files are checked:
if any changed since they were imported, every modpilot module is re-imported first, so a live
Blender picks up edits without a restart (the report's code.reloaded says so).
"""
from __future__ import annotations

import dataclasses
import importlib
import sys
import time
import traceback
import typing
from dataclasses import dataclass, field
from pathlib import Path

from modpilot.core.config import SceneConfig, load_config, save_config
from modpilot.core.errors import StepError
from modpilot.core.params import parse
from modpilot.core.report import PREFIX, dumps_report, make_report

PKG = Path(__file__).resolve().parents[1]


def _source_stamp() -> dict[str, int]:
    return {p.relative_to(PKG).as_posix(): p.stat().st_mtime_ns for p in PKG.rglob("*.py")}


_STAMP = _source_stamp()


def stale() -> bool:
    return _source_stamp() != _STAMP


def reload_all() -> list[str]:
    names = sorted(n for n in sys.modules if n == "modpilot" or n.startswith("modpilot."))
    for n in names:
        del sys.modules[n]
    importlib.import_module("modpilot")
    importlib.import_module("modpilot.steps")
    return names


def registry():
    import modpilot.steps  # noqa: F401  (registers every step)
    from modpilot.core.step import REGISTRY
    return REGISTRY


@dataclass
class StepContext:
    """What a step gets besides its params."""
    scene: object
    config: SceneConfig
    warnings: list = field(default_factory=list)
    skipped: list = field(default_factory=list)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def skip(self, what: str, why: str) -> None:
        self.skipped.append({"what": what, "why": why})

    def set_config(self, **changes) -> SceneConfig:
        self.config = dataclasses.replace(self.config, **changes)
        save_config(self.scene, self.config)
        return self.config


def describe(name: str) -> dict:
    st = registry().get(name)
    hints = typing.get_type_hints(st.params_cls)
    params = []
    for f in dataclasses.fields(st.params_cls):
        required = f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING
        default = None if required else (f.default if f.default is not dataclasses.MISSING else f.default_factory())
        params.append({"name": f.name, "type": str(hints[f.name]).replace("typing.", ""),
                       "required": required, "default": default})
    return {"step": name, "mutates": st.mutates, "needs": list(st.needs), "params": params, "doc": st.doc}


def call(name: str, params: dict | None = None, *, quiet: bool = False, _reloaded: bool = False) -> dict:
    if not _reloaded and stale():
        reload_all()
        fresh = importlib.import_module("modpilot.core.runtime")
        return fresh.call(name, params, quiet=quiet, _reloaded=True)

    import bpy

    from modpilot.core import popups, snapshot, version
    t0 = time.perf_counter()
    try:
        st = registry().get(name)
        p = parse(st.params_cls, params)
        ctx = StepContext(scene=bpy.context.scene, config=load_config(bpy.context.scene))
        before = snapshot.take()
        with popups.capture() as cap:
            data = st.fn(p, ctx)
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise StepError("internal", f"step returned {type(data).__name__}, not a dict")
        if cap.errors:
            first = cap.errors[0]
            raise StepError("operator", f"{first['module']} reported: {first['message']}"[:500],
                            details={"popups": cap.records}, partial={"data": data})
        report = make_report(step=name, params=params or {}, data=data, warnings=ctx.warnings,
                             skipped=ctx.skipped, scene_diff=snapshot.diff(before, snapshot.take()),
                             popups=cap.records, seconds=time.perf_counter() - t0,
                             code={**version.code(), "reloaded": _reloaded},
                             blender=bpy.app.version_string)
        text = dumps_report(report)
    except StepError as err:
        if not err.step:
            err.step = name
        if not quiet:
            print(str(err))
        raise
    except Exception as exc:  # a bug in a step: reported, never swallowed
        err = StepError("internal", f"{type(exc).__name__}: {exc}"[:500], step=name,
                        details={"traceback": traceback.format_exc()[-6000:]})
        if not quiet:
            print(str(err))
        raise err from exc
    if not quiet:
        print(PREFIX + text)
    return report
