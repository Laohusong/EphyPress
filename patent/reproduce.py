"""按配置复现：validate、encode、codec、preflight、ks4 或 all。"""

import argparse
import subprocess
import sys
from pathlib import Path

from experiment import environment, load, read_config, save, sha256

HERE = Path(__file__).resolve().parent


def execute(config, script, name, **job):
    folder = Path(config["output"]) / name
    result = folder / "result.json"
    if result.exists():
        raise FileExistsError(f"已有结果，不能覆盖：{result}")
    payload = dict(config=config, result=str(result), **job)
    save(folder / "job.json", payload)
    print(f"运行 {name}", flush=True)
    with (folder / "run.log").open("w", encoding="utf-8") as log:
        subprocess.run(
            [sys.executable, str(HERE / script), str(folder / "job.json")],
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
        )
    return load(result)


def validate(config):
    expected = config["samples"] * config["channels"] * 2
    assert Path(config["raw"]).stat().st_size == expected, "原始文件大小错误"
    assert sha256(config["raw"]) == config["sha256"], "原始文件 SHA256 不符"
    assert Path(config["probe"]).is_file(), "缺少探针配置"
    assert config["codec_workers"] == len(config["codec_cpus"])
    assert config["decode_repeats"] >= 1 and all(rate > 0 for rate in config["rates_MB_s"])
    save(Path(config["output"]) / "validation.json", dict(exact_source=True, environment=environment(config)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("stage", choices=["validate", "encode", "codec", "preflight", "ks4", "all"])
    args = parser.parse_args()
    config = read_config(args.config)
    stages = ["validate", "encode", "codec", "preflight", "ks4"] if args.stage == "all" else [args.stage]
    for stage in stages:
        if stage == "validate":
            validate(config)
            continue
        validation = Path(config["output"]) / "validation.json"
        if not validation.is_file() or load(validation)["environment"]["config"] != config:
            raise RuntimeError("请先对同一配置运行 validate；之后不得更改输入文件")
        if stage == "encode":
            for kind in ("rans", "mtscomp"):
                execute(config, "benchmark_codecs.py", f"codec/{kind}_encode", kind=kind, operation="encode")
        elif stage == "codec":
            for kind in ("rans", "mtscomp"):
                execute(config, "benchmark_codecs.py", f"codec/{kind}_verify", kind=kind, operation="verify")
            for repeat in range(config["decode_repeats"]):
                kinds = ("rans", "mtscomp") if repeat % 2 == 0 else ("mtscomp", "rans")
                for operation in ("threads", "processes"):
                    for kind in kinds:
                        execute(
                            config,
                            "benchmark_codecs.py",
                            f"codec/{kind}_{operation}_{repeat + 1}",
                            kind=kind,
                            operation=operation,
                        )
            from benchmark_codecs import summarize

            summarize(Path(config["output"]) / "codec")
        elif stage == "preflight":
            for kind in ("raw", "rans", "mtscomp"):
                execute(config, "benchmark_ks4.py", f"preflight/{kind}", kind=kind, operation="preflight")
        elif stage == "ks4":
            for kind in ("raw", "rans", "mtscomp"):
                preflight = load(Path(config["output"]) / f"preflight/{kind}/result.json")
                assert preflight["status"] == "success" and preflight["metering_verified"]
            results = []
            # Preserve the historical raw/rANS order, followed by the mtscomp supplement.
            order = config["sorting_order"]
            assert {(rate, kind) for rate, kind in order} == {
                (rate, kind) for rate in config["rates_MB_s"] for kind in ("raw", "rans", "mtscomp")
            }
            assert len(order) == 3 * len(config["rates_MB_s"])
            for rate, kind in order:
                results.append(
                    execute(
                        config,
                        "benchmark_ks4.py",
                        f"ks4/{kind}_{rate}",
                        kind=kind,
                        rate=rate,
                        operation="sort",
                    )
                )
            for label, kinds in (("ks4_v03", {"raw", "rans"}), ("ks4_mtscomp", {"mtscomp"})):
                selected = [r for r in results if r["kind"] in kinds]
                folder = Path(config["output"]) / label
                save(folder / "results.json", selected)
                save(folder / "completion.json", dict(status="complete", runs=len(selected)))


if __name__ == "__main__":
    main()
