# Sprint 0 — AIHOT Baseline

核查对象：`KKKKhazix/AIHOT` 公开 main 分支与仓库文档（截至 2026-10-28）。

AIHOT 可扩展模块模式包含模块声明、server、web、migrations 与测试，并通过 site modules 注册。其原生内容对象偏新闻/文本，不直接覆盖视频二进制处理、帧证据模型和座舱 Rubric。

推荐边界：视频处理独立为 HTTP 服务，AIHOT 模块通过 API 调用；不把 ffmpeg/VLM 工作放入原有新闻 worker。

限制：未在 AIHOT checkout 中编译验证模块代码。需在实际 fork 中完成接口适配、类型检查和端到端验证。
