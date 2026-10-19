"""Test suite for src/llm/apply_agent.py"""

from unittest.mock import patch

from src.llm.apply_agent import ApplyAgent, build_apply_task
from src.pydantic_models.config_models import Secrets

JOB_URL = "https://jobs.example.com/apply/42"
RESUME_TEXT = "Ana Pérez, Python developer"
RESUME_PDF = "C:/resumes/ana.pdf"


def _task(email="ana@x.com", password="S3cure!pw", tool_notes="TOOL NOTES HERE"):
    return build_apply_task(
        job_url=JOB_URL,
        resume_readable=RESUME_TEXT,
        resume_pdf_path=RESUME_PDF,
        user_email=email,
        external_sites_password=password,
        tool_notes=tool_notes,
    )


def test_task_uses_configured_password():
    task = _task()
    assert "ana@x.com" in task
    assert "S3cure!pw" in task
    assert "ana123456" not in task


def test_task_without_password_says_cannot_register():
    task = _task(password=None)
    assert "If the site requires creating an account, stop: you cannot apply." in task
    assert "123456" not in task


def test_task_without_email_says_cannot_register():
    task = _task(email=None)
    assert "If the site requires creating an account, stop: you cannot apply." in task


def test_task_keeps_core_rules():
    task = _task()
    assert JOB_URL in task
    assert RESUME_TEXT in task
    assert RESUME_PDF in task
    assert "Do not skip required fields" in task
    assert "TOOL NOTES HERE" in task


def test_secrets_accepts_external_sites_password():
    secrets = Secrets(external_sites_password="S3cure!pw")
    assert secrets.external_sites_password == "S3cure!pw"
    assert Secrets().external_sites_password is None


@patch("src.llm.apply_agent.LLM_MODEL_TYPE", "claude_code")
def test_apply_agent_claude_code_needs_no_key(tmp_path):
    agent = ApplyAgent(None, str(tmp_path / "state.json"))
    assert agent.llm is None


@patch("src.llm.apply_agent.LLM_MODEL_TYPE", "claude_code")
def test_apply_agent_stores_external_sites_password(tmp_path):
    agent = ApplyAgent(
        None,
        str(tmp_path / "state.json"),
        user_email="ana@x.com",
        external_sites_password="S3cure!pw",
    )
    assert agent.external_sites_password == "S3cure!pw"


@patch("src.llm.apply_agent.LLM_MODEL_TYPE", "claude_code")
def test_loggable_task_hides_password(tmp_path):
    """The task goes into logs/llm_api_calls.yaml; the password must not"""
    agent = ApplyAgent(
        None,
        str(tmp_path / "state.json"),
        user_email="ana@x.com",
        external_sites_password="S3cure!pw",
    )
    loggable = agent.loggable_task(_task())
    assert "S3cure!pw" not in loggable
    assert "password: ********" in loggable
