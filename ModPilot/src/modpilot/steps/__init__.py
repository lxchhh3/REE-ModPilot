"""Every ModPilot step. Importing this package registers them (modpilot.core.step.REGISTRY)."""
from modpilot.steps import (  # noqa: F401
    doctor,
    fingerprint,
    physics,
    pose,
    query,
    setup,
    vertex_groups,
)
