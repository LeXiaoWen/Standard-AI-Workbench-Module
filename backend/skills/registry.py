from __future__ import annotations

from .base import SkillAdapter
from .example_echo_workflow import ExampleEchoAdapter


_ADAPTERS: dict[str, SkillAdapter] = {
    ExampleEchoAdapter.skill_name: ExampleEchoAdapter(),
}


def list_adapters() -> list[SkillAdapter]:
    return list(_ADAPTERS.values())


def get_adapter(skill_name: str) -> SkillAdapter:
    try:
        return _ADAPTERS[skill_name]
    except KeyError as exc:
        raise KeyError(f"未知 skill：{skill_name}") from exc
