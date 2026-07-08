from __future__ import annotations

from abc import ABC, abstractmethod

from ..schemas import SkillMetadata, Workflow


class SkillAdapter(ABC):
    skill_name: str
    display_name: str
    description: str
    accepted_inputs: list[str]
    stages: list[str]

    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            skill_name=self.skill_name,
            display_name=self.display_name,
            description=self.description,
            accepted_inputs=self.accepted_inputs,
            stages=self.stages,
        )

    @abstractmethod
    def load_instructions(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def run_stage(self, workflow: Workflow, input_text: str = "") -> tuple[Workflow, str]:
        raise NotImplementedError

    @abstractmethod
    def confirm_stage(self, workflow: Workflow, text: str = "") -> tuple[Workflow, str]:
        raise NotImplementedError

    @abstractmethod
    def build_artifacts(self, workflow: Workflow) -> dict[str, tuple[str, str, str]]:
        raise NotImplementedError
