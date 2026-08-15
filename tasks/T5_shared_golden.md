# T5：共享 stimulus 与软件 golden

## 目标

让纯软件 Function-TLM 成为独立的软件 golden，再供数据流/RTL 模型比较。

## 工作

1. 接收或构造明确批准的输入像素、PPS、APB 初始化与期望 bitstream。
2. 用 VESA CLI 和 `VesaReferenceCodec` 双路生成结果。
3. 用单顶层 `DscFunctionTlm` 通过同一 TLM 接口重放输入。
4. 写出 `datasets/authoritative_vectors.results.json` 和 `software_function.results.json`。
5. 执行 `dscflow golden compare --stage software ...`。

## 验收

- 同一 stimulus/PPS 的 SHA 一致；
- 状态和 bitstream SHA 完全一致；
- 公司向量未提供时只能标记 synthetic/standard-profile，不能标记 company-qualified。
