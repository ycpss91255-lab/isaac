"""Launch a USD scene with the default driver or a user-defined IsaacDriver."""

import argparse
import importlib.util
import sys
from pathlib import Path

from isaac_devkit.default_driver import DefaultSceneDriver
from isaac_devkit.driver import IsaacDriver


def load_driver_class(driver_path: str | Path) -> type[IsaacDriver]:
    """Load the single IsaacDriver subclass defined in the supplied Python file."""
    path = Path(driver_path).resolve()
    name = f"_isaac_scene_driver_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load Python driver from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    classes = {
        cls
        for cls in vars(module).values()
        if isinstance(cls, type)
        and cls.__module__ == module.__name__
        and issubclass(cls, IsaacDriver)
    }
    if len(classes) != 1:
        raise ValueError(
            f"{path} must define exactly one IsaacDriver subclass, found {len(classes)}"
        )
    return classes.pop()


def build_driver(
    usd_path: str | Path, driver_path: str | Path | None = None
) -> IsaacDriver:
    """Use the CLI USD unless the custom driver specifies its own USD."""
    if driver_path is None:
        return DefaultSceneDriver(usd_path)
    driver = load_driver_class(driver_path)()
    if not driver.USD:
        driver.USD = str(Path(usd_path).resolve())
    return driver


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("usd", help="USD file to open")
    parser.add_argument("--driver", help="Python file defining one IsaacDriver subclass")
    args = parser.parse_args(argv)
    build_driver(args.usd, driver_path=args.driver).run()


if __name__ == "__main__":
    main()
