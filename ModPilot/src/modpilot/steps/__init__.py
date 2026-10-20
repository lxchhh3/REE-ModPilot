"""Every ModPilot step. Importing this package registers them (modpilot.core.step.REGISTRY)."""
from modpilot.steps import (  # noqa: F401
    colliders,
    doctor,
    fingerprint,
    materials,
    physics,
    pose,
    query,
    setup,
    vertex_groups,
)
