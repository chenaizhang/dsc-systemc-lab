# CIRCT Verilator interop 回归复测报告

## 目的

使用已发布的 `systemc-backend-0.1.4` 复查以下问题：

1. interop 输入表达式的 SSA dominance；
2. `structure-only` 与 interop 组合时的实例完整性；
3. 完整原生转换的 `seq.firmem` 阻塞；
4. 全局 aggregate preparation 对内部存储的展开；
5. 七个顶层 Verilator 子模块的完整混合构建。

所有 EDA、C++ 和 SystemC 命令均在 x86_64 Linux 服务器执行。

## 环境

- CIRCT：`systemc-backend-0.1.4`，revision
  `5fff1f154467ade9a004d00284e76e78e7c09b02`；
- Verilator：5.032；
- SystemC：3.0.2；
- 编译器：g++ 15.2.0。

本次可访问的私有 bundle 生成 50 个 `hw.module` 定义和 89 个定义级 `hw.instance`。外部报告
使用的是另一份 `rtl.f`，对应 49 个 module、128 个定义级实例和 417 个展开实例；该 filelist
及其新增 primitive 源码尚未同步到当前验证服务器。因此本报告分别标注“通用最小复现”和
“现有私有 bundle 实测”，不把两份输入冒充为同一设计。

## 结果

| 检查项 | 结果 | 结论 |
|---|---|---|
| interop 前向定义/反馈最小复现 | 通过 | `0.1.4` 的拓扑排序修复有效 |
| 最终 interop IR verifier | 通过 | 未再出现 SSA dominance 错误 |
| `structure-only + interop` | 失败且命令误报成功 | `VLeaf`、实例声明和 interop 均为 0，静默丢实例缺陷确认 |
| 完整原生 SystemC | 失败 | 首错仍为 `seq.firmem<256 x 8, mask 1>` |
| 全局 aggregate preparation | 命令通过，但产生 `i196608` | 内部存储被超宽整数化的设计风险确认 |
| 大于等于一百万位整数 | 当前 bundle 为 0 | 外部报告的 `i805306368` 需要准确 417 实例输入才能复现 |
| 七模块完整混合模型 | 通过 | 7/7 选择一致，C++ 编译链接和 CTest 2/2 通过 |

dominance 回归包含两个 Verilator 黑盒之间的反馈，以及定义在 interop 使用点之后的组合表达式。
最终 IR 包含 `VLeft`、`VRight` 和唯一的 `systemc.module @FeedbackTop`，并通过独立 verifier。

`structure-only` 复测命令返回零，但输出中：

```text
VLeaf=0
leaf_instance=0
systemc.interop.verilated=0
```

因此它不能作为混合生成路径。近期必须至少增加前置诊断：检测到
`structure-only=true` 与 `systemc.interop.verilated` 同时出现时直接失败，不能继续返回成功。

完整原生转换的首错为：

```text
failed to legalize operation 'seq.firmem'
!seq.firmem<256 x 8, mask 1>
```

这不阻止七模块混合路线，但说明全原生 SystemC 尚未闭环。

## 结论

三个 interop 问题不能再统一描述为“当前版本都未修复”：

- **依赖拓扑问题已修复并复测通过**；
- **structure-only 静默丢实例仍存在**；
- **全局 aggregate preparation 的内部存储展开风险仍存在**，现有 bundle 已出现
  `i196608`，准确的数亿位复现仍缺对应 filelist；
- **七模块混合构建在现有私有 bundle 上已经闭环**，但必须用 417 实例版本再次执行相同门禁，
  才能对最新输入给出最终结论。

下一实现顺序为：先把 structure-only 静默成功改成显式失败并增加实例数量门禁；再实现只处理
选定 SystemC/Verilator 边界的 ABI scalarization，避免进入黑盒内部 memory；最后用准确的
417 实例 filelist 重跑生成、编译、elaboration 和单体 Verilator 差分。
