# CIRCT 层次剥离与 SystemC 结构/行为流程

## 1. 目标与边界

这条流程不依赖 Verilator，并提供两个可明确区分的工作模式：

```text
SV elaboration → HW/Comb/Seq IR → 深度受控切片
                                      ├─ structure：SystemC 模块骨架
                                      └─ behavior：保留层级的 SystemC 行为
```

切片保留模块端口、实例、内部通道和端口绑定；边界模块只生成行为槽，不宣称已经实现算法。
`behavior` 模式会继续转换 frontier 以上模块中的 Comb、寄存器和受支持的存储器操作，frontier
以下行为仍被隔离。因此可以逐层扩大真实行为的转换范围，并准确记录首个不支持的 operation。

## 2. CIRCT 修改

fork 分支：`codex/systemc-backend`

新增 pass：

```text
--hw-extract-hierarchy-slice="top=<module> max-depth=<N> manifest=<file>"
```

语义如下：

- 顶层深度为 0；
- 保留深度小于等于 `max-depth` 的可达模块；
- 深度等于 `max-depth` 的 `hw.module` 替换为同端口的 `hw.module.extern`；
- 删除边界以下不可达定义；
- manifest 同时记录保留边和被 frontier 截断的边；
- 不运行 `hw-aggregate-to-comb`，不进入边界模块的 Seq/Memory 实现。

`convert-hw-to-systemc="structure-only=true"` 同时扩展为：

- 将带 `hw.hierarchy.frontier` 的 extern 声明生成 `SC_MODULE`；
- 生成空的 `behaviorSlot` 和 `SC_METHOD` 注册；
- 保留 `systemc.hierarchy.frontier`、深度和端口属性；
- 父模块继续生成实例声明、`sc_signal` 和端口绑定。

完整 `convert-hw-to-systemc` 另外支持：

- frontier extern 仍生成相同的 `SC_MODULE` 行为槽；
- 保留模块的 `comb.*` 通过路径 A 直接发射到 `SC_METHOD`；
- `seq.compreg`、`seq.compreg.ce` 和 `seq.firreg` 生成边沿/复位敏感的时序方法；
- 受限的 `seq.firmem` 生成值初始化的 `std::array<sc_uint<W>, D>`，支持读延迟 0/1、
  写延迟 1、整字或单 bit mask；
- SystemC IR 中的线性延迟线程可发射为 `SC_THREAD`，`systemc.wait_time` 发射为
  `wait(sc_time(...))`。

最后一项目前只完成 SystemC dialect 到 C++ 的目标端。SV 带延迟 task 经 LLHD coroutine 自动
改写成该表示的源端 pass 尚未完成，不能把 emitter 测试等同于 SV 端到端支持。

## 3. 一键调用

环境变量：

```bash
export DSCFLOW_CIRCT_ROOT=/path/to/circt/build
export DSCFLOW_CIRCT_LIBRARY_PATH=/path/to/circt/build/lib
```

模式选择：

```bash
# 默认值，只验证结构
export DSCFLOW_SYSTEMC_MODE=structure

# 转换保留层级中的 Comb/Seq/受支持存储器
export DSCFLOW_SYSTEMC_MODE=behavior
```

运行单层：

```bash
scripts/run_circt_hierarchy_peeling.sh \
  /path/to/dsc_encoder.hw.mlir \
  dsc_encoder \
  1 \
  .work/runs/hierarchy/dsc_encoder/depth-1 \
  evidence/uhdm/module_hierarchy.json
```

脚本依次执行：

1. `hw-extract-hierarchy-slice`；
2. MLIR verifier；
3. `behavior` 模式先运行 LLHD 清理、内联和 timed-process→Seq；
4. 根据 `DSCFLOW_SYSTEMC_MODE` 运行 structure-only 或完整 `convert-hw-to-systemc`；
5. `ExportSystemC`；
6. SystemC C++ 语法编译；
7. manifest、切片 HW、生成 SystemC 和可选 UHDM 的结构对比。

## 4. 输出与门禁

输出包括 `depth_N.hw.mlir`、manifest、SystemC MLIR/C++ 和 verification JSON。行为模式还保留
`depth_N.llhd-core.mlir` 与 `depth_N.prepared.mlir`，用来定位是 LLHD→Seq 还是
HW/Comb/Seq→SystemC 失败。
验证报告只有在以下条件全部满足时才为 `pass`：

- HW 模块集合等于 manifest 的 retained 集合；
- HW 实例边等于 manifest 的 retained 边；
- SystemC 模块集合等于 retained 集合；
- frontier 没有保留内部实例；
- 提供 UHDM 时，顶层直属实例名和定义名一致；
- SystemC C++ 通过实际编译。

`behavior` 模式额外要求转换、IR 校验、ExportSystemC 和 C++ 编译全部成功；它只证明当前切片
包含的行为可以编译，不证明图像压缩输出已经与参考数据一致。

## 5. 当前层次语义限制

第一版按“模块定义的最短可达深度”切片。同一参数特化模块在多条实例路径复用时使用相同边界；
尚未实现同一模块的两个实例采用不同展开深度。后续若需要实例路径级细化，应先沿指定路径克隆
模块定义，再分别设置 frontier，不能直接修改共享定义。

这个限制不会影响顶层及统一深度的逐层剥离，但必须在需要逐实例替换前解决。

## 6. 行为能力边界

| 类别 | 当前实现 | 尚未覆盖 |
|---|---|---|
| Comb | 常用算术、位运算、比较、mux、concat/extract、类型转换 | 以真实设计复测发现的首个新 operation 为准 |
| Seq 寄存器 | 基础寄存器、enable、时钟边沿、复位 | 多时钟复杂过程需逐例验证 |
| 存储器 | 受限 `seq.firmem` → `std::array` 仿真存储器 | 多端口复杂冲突、任意 mask、文件/随机初始化 |
| 延迟 task | `SC_THREAD` 与 `wait()` 的目标发射和运行测试 | SV/LLHD coroutine → SystemC thread 自动 lowering |

所有能力先由 CIRCT Linux x86 CI 的编译和运行用例验证，再在私有 DSC core IR 上按深度复测。
