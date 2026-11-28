"""isaac_devkit: mounted Isaac Sim robot-simulation framework.

Curated re-export surface for the ADR-0017 framework (isaac#130). The
public contract (ADR-0017 section 9) is re-exported here so consumers
import one stable namespace::

    from isaac_devkit import load_scene, build_scene, IsaacDriver

Import-safety invariant (ADR-0017 section 8 / PRD A1): importing this
package, or any of its modules, on a host without Isaac Sim must leave
``sys.modules`` free of ``omni`` / ``pxr`` / ``isaacsim``. Every Isaac
import inside the package is function-local; ``pxr`` type annotations
use ``TYPE_CHECKING`` string annotations only. Re-exporting the names
below is safe because each module keeps its Isaac imports function-local,
so importing the symbols does not trigger an Isaac import.
"""

from isaac_devkit.driver import (
    IsaacDriver,
    parse_livestream_env,
    resolve_repo_relative_usd,
)
from isaac_devkit.exceptions import (
    IsaacDevkitError,
    LinkNotFoundError,
    SceneError,
    SensorConfigError,
    SensorNotFoundError,
)
from isaac_devkit.scene import build_scene, load_scene
from isaac_devkit.sensors import setup_sensors
from isaac_devkit.usd_model import PrimSummary

# Tracks the repo git tag (ADR-0017 section 3); pre-release placeholder
# until the first release (v1.0.0 at the MVP gate, PRD A6). Keep in
# sync with framework/pyproject.toml [project] version.
__version__ = "0.1.0"

__all__ = [
    "__version__",
    # Scene (ADR-0017 section 9).
    "load_scene",
    "build_scene",
    # Sensors.
    "setup_sensors",
    # USD model structure.
    "PrimSummary",
    # Driver lifecycle (ADR-0009 / A2).
    "IsaacDriver",
    "parse_livestream_env",
    "resolve_repo_relative_usd",
    # Exception hierarchy.
    "IsaacDevkitError",
    "SceneError",
    "SensorConfigError",
    "SensorNotFoundError",
    "LinkNotFoundError",
]
