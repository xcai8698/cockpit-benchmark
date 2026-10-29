# Cockpit Benchmark

座舱竞品体验 Benchmark MVP：把经授权的座舱视频转成带时间戳、可追溯的证据帧与结构化分析报告。当前交付是独立 Analyzer 原型和 AIHOT 集成骨架，**还不是生产可用的自动采集/排行榜系统**。

## 当前能力

- 本地上传 MP4、MOV、M4V、MKV、WEBM、AVI 视频。
- 通过 FFprobe 检查时长，通过 FFmpeg 抽帧。
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
