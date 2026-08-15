from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from .contract import build_uhdm_structure_contract, contract_module_map, read_json


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve(base: Path, value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def prepare_prompt_pack(
    config_path: Path, output_dir: Path, rtl_root: Path | None = None
) -> dict[str, Any]:
    config_path = config_path.resolve()
    case_root = config_path.parent
    config = read_json(config_path)
    if config.get("schema_version") != 1:
        raise ValueError("UHDM Agent SystemC config schema_version must be 1")
    structure_ir_path = resolve(case_root, config["uhdm"]["structure_ir"])
    structure_ir = read_json(structure_ir_path)
    contract = build_uhdm_structure_contract(structure_ir)
    modules = contract_module_map(contract)

    source_root = (
        rtl_root.resolve()
        if rtl_root
        else resolve(case_root, config["behavior"]["source_root"])
    )
    source_entries = config["behavior"].get("sources", [])
    source_by_module = {str(item["module"]): item for item in source_entries}
    if set(source_by_module) != set(modules):
        raise ValueError(
            "behavior source modules do not match UHDM modules: "
            f"sources={sorted(source_by_module)}, uhdm={sorted(modules)}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir = output_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    contract_path = output_dir / "structure_contract.json"
    contract_path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    manifest_sources = []
    prompt_paths = []
    for module_name in sorted(modules):
        source_entry = source_by_module[module_name]
        source_path = resolve(source_root, source_entry["path"])
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        digest = sha256_file(source_path)
        expected_digest = source_entry.get("sha256")
        if expected_digest and digest != expected_digest:
            raise ValueError(
                f"source digest mismatch for {module_name}: {digest} != {expected_digest}"
            )
        source_text = source_path.read_text(encoding="utf-8", errors="replace")
        prompt = render_module_prompt(
            config, contract, modules[module_name], source_path, digest, source_text
        )
        prompt_path = prompts_dir / f"{module_name}.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        prompt_paths.append(str(prompt_path))
        manifest_sources.append(
            {
                "module": module_name,
                "path": str(source_path),
                "sha256": digest,
                "bytes": source_path.stat().st_size,
                "prompt": str(prompt_path),
            }
        )

    candidate_dir = output_dir / "candidate"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    for entry in config.get("systemc", {}).get("seed_files", []):
        source = resolve(case_root, entry["source"])
        target = candidate_dir / entry.get("target", source.name)
        if not source.is_file():
            raise FileNotFoundError(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    task_path = output_dir / "AGENT_TASK.md"
    task_path.write_text(
        render_agent_task(config, contract, prompt_paths), encoding="utf-8"
    )
    manifest = {
        "format": "llm4eda-uhdm-agent-systemc-generation-manifest",
        "version": "1.0.0",
        "case": config.get("case"),
        "top": contract["top"],
        "structure_contract": str(contract_path),
        "structural_fingerprint": contract["structural_fingerprint"],
        "behavior_sources": manifest_sources,
        "candidate_dir": str(candidate_dir),
        "agent_task": str(task_path),
        "generation_policy": {
            "structure_authority": "UHDM",
            "behavior_prompt": "complete original SystemVerilog per module",
            "agent_authored_systemc": True,
            "regex_translation": False,
            "hdlconvertor_translation": False,
            "circt_translation": False,
            "internal_tlm": False,
        },
    }
    manifest_path = output_dir / "generation_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {**manifest, "manifest": str(manifest_path)}


def render_module_prompt(
    config: dict[str, Any],
    contract: dict[str, Any],
    module: dict[str, Any],
    source_path: Path,
    source_digest: str,
    source_text: str,
) -> str:
    module_name = str(module["name"])
    ports = "\n".join(
        f"- `{item['direction']} {item['name']}`，证据 `{item.get('evidence_id')}`"
        for item in module.get("ports", [])
    )
    instances = (
        "\n".join(
            f"- `{item['name']}`: `{item['module']}`，路径 `{item.get('path')}`，"
            f"绑定 `{json.dumps(item.get('bindings', []), ensure_ascii=False)}`"
            for item in module.get("instances", [])
        )
        or "- 无子模块实例。"
    )
    return f"""# {module_name}：UHDM 约束下的 SystemC 生成任务

## 不可修改的结构约束

- 顶层：`{contract["top"]}`
- 当前模块：`{module_name}`
- UHDM 结构指纹：`{contract["structural_fingerprint"]}`
- 内部层次必须使用 `SC_MODULE`/SystemC 信号和进程；不得把子模块改成 TLM socket。
- 端口、实例名、实例类型和连接必须与下列 UHDM 证据一致。

### 端口

{ports}

### 子模块与连接

{instances}

## 行为生成规则

下面的完整 SV 文件是行为提示词和实现证据。请直接理解其中的组合逻辑、时序逻辑、状态机、
寄存器、存储器、复位、握手和错误响应，并生成 C++17 SystemC：

- 边沿时序可使用 `SC_CTHREAD` 或 `SC_METHOD`；组合逻辑优先使用 `SC_METHOD` 或无副作用普通函数；
- 进程、端口、信号和模块实例应使用标准 SystemC 写法，供 systemc-clang 抽取；
- 普通辅助函数和进程使用模块前缀命名（例如 `foo_run`、`foo_drive`），避免不同类的同名成员让静态调用图产生歧义；
- 不要求逐句机械翻译，但所有外部可观察行为必须由原 SV 支持；
- 不得删除错误路径、边界检查、复位或 backpressure 来通过测试；
- 保留 `[SC_IF]` 模块接口日志，便于失败后按接口定位；
- 生成后必须通过 UHDM 结构探针、systemc-clang 静态分析、SystemC 编译和共享数据差分。

## 行为证据

- 文件：`{source_path}`
- SHA-256：`{source_digest}`

```systemverilog
{source_text}
```
"""


def render_agent_task(
    config: dict[str, Any], contract: dict[str, Any], prompt_paths: list[str]
) -> str:
    prompt_list = "\n".join(f"- `{path}`" for path in prompt_paths)
    return f"""# UHDM-guided Agent SystemC Implementation

从下列逐模块提示生成或修改 `candidate/` 中的 SystemC：

{prompt_list}

结构真值是 `structure_contract.json`，指纹为
`{contract["structural_fingerprint"]}`。原始 SV 只用于行为推理；不得重新猜测模块层次。

完成后执行：

```bash
dscflow uhdm-systemc verify \\
  --config {config.get("_display_path", "configs/uhdm_agent.json")} \\
  --run-dir <本目录>
```

验收顺序：UHDM 结构合同 → SystemC 运行时结构 → systemc-clang → 编译 → 共享数据差分。
"""
