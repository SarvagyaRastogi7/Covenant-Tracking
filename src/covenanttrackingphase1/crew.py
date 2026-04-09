from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent

from covenanttrackingphase1.tools.custom_tool import (
    AgenticCalculateDSCRTool,
    AgenticGenerateReportTool,
    AgenticValidateExcelTool,
)


@CrewBase
class Covenanttrackingphase1:
    """Crew for covenant workbook ingestion, DSCR calculation, and reporting."""

    agents: list[BaseAgent]
    tasks: list[Task]

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def orchestrator_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["orchestrator_agent"],  # type: ignore[index]
            verbose=True,
        )

    @agent
    def excel_ingestion_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["excel_ingestion_agent"],  # type: ignore[index]
            tools=[AgenticValidateExcelTool()],
            verbose=True,
        )

    @agent
    def calculation_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["calculation_agent"],  # type: ignore[index]
            tools=[AgenticCalculateDSCRTool()],
            verbose=True,
        )

    @agent
    def reporting_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["reporting_agent"],  # type: ignore[index]
            tools=[AgenticGenerateReportTool()],
            verbose=True,
        )

    @task
    def validate_excel_input_task(self) -> Task:
        return Task(
            config=self.tasks_config["validate_excel_input_task"],  # type: ignore[index]
        )

    @task
    def calculate_dscr_task(self) -> Task:
        return Task(
            config=self.tasks_config["calculate_dscr_task"],  # type: ignore[index]
            context=[self.validate_excel_input_task()],
        )

    @task
    def generate_decision_report_task(self) -> Task:
        return Task(
            config=self.tasks_config["generate_decision_report_task"],  # type: ignore[index]
            context=[self.calculate_dscr_task()],
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
            memory=False,
        )
