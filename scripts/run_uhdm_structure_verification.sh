#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
image="${DSCFLOW_UHDM_DEV_IMAGE:-localhost/dscflow-uhdm-dev:main}"
rtl_dir="${DSCFLOW_RTL_DIR:-$repo_root/inputs/private/rtl}"
build_dir="${DSCFLOW_UHDM_BUILD_DIR:-$repo_root/.work/uhdm}"
evidence_dir="${DSCFLOW_UHDM_EVIDENCE_DIR:-$repo_root/evidence/uhdm}"

if [[ ! -f "$rtl_dir/surelog.f" ]]; then
  echo "error: missing private RTL file list: $rtl_dir/surelog.f" >&2
  exit 2
fi

mkdir -p "$build_dir" "$evidence_dir"

if ! podman image exists "$image"; then
  podman build \
    -f "$repo_root/containers/uhdm-dev.Containerfile" \
    -t "$image" \
    "$repo_root"
fi

podman run --rm \
  -v "$repo_root:/work" \
  -w /work \
  "$image" \
  bash -lc '
    set -euo pipefail
    rm -rf /work/.work/uhdm/surelog
    cd /work/inputs/private/rtl
    surelog \
      -odir /work/.work/uhdm/surelog \
      -f surelog.f \
      -sverilog -mt 1 -parse -elabuhdm \
      -top dsc_encoder \
      -l /work/evidence/uhdm/surelog.log
    uhdm-lint /work/.work/uhdm/surelog/slpp_all/surelog.uhdm \
      > /work/evidence/uhdm/uhdm-lint.log 2>&1
    g++ -std=c++17 -Wall -Wextra -Wpedantic \
      /work/tools/export_uhdm_hierarchy.cpp \
      $(pkg-config --cflags --libs UHDM) \
      -o /work/.work/uhdm/uhdm_module_hierarchy
    /work/.work/uhdm/uhdm_module_hierarchy \
      /work/.work/uhdm/surelog/slpp_all/surelog.uhdm \
      /work/evidence/uhdm/module_hierarchy.json
    uhdm-hier /work/.work/uhdm/surelog/slpp_all/surelog.uhdm \
      > /work/evidence/uhdm/uhdm-hier.log
  '

python3 - "$evidence_dir/module_hierarchy.json" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
data = json.loads(path.read_text())
designs = data.get("designs", [])
definitions = sum(len(item.get("module_definitions", [])) for item in designs)
instances = sum(len(item.get("invocations", [])) + len(item.get("top_modules", [])) for item in designs)
def walk(nodes):
    for node in nodes:
        yield node
        yield from walk(node.get("children", []))

nodes = [node for design in designs for node in walk(design.get("top_modules", []))]
ports = [port for node in nodes for port in node.get("ports", [])]
child_ports = [port for node in nodes[1:] for port in node.get("ports", [])]
named_bindings = [
    port for port in child_ports
    if port.get("connection_name") or port.get("connection_full_name")
]
explicitly_unconnected = [
    port for port in child_ports
    if port.get("connected")
    and not (port.get("connection_name") or port.get("connection_full_name"))
]
print(
    "UHDM structure verified: "
    f"definitions={definitions} instances={instances} "
    f"ports={len(ports)} named_bindings={len(named_bindings)} "
    f"explicitly_unconnected={len(explicitly_unconnected)}"
)
if not designs or instances <= 1:
    raise SystemExit("error: exported UHDM hierarchy is empty")
if not ports or not named_bindings:
    raise SystemExit("error: UHDM ports or child-instance bindings are empty")
PY

# Cross-fill the port widths from the CIRCT core IR (UHDM 1.84 exports every
# port with width 0) and gate on a complete fill.
hw_mlir="${DSCFLOW_HW_MLIR:-$repo_root/.work/dsc_encoder.hw.mlir}"
if [[ ! -f "$hw_mlir" ]]; then
  echo "error: CIRCT core IR not found (set DSCFLOW_HW_MLIR): $hw_mlir" >&2
  exit 2
fi
python3 tools/fill_uhdm_widths.py \
  "$evidence_dir/module_hierarchy.json" \
  "$hw_mlir" \
  "$evidence_dir/structure_ir.json"

python3 - "$evidence_dir/structure_ir.json" <<'PY'
import json
import pathlib
import sys

data = json.loads(pathlib.Path(sys.argv[1]).read_text())
gates = data["gates"]
print(
    "UHDM widths verified: "
    f"definitions={gates['definitions']} ports={gates['ports']} "
    f"filled={gates['widths_filled']} missing={gates['widths_missing']}"
)
if gates["widths_missing"] != 0:
    raise SystemExit("error: some UHDM ports have no CIRCT width")
if gates["widths_filled"] < 3000:
    raise SystemExit("error: unexpectedly few filled port widths")
for module in data["modules"]:
    for port in module["ports"]:
        if not port.get("width_bits"):
            raise SystemExit(
                f"error: zero-width port {module['name']}.{port['name']}"
            )
PY
