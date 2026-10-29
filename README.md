# Cockpit Benchmark

座舱竞品体验 Benchmark MVP。当前实现为独立 Analyzer 原型，并提供 AIHOT 模块集成骨架；尚未直接嵌入 AIHOT 上游。

## Sprint 0–1
- 视频上传与 ffprobe 元数据探测
- FFmpeg 定点抽帧，证据 ID、时间戳、SHA-256
- 可选 OpenAI-compatible VLM 结构化分析
- Rubric 校验与人工审核保护
- 未配置 VLM 时不产生虚假分数

## Sprint 2
- AIHOT 模块接入契约与 Analyzer HTTP client
- SQL migration 草案
- 评分审核策略与排行榜准入规则

## Status
代码与设计文档正在分批提交。请查看 `docs/` 与 `integrations/aihot-module/`。此仓库为 Private。

## Safety
真实 VLM 准确率和人工评分一致性尚未验证；MVP 不应直接用于生产或未经人工审核的正式排名。
