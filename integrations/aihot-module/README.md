# AIHOT Integration Skeleton

此目录提供将 Analyzer 接入 AIHOT 的集成骨架与契约示例，尚未在 AIHOT 源码 checkout 中完成编译和运行验证。

## Contents
- `cockpit-benchmark/src/module-contract.ts`: 模块元数据/路由契约草案
- `cockpit-benchmark/src/analyzer-client.ts`: Analyzer HTTP API client
- `cockpit-benchmark/src/review-policy.ts`: 评分审核和排行榜准入策略
- `cockpit-benchmark/migrations/0001_cockpit_benchmark.sql`: 数据库迁移草案
- `cockpit-benchmark/tests/review-policy.test.ts`: 策略单元测试

## Integration steps
1. 将模块目录放入 AIHOT 的 `modules/cockpit-benchmark/`。
2. 按当前 AIHOT checkout 的 `ServerModule`/`WebModule` 类型修正导入与注册。
3. 在 `site/modules/index.ts`、`site/modules/server.ts`、`site/modules/web.ts` 注册模块。
4. 运行类型检查、迁移和端到端测试。
5. 配置企业认证与权限；禁止无身份认证的审核端点直接暴露。
