"""The skills object itself. Skipped when Home Assistant isn't installed."""
import pytest

pytest.importorskip("homeassistant")


def test_skill_mixins_never_shadow_each_other():
    """Skills, HouseSkills and SecuritySkills share one object: a method of the same name in two of them
    silently replaces the other (a "who am I" helper once broke every bed command this way)."""
    from custom_components.better_assistant.house import HouseSkills
    from custom_components.better_assistant.security import SecuritySkills
    from custom_components.better_assistant.skills import Skills

    def own(cls):
        return {n for n in vars(cls) if not (n.startswith("__") and n.endswith("__"))}
    assert not own(Skills) & own(HouseSkills)
    assert not own(Skills) & own(SecuritySkills)
    assert not own(HouseSkills) & own(SecuritySkills)
