"""Shared test fixtures for Spore tests."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import git

if TYPE_CHECKING:
    from pathlib import Path
import pytest

from spore.repo import SporeRepo


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    """Create a temporary Git repository."""
    repo = git.Repo.init(tmp_path)
    repo.config_writer().set_value("user", "name", "Test Agent").release()
    repo.config_writer().set_value("user", "email", "test@spore.dev").release()
    # Create initial commit so HEAD exists
    readme = tmp_path / "README.md"
    readme.write_text("# Test Repo\n")
    repo.index.add([str(readme)])
    repo.index.commit("initial commit")
    return tmp_path


@pytest.fixture
def spore_repo(tmp_git_repo: Path) -> SporeRepo:
    """Create an initialized SporeRepo in a temp directory."""
    os.environ["SPORE_AGENT_ID"] = "test-agent"
    repo = SporeRepo(tmp_git_repo)
    repo.init(agent_id="test-agent", repo_name="test-repo")
    return repo


@pytest.fixture
def spore_repo_with_experiment(spore_repo: SporeRepo) -> SporeRepo:
    """SporeRepo with a running experiment."""
    spore_repo.start_experiment(
        direction="attention-variants",
        hypothesis="MQA reduces memory without hurting quality",
        create_branch=False,  # Avoid branch switching in tests
    )
    return spore_repo


@pytest.fixture
def spore_repo_with_finding(spore_repo_with_experiment: SporeRepo) -> SporeRepo:
    """SporeRepo with a published finding."""
    repo = spore_repo_with_experiment
    experiments = repo.list_experiments()
    repo.publish_finding(
        experiment_id=experiments[0].id,
        direction="attention-variants",
        claim="MQA with 4 KV heads reduces val_bpb by 0.02",
        metrics={"val_bpb": 0.4523, "delta": -0.0201},
        significance=0.7,
        applicability=["attention", "memory-efficiency"],
    )
    return repo
