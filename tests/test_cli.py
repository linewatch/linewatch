import pytest

from linewatch import __version__
from linewatch.cli import main


def test_main_runs(capsys):
    assert main([]) == 0
    assert __version__ in capsys.readouterr().out


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out
