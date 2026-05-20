"""Generate Omniverse/Isaac Sim PPE test frames.

Run with Isaac Sim's Python, not the project venv Python:

    /home/oedeh/isaacsim/python.sh simulation/omniverse_ppe_world.py \
      --scenario person-no-ppe \
      --frames 30 \
      --output-dir artifacts/omniverse/person_no_ppe

Then convert frames to video with ffmpeg and feed that video to edge.worker.
"""

from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render PPE test scenes with Isaac Sim/Omniverse.")
    parser.add_argument(
        "--scenario",
        choices=["no-person", "person-ppe", "person-no-ppe", "cycle"],
        default="person-no-ppe",
        help="Scene condition to render.",
    )
    parser.add_argument("--frames", type=int, default=30, help="Number of RGB frames to render.")
    parser.add_argument(
        "--output-dir",
        default="artifacts/omniverse/ppe_test",
        help="Directory for rendered RGB frames.",
    )
    parser.add_argument("--width", type=int, default=1280, help="Render width.")
    parser.add_argument("--height", type=int, default=720, help="Render height.")
    parser.add_argument(
        "--show", action="store_true", help="Open the Isaac UI instead of headless mode."
    )
    parser.add_argument(
        "--keep-output",
        action="store_true",
        help="Do not remove existing output before rendering.",
    )
    parser.add_argument(
        "--hold-seconds",
        type=float,
        default=30.0,
        help="When --show is used, keep the Isaac window open this many seconds after rendering.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    output_dir = Path(args.output_dir)
    if output_dir.exists() and not args.keep_output:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    from isaacsim import SimulationApp

    simulation_app = SimulationApp({"headless": not args.show})
    try:
        render(args, output_dir)
        if args.show and args.hold_seconds > 0:
            print(
                f"Holding Isaac Sim window open for {args.hold_seconds:.0f}s. Press Ctrl+C to close sooner."
            )
            deadline = time.monotonic() + args.hold_seconds
            while time.monotonic() < deadline:
                simulation_app.update()
                time.sleep(1 / 30)
    finally:
        simulation_app.close()


def render(args: argparse.Namespace, output_dir: Path) -> None:
    import carb.settings
    import omni.replicator.core as rep
    import omni.usd
    from pxr import Gf, Sdf, UsdGeom

    omni.usd.get_context().new_stage()
    rep.orchestrator.set_capture_on_play(False)
    carb.settings.get_settings().set("rtx/post/dlss/execMode", 2)

    stage = omni.usd.get_context().get_stage()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)

    materials = {
        "floor": _material(stage, "/World/Materials/Floor", (0.35, 0.37, 0.38)),
        "robot": _material(stage, "/World/Materials/Robot", (0.1, 0.25, 0.9)),
        "skin": _material(stage, "/World/Materials/Skin", (0.72, 0.52, 0.38)),
        "clothes": _material(stage, "/World/Materials/Clothes", (0.12, 0.16, 0.18)),
        "vest": _material(stage, "/World/Materials/SafetyVest", (1.0, 0.48, 0.02)),
        "helmet": _material(stage, "/World/Materials/HardHat", (1.0, 0.88, 0.05)),
        "hazard": _material(stage, "/World/Materials/Hazard", (1.0, 0.78, 0.0)),
    }

    _light(stage, Sdf)
    _cube(stage, "/World/Floor", (0, 0, -0.05), (5.5, 4.0, 0.08), materials["floor"])
    _cube(stage, "/World/BackWall", (0, 1.9, 1.0), (5.5, 0.08, 1.1), materials["floor"])
    _cube(stage, "/World/RobotBase", (1.5, 0.5, 0.25), (0.45, 0.45, 0.5), materials["robot"])
    _cube(stage, "/World/RobotArm", (1.0, 0.5, 1.0), (1.0, 0.12, 0.18), materials["robot"])
    _cube(stage, "/World/HazardZone", (0, 0, 0.02), (2.5, 2.0, 0.03), materials["hazard"])

    camera = rep.create.camera(
        position=(3.2, -4.0, 2.3), look_at=(-0.45, 0.0, 1.0), focal_length=28
    )
    render_product = rep.create.render_product(camera, (args.width, args.height))
    writer = rep.writers.get("BasicWriter")
    writer.initialize(output_dir=str(output_dir), rgb=True)
    writer.attach(render_product)

    for frame_index in range(args.frames):
        scenario = _scenario_for_frame(args.scenario, frame_index)
        _set_worker(stage, materials, scenario, frame_index, Gf)
        rep.orchestrator.step(rt_subframes=8)

    writer.detach()
    render_product.destroy()
    rep.orchestrator.wait_until_complete()
    print(f"rendered_frames={len(list(output_dir.rglob('*.png')))} output_dir={output_dir}")


def _scenario_for_frame(scenario: str, frame_index: int) -> str:
    if scenario != "cycle":
        return scenario
    states = ("no-person", "person-no-ppe", "person-ppe")
    return states[(frame_index // 10) % len(states)]


def _material(stage, path: str, color: tuple[float, float, float]):
    from pxr import Sdf, UsdShade

    material = UsdShade.Material.Define(stage, path)
    shader = UsdShade.Shader.Define(stage, f"{path}/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(color)
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.55)
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    return material


def _bind(prim, material) -> None:
    from pxr import UsdShade

    UsdShade.MaterialBindingAPI(prim).Bind(material)


def _cube(stage, path: str, translate, scale, material) -> None:
    from pxr import UsdGeom

    cube = UsdGeom.Cube.Define(stage, path)
    UsdGeom.XformCommonAPI(cube).SetTranslate(translate)
    UsdGeom.XformCommonAPI(cube).SetScale(scale)
    _bind(cube.GetPrim(), material)


def _sphere(stage, path: str, translate, scale, material) -> None:
    from pxr import UsdGeom

    sphere = UsdGeom.Sphere.Define(stage, path)
    UsdGeom.XformCommonAPI(sphere).SetTranslate(translate)
    UsdGeom.XformCommonAPI(sphere).SetScale(scale)
    _bind(sphere.GetPrim(), material)


def _light(stage, Sdf) -> None:
    dome_light = stage.DefinePrim("/World/DomeLight", "DomeLight")
    dome_light.CreateAttribute("inputs:intensity", Sdf.ValueTypeNames.Float).Set(550.0)
    key_light = stage.DefinePrim("/World/KeyLight", "DistantLight")
    key_light.CreateAttribute("inputs:intensity", Sdf.ValueTypeNames.Float).Set(900.0)


def _set_worker(stage, materials, scenario: str, frame_index: int, Gf) -> None:
    worker_root = stage.GetPrimAtPath("/World/Worker")
    if worker_root.IsValid():
        stage.RemovePrim("/World/Worker")
    if scenario == "no-person":
        return

    x = -0.6 + 0.01 * (frame_index % 20)
    _cube(stage, "/World/Worker/Torso", (x, 0, 0.9), (0.36, 0.24, 0.62), materials["clothes"])
    _sphere(stage, "/World/Worker/Head", (x, 0, 1.62), (0.23, 0.23, 0.23), materials["skin"])
    _cube(
        stage, "/World/Worker/LeftLeg", (x - 0.12, 0, 0.32), (0.1, 0.1, 0.48), materials["clothes"]
    )
    _cube(
        stage,
        "/World/Worker/RightLeg",
        (x + 0.12, 0, 0.32),
        (0.1, 0.1, 0.48),
        materials["clothes"],
    )
    _cube(
        stage, "/World/Worker/LeftArm", (x - 0.42, 0, 0.98), (0.08, 0.08, 0.48), materials["skin"]
    )
    _cube(
        stage, "/World/Worker/RightArm", (x + 0.42, 0, 0.98), (0.08, 0.08, 0.48), materials["skin"]
    )

    if scenario == "person-ppe":
        _cube(
            stage,
            "/World/Worker/SafetyVest",
            (x, -0.01, 0.95),
            (0.42, 0.06, 0.52),
            materials["vest"],
        )
        _sphere(
            stage, "/World/Worker/HardHat", (x, 0, 1.82), (0.26, 0.26, 0.1), materials["helmet"]
        )


if __name__ == "__main__":
    main()
