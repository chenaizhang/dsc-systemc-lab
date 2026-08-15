# 拆仓报告

## 已完成

- 建立独立 Git 仓库，主分支 `main`；
- 从大仓中筛出 70 余个有效代码、配置、测试、证据和中文文档文件；
- 私有 RTL/spec 与第三方 VESA model 已复制到本地忽略区；
- 排除 260 MB UHDM 数据库、构建产物、AutoResearch 历史轮次及无关案例；
- 命令入口统一为 `dscflow`；
- 补充 DSC 专用 UHDM-Agent 配置、资产 SHA 检查脚本、模型边界和六个独立任务包；
- 已执行 Git whitespace/integrity 检查，工作区无已跟踪改动。

## 规模

- Git 对象约 596 KiB；
- 整个本地仓库约 6.5 MiB；
- 其中私有输入约 3.3 MiB，VESA 第三方缓存约 1.7 MiB，均不进入 Git。

## 验证状态

本轮没有新增伪装成本机结果的 EDA 测试。按项目规定，正式验证必须在 x86 服务器运行。
当前 Codex 执行环境尝试连接 `10.203.255.52:22` 时被网络沙箱拒绝（`Operation not permitted`），
因此 T1 的资产、pytest、SystemC/VESA 三路验证尚待在可访问服务器的任务中执行。

仓库内保留的 `evidence/results/` 是拆仓前已经在 x86 验证的历史证据，不等同于本次迁移后复跑。

## x86 复跑命令

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python tools/check_assets.py
pytest -q
./models/function_tlm/run_x86_verify.sh
```
