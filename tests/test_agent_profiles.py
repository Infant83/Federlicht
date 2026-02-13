import json
from pathlib import Path

from federnett.agent_profiles import list_agent_profiles, save_agent_profile
from federlicht import profiles as core_profiles


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_save_agent_profile_normalizes_apply_to(tmp_path: Path) -> None:
    root = tmp_path
    profile = {
        "id": "718006",
        "name": "AI Governance Team",
        "apply_to": ["writer", "critic", "reviser", "planner", "pla", "er", "alig", "me", "t"],
    }
    result = save_agent_profile(root, profile, store="site")
    saved = _read_json(root / result["path"])
    assert saved["apply_to"] == ["writer", "critic", "reviser", "planner", "alignment"]


def test_list_agent_profiles_normalizes_existing_apply_to(tmp_path: Path) -> None:
    root = tmp_path
    profile_dir = root / "site" / "agent_profiles"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "registry.json").write_text(
        json.dumps({"718006": {"file": "718006.json"}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (profile_dir / "718006.json").write_text(
        json.dumps(
            {
                "id": "718006",
                "name": "AI Governance Team",
                "apply_to": ["writer", "critic", "reviser", "planner", "pla", "er", "alig", "me", "t"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    listed = list_agent_profiles(root)
    site_profile = next(item for item in listed if item["id"] == "718006")
    assert site_profile["apply_to"] == ["writer", "critic", "reviser", "planner", "alignment"]


def test_federlicht_load_profile_normalizes_apply_to_fragments(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "registry.json").write_text(
        json.dumps({"demo": {"file": "demo.json"}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (profile_dir / "demo.json").write_text(
        json.dumps(
            {
                "id": "demo",
                "name": "Demo",
                "apply_to": ["writer", "pla", "er", "alig", "me", "t"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    profile = core_profiles.load_profile("demo", profile_dir=str(profile_dir))
    assert profile.apply_to == ["writer", "planner", "alignment"]
