# T1：x86 环境与输入基线

## 目标

只在 x86 Linux 服务器上验证新仓库能独立运行，不修改算法或 RTL。

## 工作

1. 安装/确认 Python 3.10+、CMake、GCC/G++、SystemC、Surelog/UHDM、CIRCT、Verilator。
2. 执行 `python tools/check_assets.py` 和 `pytest -q`。
3. 执行 `./models/function_tlm/run_x86_verify.sh`。
4. 把工具版本、命令、返回码、输出 SHA 写入 `.work/reports/T1.json`。

## 验收

- 资产校验和全部一致；
- Python 回归全部通过；
- VESA CLI、C++ adapter、Function-TLM 对合成 RGB 用例逐字节一致；
- 报告明确公司向量仍缺失。
