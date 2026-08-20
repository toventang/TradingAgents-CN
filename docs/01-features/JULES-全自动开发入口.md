# Google Jules 全自动开发入口

本目录中的功能规格是业务与技术事实源，不应一次性作为一个Jules任务提交。

Jules专用入口：

- 仓库规则：../../AGENTS.md
- 使用说明：../jules/README.md
- 自动调度与PR协议：../jules/AUTOMATION.md
- 机器可读任务DAG：../jules/task-manifest.json
- 原子任务包：../jules/tasks/
- Ubuntu环境脚本：../../scripts/jules/setup.sh

执行规则：

1. 每个Jules会话只执行一个任务ID。
2. 依赖任务PR合并后才能启动下游任务。
3. 高风险任务必须审批计划。
4. Jules可以自动创建PR，但合并前必须通过任务包规定的验证。
5. 任何单个任务都不得声称六项功能整体完成。
