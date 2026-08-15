#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_ppm(path: Path, width: int, height: int) -> None:
    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            pixels.extend(((3 * x + 5 * y) & 0xFF, (7 * x ^ 11 * y) & 0xFF, (13 * x + y) & 0xFF))
    path.write_bytes(f"P6\n{width} {height}\n255\n".encode("ascii") + pixels)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a VESA CLI reference and byte-compare the in-process DSC adapter"
    )
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--adapter-test", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    model_root = args.model_root.resolve()
    work_dir = args.work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    image = work_dir / "deterministic_rgb.ppm"
    source_list = work_dir / "source_list.txt"
    config = work_dir / "reference.cfg"
    write_ppm(image, 192, 108)
    source_list.write_text(f"{image}\n", encoding="utf-8")
    config.write_text(
        "\n".join(
            [
                "DSC_VERSION_MINOR 2",
                "FUNCTION 1",
                f"SRC_LIST {source_list}",
                f"OUT_DIR {work_dir}",
                "SLICE_WIDTH 96",
                "SLICE_HEIGHT 108",
                "BLOCK_PRED_ENABLE 1",
                "VBR_ENABLE 0",
                "LINE_BUFFER_BPC 16",
                "USE_YUV_INPUT 0",
                "SIMPLE_422 0",
                "NATIVE_422 0",
                "NATIVE_420 0",
                "FULL_ICH_ERR_PRECISION 0",
                f"INCLUDE {model_root / 'rc_8bpc_8bpp.cfg'}",
                "PPM_FILE_OUTPUT 0",
                "DPX_FILE_OUTPUT 0",
                "HDR_DPX_FILE_OUTPUT 0",
                "YUV_FILE_OUTPUT 0",
                "",
            ]
        ),
        encoding="utf-8",
    )

    cli = model_root / "source" / "dsc"
    cli_run = subprocess.run(
        [str(cli), "-F", str(config)],
        cwd=model_root,
        text=True,
        capture_output=True,
        check=False,
    )
    reference = work_dir / "deterministic_rgb.dsc"
    adapter_run = subprocess.run(
        [str(args.adapter_test.resolve()), str(image), str(reference)],
        text=True,
        capture_output=True,
        check=False,
    ) if cli_run.returncode == 0 and reference.is_file() else None

    report = {
        "format": "llm4eda-dsc-reference-differential",
        "version": "1.0.0",
        "host_architecture": subprocess.run(
            ["uname", "-m"], text=True, capture_output=True, check=True
        ).stdout.strip(),
        "source": {
            "name": "VESA DSC C reference model 1.67",
            "release": "DSC_model_20211213",
            "archive_sha256": "f2339edb1d5603d2f3ca5fbb6ca089b18ff73c43088352fa7c3b59df03e3ee2c",
        },
        "case": {
            "id": "rgb444-8bpc-8bpp-192x108-two-slices",
            "input_sha256": sha256(image),
            "reference_sha256": sha256(reference) if reference.is_file() else None,
            "reference_bytes": reference.stat().st_size if reference.is_file() else 0,
        },
        "vesa_cli": {
            "returncode": cli_run.returncode,
            "stdout": cli_run.stdout,
            "stderr": cli_run.stderr,
        },
        "adapter": {
            "returncode": adapter_run.returncode if adapter_run else None,
            "stdout": adapter_run.stdout if adapter_run else "",
            "stderr": adapter_run.stderr if adapter_run else "not run",
        },
        "pass": bool(adapter_run and cli_run.returncode == 0 and adapter_run.returncode == 0),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
