"""Default driver for playing a USD scene."""

from pathlib import Path

from isaac_devkit.driver import IsaacDriver


class DefaultSceneDriver(IsaacDriver):
    """Open a USD and run the inherited timeline and update loop."""

    def __init__(self, usd_path: str | Path) -> None:
        super().__init__()
        if not usd_path:
            raise ValueError("usd_path is required")
        self.USD = str(Path(usd_path).resolve())
