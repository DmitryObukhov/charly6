import pytest
import yaml

from worlds import linear


def test_default_config_is_valid_yaml():
    cfg = yaml.safe_load(linear.GetDefaultConfig())

    assert isinstance(cfg, dict)
    assert "simulation" not in cfg
    assert cfg["world"]["base"] == "worlds/linear.py"
    assert cfg["world"]["dt"] == 0.1


def test_init_accepts_default_config():
    linear.Init(linear.GetDefaultConfig())

    params = linear.GetParams()
    assert params["x"] == "0.0"


def test_validate_reports_problems():
    ok, problems = linear.Validate(linear.GetDefaultConfig())

    assert ok is True
    assert problems == []

    ok, problems = linear.Validate("world: {}\n")

    assert ok is False
    assert problems


def test_process_returns_float_values():
    linear.Init(linear.GetDefaultConfig())

    outputs = linear.Process({"left_motor": 0.0, "right_motor": 1.0})

    assert set(outputs) == {"velocity", "hunger", "light"}
    assert all(isinstance(value, float) for value in outputs.values())


def test_first_process_accepts_none_without_advancing():
    linear.Init(linear.GetDefaultConfig())

    outputs = linear.Process(None)

    assert set(outputs) == {"velocity", "hunger", "light"}
    assert linear.GetParams()["step"] == "0"


def test_outputs_accept_name_to_source_mapping():
    config = linear.GetDefaultConfig().replace(
        "outputs:\n"
        "  velocity: velocity\n"
        "  hunger: hunger\n"
        "  light: lightness\n",
        "outputs:\n"
        "  agent_speed: velocity\n"
        "  wall: right_wall\n",
    )
    linear.Init(config)

    outputs = linear.Process({"left_motor": 0.0, "right_motor": 1.0})

    assert set(outputs) == {"agent_speed", "wall"}
    assert isinstance(outputs["agent_speed"], float)


def test_legacy_top_level_simulation_section_still_loads():
    config = linear.GetDefaultConfig().replace(
        "world:\n"
        "  base: worlds/linear.py\n"
        "  dt: 0.1\n"
        "  seed: 42\n"
        "  input_validation: strict\n"
        "  max_steps: null\n",
        "simulation:\n"
        "  base: worlds/linear.py\n"
        "  dt: 0.1\n"
        "  seed: 42\n"
        "  input_validation: strict\n"
        "  max_steps: null\n"
        "\n"
        "world:\n",
    )
    linear.Init(config)

    linear.Process({"left_motor": 0.0, "right_motor": 1.0})

    assert float(linear.GetParams()["x"]) > 0.0


def test_same_inputs_are_deterministic_after_reinit():
    inputs = [{"left_motor": 0.0, "right_motor": 1.0} for _ in range(3)]

    linear.Init(linear.GetDefaultConfig())
    first = [linear.Process(item) for item in inputs]

    linear.Init(linear.GetDefaultConfig())
    second = [linear.Process(item) for item in inputs]

    assert first == second


def test_strict_mode_rejects_out_of_range_input():
    linear.Init(linear.GetDefaultConfig())

    with pytest.raises(ValueError, match="right_motor"):
        linear.Process({"left_motor": 0.0, "right_motor": 2.0})


def test_agent_moves_right_and_left():
    linear.Init(linear.GetDefaultConfig())

    linear.Process({"left_motor": 0.0, "right_motor": 1.0})
    right_x = float(linear.GetParams()["x"])
    assert right_x > 0.0

    for _ in range(10):
        linear.Process({"left_motor": 1.0, "right_motor": 0.0})

    assert float(linear.GetParams()["x"]) < right_x


def test_stomach_and_light_outputs_are_computed():
    linear.Init(linear.GetDefaultConfig())

    first = linear.Process({"left_motor": 0.0, "right_motor": 0.0})
    second = linear.Process({"left_motor": 0.0, "right_motor": 0.0})

    assert first["hunger"] > 0.0
    assert second["hunger"] > first["hunger"]
    assert first["light"] > 0.0
    assert 0.0 < float(linear.GetParams()["stomach_content"]) <= 10.0


def test_visualization_returns_image():
    linear.Init(linear.GetDefaultConfig())

    image = linear.GetVisualization((80, 20))

    assert image.width == 80
    assert image.height == 20
    assert image.to_ppm().startswith(b"P6\n80 20\n255\n")
