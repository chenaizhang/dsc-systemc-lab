# CIRCT 层次剥离与 SystemC 骨架流程

## 1. 目标与边界

这条流程只要求 CIRCT 准确处理模块层次，不依赖 Verilator：

```text
SV elaboration → HW IR → 深度受控切片 → SystemC 模块骨架
```

切片保留模块端口、实例、内部通道和端口绑定；边界模块只生成行为槽，不宣称已经实现算法。
Comb、Seq、Memory 和 Aggregate 的行为转换属于边界逐步下移后的后续工作。

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

## 3. 一键调用

环境变量：

```bash
export DSCFLOW_CIRCT_ROOT=/path/to/circt/build
export DSCFLOW_CIRCT_LIBRARY_PATH=/path/to/circt/build/lib
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
3. `convert-hw-to-systemc=structure-only`；
4. `ExportSystemC`；
5. SystemC C++ 语法编译；
6. manifest、切片 HW、生成 SystemC 和可选 UHDM 的结构对比。

## 4. 输出与门禁

输出包括 `depth_N.hw.mlir`、manifest、SystemC MLIR/C++ 和 verification JSON。
验证报告只有在以下条件全部满足时才为 `pass`：

- HW 模块集合等于 manifest 的 retained 集合；
- HW 实例边等于 manifest 的 retained 边；
- SystemC 模块集合等于 retained 集合；
- frontier 没有保留内部实例；
- 提供 UHDM 时，顶层直属实例名和定义名一致；
- SystemC C++ 通过实际编译。

## 5. 当前层次语义限制

第一版按“模块定义的最短可达深度”切片。同一参数特化模块在多条实例路径复用时使用相同边界；
尚未实现同一模块的两个实例采用不同展开深度。后续若需要实例路径级细化，应先沿指定路径克隆
模块定义，再分别设置 frontier，不能直接修改共享定义。

这个限制不会影响顶层及统一深度的逐层剥离，但必须在需要逐实例替换前解决。
