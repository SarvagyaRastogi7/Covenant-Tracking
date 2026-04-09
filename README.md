# Covenanttrackingphase1 Crew

Welcome to the Covenanttrackingphase1 Crew project, powered by [crewAI](https://crewai.com). This template is designed to help you set up a multi-agent AI system with ease, leveraging the powerful and flexible framework provided by crewAI. Our goal is to enable your agents to collaborate effectively on complex tasks, maximizing their collective intelligence and capabilities.

## Installation

Ensure you have Python >=3.10 <3.14 installed on your system. This project uses [UV](https://docs.astral.sh/uv/) for dependency management and package handling, offering a seamless setup and execution experience.

First, if you haven't already, install uv:

```bash
pip install uv
```

Next, navigate to your project directory and install the project into the virtualenv:

```bash
uv sync --no-editable
```

On **Python 3.13**, **`uv sync` without `--no-editable`** can leave the project broken: the console script may fail with `ModuleNotFoundError` (sometimes for `covenanttrackingphase1` or `covenanttrackingphase1.main`) because hidden `._*.pth` files are not applied, or an old install can leave an incomplete `site-packages/covenanttrackingphase1/` (e.g. only `tools/`).

- **Fix install:** `UV_NO_EDITABLE=1 uv sync --reinstall-package covenanttrackingphase1`
- **Always use:** `uv sync --no-editable` (or set `UV_NO_EDITABLE=1` in your shell before `uv sync`).

(Optional) Lock/sync via CrewAI’s installer:

```bash
crewai install
```
### Customizing

**Local LLM (Ollama):** Agents are set to `ollama/llama3.1` in `config/agents.yaml`. Run `ollama serve`, pull the model (`ollama pull llama3.1`), and optionally set `OLLAMA_API_BASE` in `.env` if Ollama is not on `http://localhost:11434`. Per-agent memory is off so OpenAI is not required.

**Cloud OpenAI (optional):** To use OpenAI instead, change `llm` in `agents.yaml` (for example `openai/gpt-4o-mini`) and set `OPENAI_API_KEY` in `.env`.

- Modify `src/covenanttrackingphase1/config/agents.yaml` to define your agents
- Modify `src/covenanttrackingphase1/config/tasks.yaml` to define your tasks
- Modify `src/covenanttrackingphase1/crew.py` to add your own logic, tools and specific args
- Modify `src/covenanttrackingphase1/main.py` to add custom inputs for your agents and tasks

## Running the Project

From the **repository root** (after `uv sync --no-editable`):

```bash
uv run covenanttrackingphase1
```

Or:

```bash
crewai run
```

**If the CLI fails** with `ModuleNotFoundError` for `covenanttrackingphase1` or `covenanttrackingphase1.main` (often after `uv sync` without `--no-editable` on Python 3.13), repair the env and rerun:

```bash
UV_NO_EDITABLE=1 uv sync --reinstall-package covenanttrackingphase1
```

**Fallback** that does not depend on a correct editable/wheel layout of the project (only the venv deps must be installed):

```bash
PYTHONPATH=src uv run python -m covenanttrackingphase1
```

## Understanding Your Crew

The CovenantTrackingPhase1 Crew is composed of multiple AI agents, each with unique roles, goals, and tools. These agents collaborate on a series of tasks, defined in `config/tasks.yaml`, leveraging their collective skills to achieve complex objectives. The `config/agents.yaml` file outlines the capabilities and configurations of each agent in your crew.

## Support

For support, questions, or feedback regarding the Covenanttrackingphase1 Crew or crewAI.
- Visit our [documentation](https://docs.crewai.com)
- Reach out to us through our [GitHub repository](https://github.com/joaomdmoura/crewai)
- [Join our Discord](https://discord.com/invite/X4JWnZnxPb)
- [Chat with our docs](https://chatg.pt/DWjSBZn)

Let's create wonders together with the power and simplicity of crewAI.
