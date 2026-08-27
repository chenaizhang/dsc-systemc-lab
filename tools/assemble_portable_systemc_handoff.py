#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from dscflow.workflows.staged_circt.runner import _render_systemc_runtime_probe


def _module_names(value: str) -> list[str]:
    names = [item.strip() for item in value.split(",") if item.strip()]
    if not names:
        raise argparse.ArgumentTypeError("至少需要一个 interop 模块")
    for name in names:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$.-]*", name):
            raise argparse.ArgumentTypeError(f"非法模块名: {name}")
    return names


def _run(argv: list[str]) -> None:
    completed = subprocess.run(argv, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"命令失败({completed.returncode}): {' '.join(argv)}")


def _run_to_file(argv: list[str], output: Path) -> None:
    with output.open("wb") as stream:
        completed = subprocess.run(argv, stdout=stream, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"命令失败({completed.returncode}): {' '.join(argv)}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _isolate_public_module(ir: str, *, container: str, module_name: str) -> str:
    container_pattern = re.compile(
        rf"^(?P<indent>\s*)hw\.module\s+@{re.escape(container)}(?=\()",
        re.MULTILINE,
    )
    ir, container_count = container_pattern.subn(
        rf"\g<indent>hw.module private @{container}", ir, count=1
    )
    if container_count != 1:
        raise RuntimeError(f"无法把容器模块设为 private: {container}")

    target_pattern = re.compile(
        rf"^(?P<indent>\s*)hw\.module\s+private\s+@{re.escape(module_name)}(?=\()",
        re.MULTILINE,
    )
    ir, target_count = target_pattern.subn(
        rf"\g<indent>hw.module @{module_name}", ir, count=1
    )
    if target_count != 1:
        raise RuntimeError(f"无法把 interop 模块设为 public: {module_name}")
    return ir


def _externalize_firmem_primitives(ir: str) -> tuple[str, dict[str, tuple[int, int]]]:
    pattern = re.compile(
        r"^(?P<indent>\s*)hw\.module private "
        r"@(?P<name>gram_bist_1r1w(?:_\d+)?)"
        r"\((?P<ports>[^\n]+)\) \{",
        re.MULTILINE,
    )
    specifications: dict[str, tuple[int, int]] = {}
    search_start = 0
    while match := pattern.search(ir, search_start):
        ports = match.group("ports")
        address = re.search(r"in %addr_r : i(\d+)", ports)
        data = re.search(r"out data_r : i(\d+)", ports)
        if not address or not data:
            raise RuntimeError(f"无法识别 SRAM 端口: {match.group('name')}")
        specifications[match.group("name")] = (
            int(address.group(1)),
            int(data.group(1)),
        )

        opening_brace = match.end() - 1
        depth = 0
        closing_brace = None
        for index in range(opening_brace, len(ir)):
            if ir[index] == "{":
                depth += 1
            elif ir[index] == "}":
                depth -= 1
                if depth == 0:
                    closing_brace = index + 1
                    break
        if closing_brace is None:
            raise RuntimeError(f"SRAM 模块括号不完整: {match.group('name')}")

        declaration = match.group(0)[:-1].rstrip().replace(
            "hw.module private", "hw.module.extern", 1
        )
        ir = ir[: match.start()] + declaration + ir[closing_brace:]
        search_start = match.start() + len(declaration)
    return ir, specifications


def _render_firmem_primitives(specifications: dict[str, tuple[int, int]]) -> str:
    modules: list[str] = []
    for name, (address_width, data_width) in sorted(specifications.items()):
        depth = 1 << address_width
        modules.append(
            f"""
module {name} (
  input logic clk_r,
  input logic en_r,
  input logic [{address_width - 1}:0] addr_r,
  output logic [{data_width - 1}:0] data_r,
  input logic clk_w,
  input logic [{address_width - 1}:0] addr_w,
  input logic we_w,
  input logic [{data_width - 1}:0] data_w,
  input logic [11:0] bist_in,
  output logic [11:0] bist_out
);
  logic [{data_width - 1}:0] memory [0:{depth - 1}];
  always @(posedge clk_w)
    if (we_w)
      memory[addr_w] <= data_w;
  always @(posedge clk_r)
    if (en_r)
      data_r <= memory[addr_r];
  assign bist_out = 12'h000;
endmodule
""".strip()
        )
    return "\n\n".join(modules) + ("\n" if modules else "")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="组装从源码重新构建的 CIRCT/Verilator SystemC 交接工程"
    )
    parser.add_argument("--prepared-ir", type=Path, required=True)
    parser.add_argument("--mixed-header", type=Path, required=True)
    parser.add_argument("--frontend-record", type=Path)
    parser.add_argument("--container", required=True)
    parser.add_argument("--modules", type=_module_names, required=True)
    parser.add_argument("--circt-opt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo_root = args.repo_root.resolve()
    prepared_ir = args.prepared_ir.resolve()
    mixed_header = args.mixed_header.resolve()
    circt_opt = args.circt_opt.resolve()
    output = args.output.resolve()
    template = repo_root / "packaging" / "systemc_mixed"

    for path in (prepared_ir, mixed_header, circt_opt, template):
        if not path.exists():
            print(f"缺少输入: {path}", file=sys.stderr)
            return 2
    if output.exists():
        print(f"输出目录已存在，拒绝覆盖: {output}", file=sys.stderr)
        return 2

    shutil.copytree(template, output)
    generated = output / "generated"
    generated.mkdir()
    tests = output / "tests"
    tests.mkdir()
    rtl_shims = output / "rtl_shims"
    rtl_shims.mkdir()
    evidence = output / "evidence"
    evidence.mkdir()

    prepared_text, firmem_primitives = _externalize_firmem_primitives(
        prepared_ir.read_text(encoding="utf-8")
    )
    flattened_sources: dict[str, Path] = {}
    with tempfile.TemporaryDirectory(prefix="dsc-systemc-interop-") as temp_dir:
        temp_root = Path(temp_dir)
        for module_name in args.modules:
            isolated_ir = temp_root / f"{module_name}.mlir"
            isolated_ir.write_text(
                _isolate_public_module(
                    prepared_text,
                    container=args.container,
                    module_name=module_name,
                ),
                encoding="utf-8",
            )
            flattened_sv = generated / f"interop_{module_name}.sv"
            _run_to_file(
                [
                    str(circt_opt),
                    "--symbol-dce",
                    "--llhd-lower-processes",
                    "--canonicalize",
                    "--lower-seq-to-sv",
                    "--canonicalize",
                    "--export-verilog",
                    str(isolated_ir),
                    "-o",
                    "/dev/null",
                ],
                flattened_sv,
            )
            with flattened_sv.open("a", encoding="utf-8") as stream:
                stream.write("\n")
                stream.write(_render_firmem_primitives(firmem_primitives))
            flattened_sources[module_name] = flattened_sv
    shutil.copy2(mixed_header, generated / "mixed_systemc.hpp")
    shutil.copy2(
        template / "circt_systemc_verilator_wide.h",
        generated / "circt_systemc_verilator_wide.h",
    )
    shutil.copy2(
        repo_root / "models" / "cycle_systemc" / "rtl_shims" / "dsc_support_primitives.sv",
        rtl_shims / "dsc_support_primitives.sv",
    )
    shutil.copy2(
        repo_root / "models" / "cycle_systemc" / "tests" / "cdc_shim_tb.sv",
        tests / "cdc_shim_tb.sv",
    )
    shutil.copy2(
        repo_root / "scripts" / "run_portable_handoff_verification.sh",
        output / "verify.sh",
    )

    overlay_verified = False
    if args.frontend_record:
        frontend_record = args.frontend_record.resolve()
        record = json.loads(frontend_record.read_text(encoding="utf-8"))
        expected_overlay = str(
            (
                repo_root
                / "models"
                / "cycle_systemc"
                / "rtl_shims"
                / "dsc_support_primitives.sv"
            ).resolve()
        )
        overlay_verified = expected_overlay in [str(item) for item in record.get("argv", [])]
        if not overlay_verified:
            raise RuntimeError("frontend 记录没有使用同步器仿真 shim")
        shutil.copy2(frontend_record, evidence / "frontend_with_cdc_overlay.json")

    module_list = ";".join(args.modules)
    (generated / "interop_modules.cmake").write_text(
        "# Generated by assemble_portable_systemc_handoff.py\n"
        f'set(INTEROP_MODULES "{module_list}")\n',
        encoding="utf-8",
    )
    smoke_source = _render_systemc_runtime_probe(
        generated / "mixed_systemc.hpp", args.container
    ).replace(
        'std::cout << "CIRCT_SYSTEMC_PORTS=" << port_count << "\\n";',
        'std::cout << "CIRCT_SYSTEMC_PORTS=" << port_count << "\\n";\n'
        '  std::cout << "MIXED_SYSTEMC_SMOKE=PASS\\n";',
    )
    (tests / "mixed_systemc_smoke.cpp").write_text(smoke_source, encoding="utf-8")
    manifest = {
        "format": "portable-systemc-handoff-source-v1",
        "conversion_top": args.container,
        "container": args.container,
        "interop_modules": args.modules,
        "inputs": {
            "prepared_ir_sha256": _sha256(prepared_ir),
            "mixed_systemc_header_sha256": _sha256(mixed_header),
        },
        "generated": {
            "interop_flattened_sv_sha256": {
                name: _sha256(path) for name, path in flattened_sources.items()
            },
            "mixed_systemc_header_sha256": _sha256(
                generated / "mixed_systemc.hpp"
            ),
        },
        "precompiled_archives_included": False,
        "cdc_overlay_verified_in_frontend_record": overlay_verified,
    }
    (generated / "source_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
