"""Author a compliant construction-entry USD scene in Isaac Sim.

Run headlessly with Isaac Sim's Python from the repository root:

    /home/oedeh/isaacsim/python.sh simulation/author_construction_entry_compliant.py

Outputs:
    output/construction_entry_compliant.usd
    output/construction_entry_compliant.png
"""

from __future__ import annotations

import math
import shutil
from pathlib import Path

from isaacsim import SimulationApp

simulation_app = SimulationApp(
    {
        "headless": True,
        "width": 1920,
        "height": 1080,
        "renderer": "RaytracedLighting",
        "sync_loads": True,
    }
)

# Import Omniverse and Isaac APIs after SimulationApp is created.
import carb  # noqa: E402
import omni.usd  # noqa: E402
from omni.isaac.core import World  # noqa: E402
from omni.isaac.core.utils.prims import delete_prim, is_prim_path_valid  # noqa: E402
from omni.isaac.core.utils.stage import add_reference_to_stage, save_stage  # noqa: E402
from omni.isaac.nucleus import get_assets_root_path, is_file  # noqa: E402
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdShade  # noqa: E402

# Replicator is used only for the required thumbnail render.
import omni.replicator.core as rep  # noqa: E402
from PIL import Image  # noqa: E402

OUTPUT_DIR = Path("output")
STAGE_PATH = OUTPUT_DIR / "construction_entry_compliant.usd"
THUMBNAIL_PATH = OUTPUT_DIR / "construction_entry_compliant.png"
CAMERA_PATH = "/World/SecurityCam"
GATE_PATH = "/World/SouthEntryGate"
WORKER_PATH = "/World/Worker"

PRINTED_PATHS: dict[str, str] = {}


def main() -> None:
    """Build, save, render, and report the requested scene."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _remove_previous_thumbnail_output()

    try:
        world = World(stage_units_in_meters=1.0)
        stage = omni.usd.get_context().get_stage()
        assets_root = get_assets_root_path()
        if not assets_root:
            raise RuntimeError("Could not resolve Isaac Sim assets root from Nucleus")

        _clear_world(stage)
        _set_stage_metadata(stage)
        _author_environment(stage, assets_root)
        _author_props(stage, assets_root)
        _author_lighting(stage, assets_root)
        _author_worker(stage, assets_root)
        _author_security_camera(stage)

        # Step once so referenced assets and authored transforms are realized before save/render.
        world.initialize_physics()
        for _ in range(5):
            world.step(render=True)

        save_stage(str(STAGE_PATH), save_and_reload_in_place=False)
        _render_thumbnail()
        _print_required_paths()
    finally:
        simulation_app.close()


# ----------------------------- Stage lifecycle -----------------------------


def _clear_world(stage: Usd.Stage) -> None:
    """Make the script idempotent by removing /World before authoring."""
    if is_prim_path_valid("/World"):
        delete_prim("/World")
    UsdGeom.Xform.Define(stage, "/World")


def _set_stage_metadata(stage: Usd.Stage) -> None:
    """Configure stage units, up-axis, and playback duration."""
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    stage.SetStartTimeCode(0)
    stage.SetEndTimeCode(240)
    stage.SetTimeCodesPerSecond(24)
    stage.SetFramesPerSecond(24)


# ----------------------------- Asset utilities -----------------------------


def _asset(assets_root: str, relative_path: str) -> str:
    return assets_root.rstrip("/") + relative_path


def _first_existing_asset(assets_root: str, relative_paths: list[str]) -> str | None:
    for relative_path in relative_paths:
        candidate = _asset(assets_root, relative_path)
        try:
            if is_file(candidate):
                return candidate
        except Exception:
            carb.log_warn(f"Could not check asset path: {candidate}")
    return None


def _reference_if_available(
    assets_root: str,
    candidates: list[str],
    prim_path: str,
    translate: tuple[float, float, float],
    rotate_xyz: tuple[float, float, float] = (0, 0, 0),
    scale: tuple[float, float, float] = (1, 1, 1),
) -> bool:
    asset_path = _first_existing_asset(assets_root, candidates)
    if not asset_path:
        return False
    add_reference_to_stage(asset_path, prim_path)
    _set_xform(prim_path, translate, rotate_xyz, scale)
    return True


# ----------------------------- Environment -----------------------------


def _author_environment(stage: Usd.Stage, assets_root: str) -> None:
    """Reference a warehouse if available; otherwise build a concrete slab and fence gate."""
    env_loaded = _reference_if_available(
        assets_root,
        [
            "/Isaac/Environments/Simple_Warehouse/warehouse.usd",
            "/Isaac/Environments/Simple_Warehouse/full_warehouse.usd",
            "/Isaac/Environments/Simple_Warehouse/simple_warehouse.usd",
            "/Isaac/Environments/Grid/default_environment.usd",
        ],
        "/World/Environment",
        (0, 8, 0),
        (0, 0, 0),
        (1, 1, 1),
    )
    if not env_loaded:
        _build_concrete_slab_and_fence(stage)
    else:
        _build_gate(stage)
        _add_concrete_slab(stage)


def _build_concrete_slab_and_fence(stage: Usd.Stage) -> None:
    """Fallback facility shell: 30m slab and two fence segments with a south entry gate."""
    _add_concrete_slab(stage)
    _build_gate(stage)
    _cube(
        "/World/NorthFence", (0, 15, 1.25), (30, 0.08, 2.5), _mat("FenceMetal", (0.45, 0.48, 0.48))
    )
    _cube(
        "/World/WestFence", (-15, 0, 1.25), (0.08, 30, 2.5), _mat("FenceMetal", (0.45, 0.48, 0.48))
    )
    _cube(
        "/World/EastFence", (15, 0, 1.25), (0.08, 30, 2.5), _mat("FenceMetal", (0.45, 0.48, 0.48))
    )


def _add_concrete_slab(stage: Usd.Stage) -> None:
    _cube("/World/ConcreteSlab", (0, 0, -0.05), (30, 30, 0.1), _mat("Concrete", (0.42, 0.42, 0.4)))


def _build_gate(stage: Usd.Stage) -> None:
    """Create two chain-link style fence segments with a clear gate opening at south edge."""
    fence_mat = _mat("ChainLinkFence", (0.55, 0.57, 0.58), metallic=0.6, roughness=0.35)
    _cube(f"{GATE_PATH}/LeftFenceSegment", (-9, -15, 1.2), (12, 0.08, 2.4), fence_mat)
    _cube(f"{GATE_PATH}/RightFenceSegment", (9, -15, 1.2), (12, 0.08, 2.4), fence_mat)
    _cube(f"{GATE_PATH}/LeftPost", (-3, -15, 1.4), (0.18, 0.18, 2.8), fence_mat)
    _cube(f"{GATE_PATH}/RightPost", (3, -15, 1.4), (0.18, 0.18, 2.8), fence_mat)
    _cube(f"{GATE_PATH}/TopRailLeft", (-9, -15, 2.45), (12, 0.12, 0.08), fence_mat)
    _cube(f"{GATE_PATH}/TopRailRight", (9, -15, 2.45), (12, 0.12, 0.08), fence_mat)
    PRINTED_PATHS["gate"] = GATE_PATH


# ----------------------------- Props -----------------------------


def _author_props(stage: Usd.Stage, assets_root: str) -> None:
    """Add construction props around the gate and inside the facility."""
    _reference_if_available(
        assets_root,
        [
            "/Isaac/Props/Forklift/forklift.usd",
            "/Isaac/Props/Forklift/Forklift.usd",
            "/Isaac/Props/Vehicles/Forklift/forklift.usd",
        ],
        "/World/Props/Forklift",
        (7, -4, 0),
        (0, 0, 145),
        (1, 1, 1),
    ) or _fallback_forklift()

    _reference_if_available(
        assets_root,
        [
            "/Isaac/Props/Construction/TrafficCone/traffic_cone.usd",
            "/Isaac/Props/TrafficCone/traffic_cone.usd",
            "/Isaac/Props/Traffic_Cone/traffic_cone.usd",
        ],
        "/World/Props/TrafficConeLeft",
        (-3.8, -15.2, 0.0),
        (0, 0, 0),
        (1, 1, 1),
    ) or _cone("/World/Props/TrafficConeLeft", (-3.8, -15.2, 0.0))
    _reference_if_available(
        assets_root,
        [
            "/Isaac/Props/Construction/TrafficCone/traffic_cone.usd",
            "/Isaac/Props/TrafficCone/traffic_cone.usd",
            "/Isaac/Props/Traffic_Cone/traffic_cone.usd",
        ],
        "/World/Props/TrafficConeRight",
        (3.8, -15.2, 0.0),
        (0, 0, 0),
        (1, 1, 1),
    ) or _cone("/World/Props/TrafficConeRight", (3.8, -15.2, 0.0))

    _pallet_stack("/World/Props/CinderBlockPallets", (-6, -5, 0))
    _scaffolding_stack("/World/Props/ScaffoldingStack", (-8, 0, 0))
    _ppe_required_sign(stage)


def _fallback_forklift() -> None:
    forklift_mat = _mat("ForkliftYellow", (1.0, 0.72, 0.05))
    dark_mat = _mat("ForkliftDark", (0.05, 0.05, 0.05))
    _cube("/World/Props/Forklift/Body", (7, -4, 0.6), (1.6, 0.9, 0.8), forklift_mat)
    _cube("/World/Props/Forklift/Mast", (6.25, -4, 1.3), (0.12, 0.9, 1.8), dark_mat)
    _cube("/World/Props/Forklift/ForkLeft", (5.55, -4.25, 0.18), (1.2, 0.08, 0.08), dark_mat)
    _cube("/World/Props/Forklift/ForkRight", (5.55, -3.75, 0.18), (1.2, 0.08, 0.08), dark_mat)


def _cone(path: str, translate: tuple[float, float, float]) -> None:
    orange = _mat("ConeOrange", (1.0, 0.32, 0.02))
    white = _mat("ConeWhite", (0.95, 0.95, 0.9))
    _cube(f"{path}/Base", (translate[0], translate[1], 0.05), (0.7, 0.7, 0.1), orange)
    _cube(f"{path}/Body", (translate[0], translate[1], 0.45), (0.32, 0.32, 0.8), orange)
    _cube(f"{path}/ReflectiveBand", (translate[0], translate[1], 0.62), (0.36, 0.34, 0.08), white)


def _pallet_stack(path: str, translate: tuple[float, float, float]) -> None:
    block_mat = _mat("CinderBlocks", (0.45, 0.45, 0.43))
    wood_mat = _mat("PalletWood", (0.42, 0.25, 0.12))
    _cube(f"{path}/Pallet", (translate[0], translate[1], 0.1), (2.2, 1.2, 0.2), wood_mat)
    for row in range(3):
        for col in range(4):
            _cube(
                f"{path}/Block_{row}_{col}",
                (translate[0] - 0.75 + col * 0.5, translate[1] - 0.35 + row * 0.35, 0.35),
                (0.42, 0.22, 0.22),
                block_mat,
            )


def _scaffolding_stack(path: str, translate: tuple[float, float, float]) -> None:
    metal = _mat("ScaffoldMetal", (0.65, 0.66, 0.62), metallic=0.7, roughness=0.25)
    for level in range(3):
        z = translate[2] + 0.45 + level * 0.55
        _cube(f"{path}/RailA_{level}", (translate[0], translate[1], z), (2.4, 0.06, 0.06), metal)
        _cube(
            f"{path}/RailB_{level}", (translate[0], translate[1] + 0.9, z), (2.4, 0.06, 0.06), metal
        )
        _cube(
            f"{path}/PostL_{level}",
            (translate[0] - 1.2, translate[1] + 0.45, z),
            (0.06, 0.06, 0.5),
            metal,
        )
        _cube(
            f"{path}/PostR_{level}",
            (translate[0] + 1.2, translate[1] + 0.45, z),
            (0.06, 0.06, 0.5),
            metal,
        )


def _ppe_required_sign(stage: Usd.Stage) -> None:
    sign_mat = _mat("SignYellow", (1.0, 0.88, 0.05))
    text_mat = _mat("SignTextBlack", (0.02, 0.02, 0.02))
    _cube("/World/Props/PPERequiredSign/Panel", (0, -15.12, 1.55), (2.8, 0.06, 0.75), sign_mat)
    text = UsdGeom.Mesh.Define(stage, "/World/Props/PPERequiredSign/TextPlaceholder")
    # Use simple black bars so the warning remains visible even without font/text extensions.
    _cube("/World/Props/PPERequiredSign/TextLine1", (0, -15.17, 1.72), (2.2, 0.03, 0.05), text_mat)
    _cube("/World/Props/PPERequiredSign/TextLine2", (0, -15.17, 1.55), (2.4, 0.03, 0.05), text_mat)
    _cube("/World/Props/PPERequiredSign/TextLine3", (0, -15.17, 1.38), (2.0, 0.03, 0.05), text_mat)
    text.GetPrim().CreateAttribute("user:label", Sdf.ValueTypeNames.String).Set(
        "PPE REQUIRED BEYOND THIS POINT"
    )


# ----------------------------- Lighting -----------------------------


def _author_lighting(stage: Usd.Stage, assets_root: str) -> None:
    """Add warm sun and daytime ambient dome lighting."""
    sun = UsdLux.DistantLight.Define(stage, "/World/Sun")
    sun.CreateIntensityAttr(3500.0)
    sun.CreateColorTemperatureAttr(5200.0)
    sun.CreateEnableColorTemperatureAttr(True)
    UsdGeom.XformCommonAPI(sun).SetRotate((-45, 0, -135), UsdGeom.XformCommonAPI.RotationOrderXYZ)

    dome = UsdLux.DomeLight.Define(stage, "/World/DaytimeDome")
    dome.CreateIntensityAttr(650.0)
    hdr = _first_existing_asset(
        assets_root,
        [
            "/NVIDIA/Assets/Skies/Clear/noon_grass_4k.hdr",
            "/NVIDIA/Assets/Skies/Cloudy/champagne_castle_1_4k.hdr",
            "/NVIDIA/Assets/Skies/Dynamic/ClearSky.hdr",
        ],
    )
    if hdr:
        dome.CreateTextureFileAttr(hdr)


# ----------------------------- Character and PPE -----------------------------


def _author_worker(stage: Usd.Stage, assets_root: str) -> None:
    """Reference a construction male character when available and add clear PPE geometry."""
    worker_asset = _first_existing_asset(
        assets_root,
        [
            "/Isaac/People/Characters/original_male_adult_construction_05/original_male_adult_construction_05.usd",
            "/Isaac/People/Characters/original_male_adult_construction_05.usd",
            "/Isaac/People/Characters/male_adult_construction_05/male_adult_construction_05.usd",
            "/Isaac/People/Characters/original_male_adult_business_02/original_male_adult_business_02.usd",
        ],
    )
    if worker_asset:
        add_reference_to_stage(worker_asset, WORKER_PATH)
        _set_xform(WORKER_PATH, (0, -23, 0), (0, 0, 0), (1, 1, 1))
    else:
        _fallback_worker_body()
    PRINTED_PATHS["worker"] = WORKER_PATH

    _animate_worker_walk(stage)
    _author_ppe_items()


def _fallback_worker_body() -> None:
    clothes = _mat("WorkerClothes", (0.1, 0.12, 0.15))
    skin = _mat("WorkerSkin", (0.68, 0.48, 0.34))
    _cube(f"{WORKER_PATH}/Torso", (0, -23, 0.95), (0.42, 0.25, 0.65), clothes)
    _sphere(f"{WORKER_PATH}/Head", (0, -23, 1.68), (0.22, 0.22, 0.22), skin)
    _cube(f"{WORKER_PATH}/LeftLeg", (-0.14, -23, 0.35), (0.11, 0.11, 0.55), clothes)
    _cube(f"{WORKER_PATH}/RightLeg", (0.14, -23, 0.35), (0.11, 0.11, 0.55), clothes)
    _cube(f"{WORKER_PATH}/LeftArm", (-0.42, -23, 1.02), (0.08, 0.08, 0.5), skin)
    _cube(f"{WORKER_PATH}/RightArm", (0.42, -23, 1.02), (0.08, 0.08, 0.5), skin)


def _animate_worker_walk(stage: Usd.Stage) -> None:
    """Animate the worker north through the gate at about 1.3 m/s for 10 seconds."""
    prim = stage.GetPrimAtPath(WORKER_PATH)
    xform = UsdGeom.Xformable(prim)
    translate_op = _get_or_add_translate_op(xform)
    translate_op.Set(Gf.Vec3d(0, -23, 0), 0)
    translate_op.Set(Gf.Vec3d(0, -10, 0), 240)
    prim.CreateAttribute("user:animation", Sdf.ValueTypeNames.String).Set(
        "Walk north at approximately 1.3 m/s for 10 seconds. Use bundled walk clip or AnimationGraph if available."
    )


def _author_ppe_items() -> None:
    vest = _mat("HiVisOrangeVest", (1.0, 0.36, 0.02))
    reflective = _mat("ReflectiveStripe", (0.85, 1.0, 0.3))
    helmet = _mat("YellowHardHat", (1.0, 0.86, 0.02))
    glasses = _mat("ClearSafetyGlasses", (0.7, 0.95, 1.0), opacity=0.35)
    gloves = _mat("WorkGloves", (0.12, 0.1, 0.08))
    boots = _mat("SteelToeBoots", (0.03, 0.03, 0.035))

    _cube(f"{WORKER_PATH}/PPE/SafetyVest", (0, -23.03, 1.05), (0.48, 0.08, 0.55), vest)
    _cube(
        f"{WORKER_PATH}/PPE/ReflectiveStripeLeft",
        (-0.14, -23.08, 1.07),
        (0.05, 0.04, 0.55),
        reflective,
    )
    _cube(
        f"{WORKER_PATH}/PPE/ReflectiveStripeRight",
        (0.14, -23.08, 1.07),
        (0.05, 0.04, 0.55),
        reflective,
    )
    _sphere(f"{WORKER_PATH}/PPE/HardHat", (0, -23, 1.9), (0.27, 0.23, 0.09), helmet)
    _cube(f"{WORKER_PATH}/PPE/SafetyGlasses", (0, -23.18, 1.7), (0.32, 0.035, 0.06), glasses)
    _cube(f"{WORKER_PATH}/PPE/LeftGlove", (-0.46, -23, 0.8), (0.12, 0.1, 0.12), gloves)
    _cube(f"{WORKER_PATH}/PPE/RightGlove", (0.46, -23, 0.8), (0.12, 0.1, 0.12), gloves)
    _cube(f"{WORKER_PATH}/PPE/LeftBoot", (-0.14, -23.05, 0.08), (0.18, 0.28, 0.13), boots)
    _cube(f"{WORKER_PATH}/PPE/RightBoot", (0.14, -23.05, 0.08), (0.18, 0.28, 0.13), boots)

    PRINTED_PATHS.update(
        {
            "hard_hat": f"{WORKER_PATH}/PPE/HardHat",
            "safety_vest": f"{WORKER_PATH}/PPE/SafetyVest",
            "safety_glasses": f"{WORKER_PATH}/PPE/SafetyGlasses",
            "left_glove": f"{WORKER_PATH}/PPE/LeftGlove",
            "right_glove": f"{WORKER_PATH}/PPE/RightGlove",
            "left_boot": f"{WORKER_PATH}/PPE/LeftBoot",
            "right_boot": f"{WORKER_PATH}/PPE/RightBoot",
        }
    )


# ----------------------------- Camera and thumbnail -----------------------------


def _author_security_camera(stage: Usd.Stage) -> None:
    """Create the security camera inside the facility looking back toward the gate."""
    camera = UsdGeom.Camera.Define(stage, CAMERA_PATH)
    camera.CreateFocalLengthAttr(24.0)
    camera.CreateFocusDistanceAttr(6.0)
    camera.CreateFStopAttr(5.6)
    camera.CreateClippingRangeAttr(Gf.Vec2f(0.1, 1000.0))
    _look_at(CAMERA_PATH, Gf.Vec3d(1.5, -11.0, 3.0), Gf.Vec3d(0.0, -17.0, 1.45))
    stage.SetDefaultPrim(stage.GetPrimAtPath("/World"))
    stage.GetRootLayer().defaultPrim = "World"
    stage.GetPrimAtPath(CAMERA_PATH).CreateAttribute(
        "user:defaultRenderCamera", Sdf.ValueTypeNames.Bool
    ).Set(True)
    PRINTED_PATHS["camera"] = CAMERA_PATH


def _render_thumbnail() -> None:
    """Render a 1920x1080 RGB thumbnail from /World/SecurityCam at the walk midpoint."""
    stage = omni.usd.get_context().get_stage()
    worker = stage.GetPrimAtPath(WORKER_PATH)
    if worker.IsValid():
        _get_or_add_translate_op(UsdGeom.Xformable(worker)).Set(Gf.Vec3d(0, -16.5, 0))

    render_product = rep.create.render_product(CAMERA_PATH, (1920, 1080))
    annotator = rep.AnnotatorRegistry.get_annotator("rgb")
    annotator.attach(render_product)
    for _ in range(3):
        rep.orchestrator.step(rt_subframes=16)
    rgb = annotator.get_data()
    annotator.detach()
    render_product.destroy()
    rep.orchestrator.wait_until_complete()

    if rgb is None or len(rgb.shape) < 3:
        raise RuntimeError("RGB annotator did not return image data")
    Image.fromarray(rgb[:, :, :3]).save(THUMBNAIL_PATH)


# ----------------------------- Geometry helpers -----------------------------


def _mat(
    name: str,
    color: tuple[float, float, float],
    metallic: float = 0.0,
    roughness: float = 0.55,
    opacity: float = 1.0,
):
    stage = omni.usd.get_context().get_stage()
    path = f"/World/Materials/{name}"
    material = UsdShade.Material.Define(stage, path)
    shader = UsdShade.Shader.Define(stage, f"{path}/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(color)
    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(metallic)
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(roughness)
    shader.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(opacity)
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    return material


def _bind(prim, material) -> None:
    UsdShade.MaterialBindingAPI(prim).Bind(material)


def _cube(path: str, translate, scale, material) -> None:
    stage = omni.usd.get_context().get_stage()
    cube = UsdGeom.Cube.Define(stage, path)
    _set_xform(path, translate, (0, 0, 0), scale)
    _bind(cube.GetPrim(), material)


def _sphere(path: str, translate, scale, material) -> None:
    stage = omni.usd.get_context().get_stage()
    sphere = UsdGeom.Sphere.Define(stage, path)
    _set_xform(path, translate, (0, 0, 0), scale)
    _bind(sphere.GetPrim(), material)


def _set_xform(
    prim_path: str,
    translate: tuple[float, float, float],
    rotate_xyz: tuple[float, float, float],
    scale: tuple[float, float, float],
) -> None:
    stage = omni.usd.get_context().get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    xform = UsdGeom.Xformable(prim)
    _get_or_add_translate_op(xform).Set(Gf.Vec3d(*translate))
    _get_or_add_rotate_op(xform).Set(Gf.Vec3f(*rotate_xyz))
    _get_or_add_scale_op(xform).Set(Gf.Vec3f(*scale))


def _get_or_add_translate_op(xform: UsdGeom.Xformable):
    for op in xform.GetOrderedXformOps():
        if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
            return op
    return xform.AddTranslateOp()


def _get_or_add_rotate_op(xform: UsdGeom.Xformable):
    for op in xform.GetOrderedXformOps():
        if op.GetOpType() == UsdGeom.XformOp.TypeRotateXYZ:
            return op
    return xform.AddRotateXYZOp()


def _get_or_add_scale_op(xform: UsdGeom.Xformable):
    for op in xform.GetOrderedXformOps():
        if op.GetOpType() == UsdGeom.XformOp.TypeScale:
            return op
    return xform.AddScaleOp()


def _look_at(prim_path: str, eye: Gf.Vec3d, target: Gf.Vec3d) -> None:
    stage = omni.usd.get_context().get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    direction = (target - eye).GetNormalized()
    yaw = math.degrees(math.atan2(direction[0], direction[1]))
    horizontal = math.sqrt(direction[0] ** 2 + direction[1] ** 2)
    pitch = -math.degrees(math.atan2(direction[2], horizontal))
    xform = UsdGeom.XformCommonAPI(prim)
    xform.SetTranslate(eye)
    xform.SetRotate((pitch, 0, -yaw), UsdGeom.XformCommonAPI.RotationOrderXYZ)


def _remove_previous_thumbnail_output() -> None:
    if THUMBNAIL_PATH.exists():
        THUMBNAIL_PATH.unlink()
    writer_dir = OUTPUT_DIR / "_thumbnail_writer"
    if writer_dir.exists():
        shutil.rmtree(writer_dir)


def _print_required_paths() -> None:
    print(f"stage={STAGE_PATH}")
    print(f"thumbnail={THUMBNAIL_PATH}")
    for label, path in PRINTED_PATHS.items():
        print(f"{label}={path}")


if __name__ == "__main__":
    main()
