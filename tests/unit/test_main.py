import runpy
import sys

import pytest


def test_the_package_runs_the_birling_command(write_project, monkeypatch, capsys):
    root = write_project({"app/service.py": "def load():\n    return None\n"})
    monkeypatch.chdir(root)
    monkeypatch.setattr(sys, "argv", ["birling", "app"])

    with pytest.raises(SystemExit) as raised:
        runpy.run_module("birling", run_name="__main__")

    assert raised.value.code == 0
    assert capsys.readouterr().out.splitlines()[-1].split() == ["TOTAL", "0", "0", "100%"]
