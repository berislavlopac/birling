from importlib.metadata import entry_points, version

import birling
from birling.cli import main


def test_package_reports_the_installed_distribution_version():
    expected = version("birling")

    reported = birling.__version__

    assert reported == expected


def test_package_installs_the_birling_command():
    [script] = entry_points(group="console_scripts", name="birling")

    command = script.load()

    assert command is main
