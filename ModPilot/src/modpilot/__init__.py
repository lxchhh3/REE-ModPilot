"""ModPilot: MH Wilds mod-building steps that run inside Blender.

    import modpilot; modpilot.call("vertex_groups", {...})

returns the step's report (and prints it as one "MODPILOT_REPORT=<json>" line); a failure raises
StepError, whose text is "MODPILOT_ERROR=<json>". The same line works over Blender Lab MCP, the
community blender-mcp bridge and headless sessions.

Blender's modules are imported only inside these functions, so the bpy-free parts of the package
(modpilot.core.params, .errors, .report, .step, .config, and later formats / geom / checks)
import on the host too.
"""
__all__ = ["call", "reload", "steps", "describe"]


def call(name: str, params: dict | None = None, *, quiet: bool = False) -> dict:
    """Run step `name` with `params` in this Blender; return its report."""
    from modpilot.core import runtime
    return runtime.call(name, params, quiet=quiet)


def reload() -> list[str]:
    """Re-import every modpilot module now; returns their names."""
    from modpilot.core import runtime
    return runtime.reload_all()


def steps() -> list[str]:
    from modpilot.core import runtime
    return runtime.registry().names()


def describe(name: str) -> dict:
    """A step's params (name, type, default) and docstring."""
    from modpilot.core import runtime
    return runtime.describe(name)
