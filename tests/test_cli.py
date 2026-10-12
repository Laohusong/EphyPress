import json
import subprocess
import sys

import numpy as np


def test_installed_module_cli_roundtrip_and_error_codes(tmp_path):
    raw, archive, restored = tmp_path / "raw.bin", tmp_path / "raw.spc", tmp_path / "restored.bin"
    np.arange(3001, dtype="<i2").tofile(raw)

    def run(*args):
        return subprocess.run(
            [sys.executable, "-m", "ephypress", *map(str, args)], capture_output=True, text=True
        )

    assert run("compress", raw, archive, "--channels", 1, "--workers", 1).returncode == 0
    check = run("verify", archive, "--original", raw)
    assert check.returncode == 0 and json.loads(check.stdout)["exact_equal"]
    assert json.loads(run("info", archive).stdout)["shape"] == [3001, 1]
    assert run("decompress", archive, restored).returncode == 0
    assert restored.read_bytes() == raw.read_bytes()
    assert run("decompress", archive, restored).returncode == 1
