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
| 原始空壳原语输入生成的 SystemC C++ | 6,955,310 字节，语法编译通过；不能用于功能验证 |
| 改用有行为的同步器/RAM 原语后 | 6,960,190 字节，C++ 编译通过；96×16 图像功能差分失败 |

## 仍未完成

1. 已用 96×16 图像对全层次原生 SystemC 做端到端码流 golden 差分：1536 像素被接收，
   输出 0 字节；同输入 Verilator RTL 输出 1536 字节。首个缺失 valid 的已观测边界在
   predict 之后、format 输出之前。详见[中文报告](circt_native_image_differential_x86_zh.md)。
   完整 192×108 图像的原生输出尚未跑完，当前不能证明压缩算法语义正确。
2. 转换日志仍会标记部分前端顺序反馈网络；它们已能生成代码，但仍需要以逐周期参考模型验证
   时序语义，不能只凭 C++ 编译结果判定正确。
   此外，同一 SV 重新抽取的 HW IR 会出现 `llhd.wait` 顺序差异，另一次运行在
   `dsce_stream_fifo` 的 `seq.to_clock` 合法化失败；源码重建稳定性也未通过。
3. 深度 2～5 的独立 function reference 尚未逐模块完成；该工作不阻塞 CIRCT backend，后续可由
   模型验证任务并行推进。
4. 新 revision 的干净 CI 构建和回归已经通过，其二进制包在 x86 上重跑完整设计成功；
   [0.1.6 Release](https://github.com/chenaizhang/circt/releases/tag/systemc-backend-0.1.6)
   已发布，重新下载的资产与实测包逐字节一致；
   [标签工作流](https://github.com/chenaizhang/circt/actions/runs/35331143893)也已通过。

## 结论

当前已经不再是“只有 HW 骨架可用”。CIRCT 路径能够在真实设计上完成完整层次的 HW、Comb、
基础 Seq 和聚合转换，输出可编译 SystemC；内存、寄存器/复位、线程和混合模型也各有独立运行
证据。真实图像差分已发现原生模型的确定行为偏差，不能因结构/编译门禁通过而宣布完整
DSC 可用。先定位并修复 predict 至 format 之间的首个周期差异，再重跑整帧码流。
