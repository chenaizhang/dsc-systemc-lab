# 当前落地进度与边界

## CIRCT 主线已完成

1. **层次剥离**：可按深度保留 `hw.module`、端口、实例和连接，并生成对应
   `systemc.module`。真实 `dsc_encoder` 在深度 6 保留 50 个模块定义和 89 条实例边，
   frontier 为 0。
2. **Comb**：算术、位运算、比较、mux、concat、extract、类型转换及聚合胶水可导出；
   Comb 结果会物化为局部变量，避免 ExportSystemC 递归内联形成指数级 C++ 表达式。
3. **Seq**：基础寄存器、时钟、同步/异步复位和 enable 已能转换并发射；寄存器运行测试通过。
4. **存储器**：受支持的存储表示可转换为 SystemC 数组及读写进程；独立内存运行测试通过。
5. **延迟线程**：SystemC dialect 的 `SC_THREAD + wait()` 发射和运行测试通过。SV delayed
   task 到该表示的完整前端 lowering 仍需按输入语法继续扩充。
6. **聚合反馈**：新增位级依赖证明，只消除一轮更新中所有元素均被覆盖的前端临时反馈环；
   可能表示 latch 或真实组合环的部分覆盖不会被静默删除。
7. **Verilator interop**：标量端口和 packed 聚合端口的混合模型均可从源码构建、链接和运行。

开发构建 revision 为 `fb0695bbcd33937d6e9c7cfc8a702065e997d708`。所有 EDA、C++ 和
SystemC 验证均在 Linux x86_64 环境执行。

## 本轮实测结果

| 检查项 | 结果 |
|---|---|
| HW-to-SystemC、SystemC dialect、ExportSystemC 基础回归 | 23/23 通过 |
| 层次、LLHD、Seq memory、SystemC 和导出完整发布回归 | 35/35 通过 |
| 内存 SystemC 运行测试 | 通过 |
| 寄存器、时钟、复位 SystemC 运行测试 | 通过 |
| `SC_THREAD + wait()` 运行测试 | 通过 |
| 标量与聚合 Verilator 混合运行测试 | 通过 |
| 仓库 Python 测试 | 49/49 通过 |
| 小型层次样本 Comb/Seq/Memory 端到端运行 | 通过 |
| 真实 `dsc_encoder` 深度 6 行为转换 | 50 模块、89 实例、0 frontier，通过 |
| 真实设计生成的 SystemC C++ | 6,955,310 字节，语法编译通过 |

## 仍未完成

1. 真实图像测试数据尚未对这份全层次 SystemC 进行端到端码流 golden 差分。因此目前能证明
   结构完整、转换闭环和代码可编译，不能证明压缩算法语义已经正确。
2. 转换日志仍会标记部分前端顺序反馈网络；它们已能生成代码，但仍需要以逐周期参考模型验证
   时序语义，不能只凭 C++ 编译结果判定正确。
3. 深度 2～5 的独立 function reference 尚未逐模块完成；该工作不阻塞 CIRCT backend，后续可由
   模型验证任务并行推进。
4. 新 revision 的可下载 Linux x86_64 Release 正在执行干净 CI 构建和回归；只有 CI 通过并用
   发布包在 x86 上复测后，才替换 0.1.5 的交付链接。

## 结论

当前已经不再是“只有 HW 骨架可用”。CIRCT 路径能够在真实设计上完成完整层次的 HW、Comb、
基础 Seq 和聚合转换，输出可编译 SystemC；内存、寄存器/复位、线程和混合模型也各有独立运行
证据。剩余核心风险从“代码生成能否完成”转为“真实图像输入下的逐周期和最终码流语义是否与
参考一致”。
