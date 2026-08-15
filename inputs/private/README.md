# 私有输入区

此目录在本地已放入老师提供的 DSC RTL、三份规格 PDF 及其文本抽取版本，但内容默认被
Git 忽略。不要把授权不明的 RTL、标准文本或客户测试向量提交到公开仓库。

期望的本地布局：

```text
inputs/private/
├── rtl/       # 43 个 SV 定义、surelog.f、UHDM 复现说明
├── spec/      # DSC v1.2b、encoder user guide、release notes
└── spec-text/ # PDF 文本抽取，仅供检索/Agent 提示
```

`configs/staged_circt.json` 默认从 `inputs/private/rtl` 读取真实设计。
