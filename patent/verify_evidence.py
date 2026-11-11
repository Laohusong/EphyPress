"""检查已交付附图的证据完整性；不把历史源码指纹套到当前代码上。"""

import math
import statistics
from pathlib import Path

from experiment import load, sha256

ROOT = Path(__file__).resolve().parent


def main():
    manifest = load(ROOT / "evidence_sha256.json")
    for name, expected in manifest.items():
        assert sha256(ROOT / name) == expected, f"证据文件改变：{name}"
    dataset = load(ROOT / "config/dataset.json")
    report = load(ROOT / "data/codec_comparison.json")
    rows = [r for r in report["rows"] if r["dataset"] == "neuropixels"]
    processes = [r for r in report["process_rows"] if r["dataset"] == "neuropixels"]
    assert len(rows) == len(processes) == 2
    assert {r["profile"] for r in rows} == {"delta_ans0", "mtscomp"}
    for row in rows + processes:
        assert row["raw_bytes"] == dataset["bytes"]
        assert len(row["decode_runs_s"]) == 5 and min(row["decode_runs_s"]) > 0
        assert math.isclose(statistics.median(row["decode_runs_s"]), row["decode_median_s"])
    for row in rows:
        assert row["exact_equal"] and row["raw_sha256"] == dataset["sha256"]
        assert math.isclose(row["ratio"], row["raw_bytes"] / row["archive_bytes"])
    all_results = []
    for folder, count in (("ks4_v03", 6), ("ks4_mtscomp", 3)):
        completion = load(ROOT / "data" / folder / "completion.json")
        results = load(ROOT / "data" / folder / "results.json")
        assert completion["status"] == "complete" and completion["runs"] == count == len(results)
        assert all(r["status"] == "success" and r["seconds"] > 0 for r in results)
        all_results.extend(results)
    assert {(r["kind"], r["bandwidth_MB_s"]) for r in all_results} == {
        (kind, rate) for kind in ("raw", "rans", "mtscomp") for rate in (100, 500, 5000)
    }
    print(f"通过：{len(manifest)} 个证据文件；图3同一数据；图4九次完整分选。")


if __name__ == "__main__":
    main()
