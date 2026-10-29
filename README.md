# Cockpit Benchmark

座舱竞品体验 Benchmark MVP：把经授权的座舱视频转成带时间戳、可追溯的证据帧与结构化分析报告。当前交付是独立 Analyzer 原型和 AIHOT 集成骨架，**还不是生产可用的自动采集/排行榜系统**。

## 当前能力

- 本地上传 MP4、MOV、M4V、MKV、WEBM、AVI 视频。
- 通过 FFprobe 检查时长，通过 FFmpeg 抽帧。
- 输出有版本号的抽帧审计清单：策略、帧预算、实际时间戳、时间覆盖缺口和补充时间点。
- 可选场景切换采样策略 `scene_aware_v1`，并可在上传时补充短暂关键交互的时间点。
- 为证据帧记录 evidence ID、目标时间戳和 SHA-256。
- 可选调用 OpenAI-compatible 的视觉语言模型（VLM）分析采样帧。
- 校验评分引用的证据 ID、分数范围和评分理由；无证据项不允许猜分。
- 未配置 VLM 时只完成视频/抽帧验证，不生成评分。
- 浏览器页面查看任务、分项结果和证据帧，并记录人工审核。
- 提供 Docker 启动方式和 AIHOT 数据库/审核策略集成骨架。

## 快速启动

前置条件：Python 3.12（建议）以及 FFmpeg/FFprobe。

    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env
    uvicorn app.main:app --reload --host 127.0.0.1 --port 8010

Windows PowerShell 激活环境可用：

    .venv\Scripts\Activate.ps1

打开 http://127.0.0.1:8010。配置模型前，应用应只抽帧、不打分。若需启用 VLM，在本地 .env 配置 OPENAI_BASE_URL、VLM_MODEL 及相应 API Key；不要提交真实密钥。

也可查看 Dockerfile 和 docker-compose.yml。Compose 启动前需在本地创建 .env。

## 证据帧采样

默认策略为 `uniform_v1`，保持原有固定间隔采样行为。上传表单可在“补充关键证据时间点”中填写秒数，例如 `12.5, 18, 42.2`；这些时间点优先保留，但所有帧（包括补充帧）都受 `MAX_FRAMES` 限制。超出视频时长的时间点会被忽略并写入报告警告。

如需评估场景切换采样，可在本地 `.env` 设置：

    SAMPLING_POLICY=scene_aware_v1
    SCENE_CHANGE_THRESHOLD=0.30
    SCENE_DETECTION_TIMEOUT_SEC=180

该策略会额外解码一次视频，在 2 fps、宽度不超过 320 像素的代理画面上寻找**可能的视觉切换**，并把最多约三分之一的帧预算用于切换候选，其余帧用于时间覆盖。它不是语义事件识别，不能保证发现短暂的转向灯、按钮状态或所有弹窗；检测失败时会回退到时间覆盖采样并保留警告。场景切换检测会增加处理时间，建议先在固定金标视频集上与 `uniform_v1` 对比，再决定是否用于正式 Benchmark。

报告中的 `sampling_manifest` 记录策略与版本、候选/选中时间戳、被丢弃的补充时间点、最大覆盖间隔及较大缺口，便于复现每一次分析。

## 关键目录

- app/main.py — 上传、状态、报告、证据帧和审核 API。
- app/video.py — 时长探测、抽帧与文件哈希。
- app/pipeline.py — 分析流水线和输出校验。
- app/providers/openai_compatible.py — OpenAI-compatible VLM 适配器。
- config/rubric.v1.json — 初版可观察性评分规范。
- schemas/analysis_result.schema.json — 分析结果 Schema。
- app/static/index.html — 浏览器 MVP。
- integrations/aihot-module/cockpit-benchmark — AIHOT 集成脚手架与 SQL migration。
- docs/TECHNICAL_PLAN.md — 当前范围、接口与下一步验证方案。
- docs/SPRINT0_BASELINE.md、docs/SPRINT1_ACCEPTANCE.md 与 SPRINT2_ACCEPTANCE.md — 迭代记录。

## 验证状态与边界

- GitHub Actions 的 Python tests 工作流已通过：对 main 提交执行依赖安装与 pytest -q，结果 success。
- TypeScript/Vitest 测试源已提交，但尚未运行。
- SQL migration 尚未在 PostgreSQL 中实际应用。
- AIHOT 代码是集成脚手架，尚未在某个具体 AIHOT checkout 中注册、编译和端到端运行。
- 当前没有自动视频发现/下载/定时任务，没有 Analyzer 身份认证，也没有经过人工金标集验证的 VLM 评分质量结论。

**安全提示：** 当前服务仅适用于本机或受控内网开发，不能直接暴露到公网。共享部署前必须补上认证授权、存储与保留策略、访问审计，并确认视频素材具有处理权限。正式排名必须以同场景、同 Rubric 版本、证据充分且人工审核通过的记录为基础。

## 相关文档

- [Technical plan](docs/TECHNICAL_PLAN.md)
- [Sprint 0 baseline](docs/SPRINT0_BASELINE.md)
- [Sprint 1 acceptance](docs/SPRINT1_ACCEPTANCE.md)
- [Sprint 2 acceptance](SPRINT2_ACCEPTANCE.md)
- [AIHOT integration scaffold](integrations/aihot-module/cockpit-benchmark/README.md)
