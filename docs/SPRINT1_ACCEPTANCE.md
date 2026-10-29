# Sprint 1 Acceptance

已实现独立 FastAPI Analyzer 原型：视频上传、ffprobe 元数据探测、FFmpeg 抽帧、证据 ID/时间戳/SHA-256、可选 OpenAI-compatible VLM、Rubric 校验、报告 API 和人工审核保护。

验证：此前本地自动化测试报告为 11/11 通过；使用 8 秒测试视频完成上传与抽帧端到端检查。未配置 VLM 时分项分数与总分保持 null。

限制：测试视频非真实座舱素材；真实 VLM 的识别准确率、评分一致性、性能尚未验证。任务存储和审核 API 仍是 MVP，不应直接暴露到公网。
