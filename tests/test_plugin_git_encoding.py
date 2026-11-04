# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Workspace identity survives a non-UTF-8 host locale."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("integration", "module"),
    [("codex", "scope_binding"), ("claude-code", "workspace_scope"), ("workbuddy", "workspace_scope")],
)
def test_plugin_reads_unicode_git_root_under_gbk_locale(tmp_path: Path, integration: str, module: str) -> None:
    git = shutil.which("git")
    if git is None:
        pytest.skip("Git is required to resolve a repository workspace")
    repository = tmp_path / "财报仓库"
    repository.mkdir()
    subprocess.run([git, "init", "--quiet", str(repository)], check=True, capture_output=True, timeout=10)
    plugin = Path(__file__).resolve().parents[1] / "integrations" / integration / "plugins/powercontext"
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(plugin / "scripts"), str(plugin))),
        "PYTHONUTF8": "0",
        "PYTHONIOENCODING": "utf-8",
    }
    # Change subprocess's default decoder in a separate process, preserving the
    # test runner's locale and the Git process's actual UTF-8 path output.
    program = (
        "import importlib, locale, sys; "
        "locale.getencoding = lambda: 'gbk'; "
        "binding = importlib.import_module(sys.argv[1]); "
        "print(binding._git_value(sys.argv[2], 'rev-parse', '--show-toplevel'))"
    )
    result = subprocess.run(
        [sys.executable, "-c", program, module, str(repository)],
        env=environment,
        check=True,
        capture_output=True,
        encoding="utf-8",
        timeout=15,
    )
    assert Path(result.stdout.strip()).resolve() == repository.resolve()
