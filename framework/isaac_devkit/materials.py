"""Load material YAML and resolve a flat mapping of per-prim properties.

The scene builder uses the first declared diffuse color to configure a
Core Experimental PreviewSurfaceMaterial at spawn time. Structural
variants can still use USD variant sets. The mapping is JSON-serializable
and can be prepared without loading Isaac Sim.

Usage:

    from isaac_devkit.materials import (
        load_material_config, material_cfg_from_yaml,
    )
    cfg = load_material_config("model/usd/object/obstacle/material.yaml")
    spawn_material = material_cfg_from_yaml(cfg, variant="blue")
"""

from pathlib import Path

import yaml


def load_material_config(path):
    """Load and validate a material YAML config."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"material config not found: {p}")
    with p.open() as f:
        cfg = yaml.safe_load(f)
    _validate(cfg, source=str(p))
    cfg["_source"] = str(p)
    return cfg


def get_variant_names(cfg):
    """Return list of variant names, or [] if single material mode."""
    if "variants" not in cfg:
        return []
    return list(cfg["variants"].keys())


def get_prim_material_map(cfg, variant=None):
    """Return {prim_path: material_props} for the given variant.

    In single material mode, variant is ignored.
    In variant mode, if variant is None, uses default_variant.
    """
    if "materials" in cfg:
        return dict(cfg["materials"])

    if variant is None:
        variant = cfg.get("default_variant")
    variants = cfg["variants"]
    if variant not in variants:
        raise ValueError(
            f"variant '{variant}' not found in {sorted(variants.keys())}"
        )
    return dict(variants[variant])


def resolve_texture_path(texture_rel, model_dir):
    """Resolve a texture path relative to the model directory."""
    resolved = Path(model_dir) / texture_rel
    if not resolved.exists():
        raise FileNotFoundError(
            f"texture not found: {resolved} "
            f"(from texture_rel='{texture_rel}', model_dir='{model_dir}')"
        )
    return resolved


def material_cfg_from_yaml(cfg, variant=None):
    """Resolve a material YAML spec to per-prim properties for one variant.

    The mapping includes the shader name, an optional RGB diffuse color,
    and any relative albedo texture, roughness, and metallic values.

    Args:
        cfg: A loaded material config (from ``load_material_config``).
        variant: Variant name to resolve in variant mode; ``None`` uses
            ``default_variant``. Ignored in single-material mode.

    Returns:
        ``{prim_path: {"shader": str, "diffuse_color": (r,g,b)?, ...}}``.

    Raises:
        ValueError: If ``variant`` is unknown (via
            ``get_prim_material_map``).
    """
    prim_map = get_prim_material_map(cfg, variant=variant)

    spawn_cfg = {}
    for prim_path, props in prim_map.items():
        entry = {"shader": props["shader"]}
        if "diffuse_color" in props:
            entry["diffuse_color"] = tuple(
                float(c) for c in props["diffuse_color"]
            )
        for key in ("albedo_texture", "roughness", "metallic"):
            if key in props:
                value = props[key]
                if key in ("roughness", "metallic"):
                    value = float(value)
                entry[key] = value
        spawn_cfg[prim_path] = entry
    return spawn_cfg


def _validate(cfg, source):
    """Validate material config structure."""
    has_variants = "variants" in cfg
    has_materials = "materials" in cfg

    if not has_variants and not has_materials:
        raise ValueError(
            f"{source}: needs either 'variants' or 'materials' top-level key"
        )

    if has_variants:
        _validate_variants(cfg, source)
    if has_materials:
        _validate_materials(cfg, source)


def _validate_variants(cfg, source):
    variants = cfg["variants"]
    if not variants:
        raise ValueError(f"{source}: variants is empty")

    if "default_variant" not in cfg:
        raise ValueError(f"{source}: variant mode requires 'default_variant'")

    default = cfg["default_variant"]
    if default not in variants:
        raise ValueError(
            f"{source}: default_variant '{default}' not in "
            f"{sorted(variants.keys())}"
        )

    for vname, prim_map in variants.items():
        for prim_path, mat_props in prim_map.items():
            if "shader" not in mat_props:
                raise ValueError(
                    f"{source}: variants.{vname}.{prim_path} needs 'shader'"
                )


def _validate_materials(cfg, source):
    for prim_path, mat_props in cfg["materials"].items():
        if "shader" not in mat_props:
            raise ValueError(
                f"{source}: materials.{prim_path} needs 'shader'"
            )
