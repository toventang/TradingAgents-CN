# TradingAgents-CN 项目快速参考指南

**快速导航**: 项目核心信息速查表  
**最后更新**: 2026年7月17日

---

## 📚 核心文档导航

| 文档 | 用途 | 位置 |
|------|------|------|
| **PROJECT_ANALYSIS.md** | 项目完整分析报告 | `/项目根目录/` |
| **TECHNICAL_DEEP_DIVE.md** | 技术深度解析 | `/项目根目录/` |
| **README.md** | 项目主文档 | `/项目根目录/` |
| 架构文档 | 系统架构设计 | `/docs/architecture/` |
| API 文档 | API 端点说明 | `/docs/api/` |
| 部署指南 | Docker 部署 | `/docs/deployment/` |

---

## 🚀 快速启动

### 前置要求
```bash
# 系统要求
- Python >= 3.10
- Docker & Docker Compose
- Node.js >= 16 (前端)
- MongoDB (可选，Docker 提供)
- Redis (可选，Docker 提供)
```

### 开发环境启动

```bash
# 1. 克隆项目
git clone https://github.com/hsliuping/TradingAgents-CN.git
cd TradingAgents-CN

# 2. 启动 Docker 容器
docker-compose up -d

# 3. 安装 Python 依赖
pip install -r requirements.txt

# 4. 安装前端依赖
cd frontend
npm install

# 5. 启动前端开发服务器
npm run dev

# 6. 在另一个终端启动后端
cd ..
python main.py
```

### 访问应用
- 前端: http://localhost:5173
- 后端 API: http://localhost:8000
- API 文档: http://localhost:8000/docs

---

## 🏗️ 项目结构速查

```
TradingAgents-CN/
├── app/                    # 后端 FastAPI 应用
│   ├── core/              # 配置、数据库、日志
│   ├── routers/           # 26+ API 端点
│   ├── services/          # 25+ 业务逻辑服务
│   ├── models/            # 数据模型
│   └── worker.py          # 异步任务处理
│
├── tradingagents/         # 多智能体引擎
│   ├── graph/             # LangGraph 图结构
│   ├── agents/            # 5 类智能体
│   └── llm_clients/       # LLM 集成
│
├── frontend/              # Vue3 前端应用
│   ├── src/
│   │   ├── views/         # 15+ 页面
│   │   ├── components/    # 30+ 可复用组件
│   │   ├── api/           # 20+ API 接口
│   │   └── stores/        # Pinia 状态
│   └── vite.config.ts
│
├── docs/                  # 100+ 文档
├── config/                # 配置文件
├── scripts/               # 运维脚本
└── docker/                # Docker 配置
```

---

## 🔑 关键特性速查

### 后端特性

| 特性 | 描述 | 文件 |
|------|------|------|
| **分析引擎** | 多智能体股票分析 | `app/services/analysis_service.py` |
| **数据源** | Tushare/AkShare/BaoStock 集成 | `app/services/data_sources/` |
| **任务队列** | Redis 基础的异步任务系统 | `app/services/queue_service.py` |
| **认证授权** | JWT + 角色权限管理 | `app/routers/auth_db.py` |
| **实时推送** | SSE + WebSocket | `app/routers/sse.py` |
| **缓存管理** | 多层缓存策略 | `app/services/cache.py` |
| **进度跟踪** | Redis Pub/Sub 进度追踪 | `app/services/redis_progress_tracker.py` |

### 前端特性

| 特性 | 描述 | 位置 |
|------|------|------|
| **分析页面** | 股票分析表单与结果展示 | `frontend/src/views/Analysis/` |
| **仪表板** | 用户统计和快速访问 | `frontend/src/views/Dashboard/` |
| **股票筛选** | 多维度股票筛选 | `frontend/src/views/Screening/` |
| **配置管理** | LLM 和数据源配置 | `frontend/src/views/Settings/` |
| **报告导出** | PDF/Word 报告导出 | `frontend/src/views/Reports/` |
| **模拟交易** | 虚拟交易模拟 | `frontend/src/views/PaperTrading/` |

---

## 💻 常用命令

### 后端命令

```bash
# 启动 FastAPI 服务
python main.py

# 启动 Worker 进程
python -m app.worker

# 数据库迁移
python -m app.scripts.migrate_db

# 初始化数据源
python cli/main.py init tushare

# 运行测试
pytest tests/ -v

# 生成 API 文档
python -m app.scripts.generate_api_docs
```

### 前端命令

```bash
# 开发模式
npm run dev

# 生产构建
npm run build

# 预览构建结果
npm run preview

# 代码检查
npm run lint

# 代码格式化
npm run format
```

### Docker 命令

```bash
# 启动所有容器
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止所有容器
docker-compose down

# 重启特定服务
docker-compose restart backend

# 查看容器状态
docker-compose ps
```

---

## 🔌 API 端点速查

### 分析相关
```
POST   /analysis/analyze              # 创建分析任务
GET    /analysis/{id}                 # 获取分析结果
GET    /analysis/list                 # 获取分析历史
POST   /analysis/batch                # 批量分析
POST   /analysis/{id}/cancel          # 取消分析
```

### 股票数据
```
GET    /stocks/{symbol}               # 获取股票信息
GET    /stocks/list                   # 股票列表
GET    /stock-data/history            # 历史数据
GET    /stock-data/indicators         # 技术指标
```

### 配置管理
```
GET    /config/llm-providers          # LLM 供应商列表
GET    /config/models                 # 可用模型
POST   /config/update                 # 更新配置
GET    /config/data-sources           # 数据源配置
```

### 实时推送
```
GET    /sse/stream/{task_id}          # SSE 流
WS     /ws/notifications              # WebSocket 连接
```

### 系统管理
```
GET    /health                        # 健康检查
GET    /health/db                     # 数据库状态
GET    /logs/operations               # 操作日志
GET    /cache/stats                   # 缓存统计
```

---

## 🗄️ 数据库模型速查

### 核心集合

| 集合 | 用途 | 关键字段 |
|------|------|---------|
| `analysis_results` | 分析结果 | `user_id`, `stock_symbol`, `timestamp` |
| `users` | 用户数据 | `username`, `email`, `role` |
| `stock_basic_info` | 股票基础 | `symbol`, `name`, `list_date` |
| `sync_status` | 同步状态 | `job_key`, `status`, `finished_at` |
| `operation_logs` | 操作日志 | `user_id`, `action`, `timestamp` |
| `config` | 系统配置 | `config_type`, `config_key` |
| `cache` | 缓存数据 | `key`, `value`, `ttl` |

---

## 🔐 环境变量配置

### 关键环境变量

```bash
# 服务器配置
HOST=0.0.0.0
PORT=8000
DEBUG=true

# MongoDB
MONGODB_HOST=localhost
MONGODB_PORT=27017
MONGODB_DATABASE=tradingagentscn
MONGODB_USERNAME=
MONGODB_PASSWORD=

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=

# LLM 配置
LLM_PROVIDER=openai
OPENAI_API_KEY=your-key-here
GOOGLE_API_KEY=your-key-here

# 数据源 API
TUSHARE_TOKEN=your-token-here

# JWT 配置
JWT_SECRET=your-secret-key
JWT_ALGORITHM=HS256
JWT_EXPIRATION=3600
```

---

## 🐛 常见问题

### Q: 如何切换 LLM 提供商？
**A**: 在配置页面或通过 API 设置 `llm_provider`，支持的值有:
- `openai` (默认)
- `google` 
- `anthropic`
- `aihubmix` (聚合提供商)

### Q: 如何优化分析速度？
**A**: 
1. 减少分析师数量: `selected_analysts` 参数
2. 使用快速模型: `quick_think_llm=gpt-4o-mini`
3. 减少辩论轮数: `max_debate_rounds=0`

### Q: 如何处理数据同步失败？
**A**: 
1. 检查数据源 API 密钥
2. 查看同步日志: `/logs/system`
3. 手动触发同步: `POST /stock-sync/trigger`
4. 检查多级回退链路状态

### Q: 如何启用 WebSocket？
**A**: 连接到 `ws://localhost:8000/ws/notifications`，发送消息订阅频道

### Q: 前端无法连接后端？
**A**:
1. 确认后端正在运行: `curl http://localhost:8000/health`
2. 检查 CORS 配置: `ALLOWED_ORIGINS`
3. 检查防火墙设置

---

## 📈 性能参数调优

### FastAPI 服务器
```python
# uvicorn 配置
workers = 4              # 工作进程数
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 120            # 请求超时（秒）
keepalive = 5            # 连接保活（秒）
```

### MongoDB 连接
```python
MONGO_MAX_CONNECTIONS = 100
MONGO_MIN_CONNECTIONS = 10
MONGO_CONNECT_TIMEOUT_MS = 30000   # 30 秒
MONGO_SOCKET_TIMEOUT_MS = 60000    # 60 秒
```

### Redis 配置
```bash
maxmemory = 256mb        # 最大内存
maxmemory-policy = allkeys-lru  # 淘汰策略
timeout = 0              # 客户端超时
```

---

## 🎓 学习资源

### 官方文档
- [系统架构文档](../docs/architecture/system-architecture.md)
- [API 参考](../docs/api/api-reference.md)
- [部署指南](../docs/deployment/deployment-guide.md)
- [故障排除](../docs/troubleshooting/common-issues.md)

### 外部资源
- [LangGraph 官方文档](https://langchain-ai.github.io/langgraph/)
- [FastAPI 官方文档](https://fastapi.tiangolo.com/)
- [Vue 3 官方文档](https://vuejs.org/)
- [MongoDB 官方文档](https://docs.mongodb.com/)

### 学习中心
- [项目内学习中心](../docs/learning/)
- [提示词工程指南](../docs/learning/prompt-engineering.md)
- [模型选择指南](../docs/learning/model-selection.md)

---

## 🤝 贡献指南

### 代码贡献流程
1. Fork 项目
2. 创建特性分支: `git checkout -b feature/new-feature`
3. 提交更改: `git commit -m "Add new feature"`
4. 推送到分支: `git push origin feature/new-feature`
5. 创建 Pull Request

### 代码规范
- Python: PEP 8
- TypeScript: ESLint + Prettier
- 提交消息: `[类型] 描述` (e.g., `[feature] Add analysis result export`)

### 测试要求
- 单元测试覆盖率 > 70%
- 集成测试通过
- 代码审查批准

---

## 📞 获取帮助

| 渠道 | 信息 |
|------|------|
| **GitHub Issues** | https://github.com/hsliuping/TradingAgents-CN/issues |
| **官方邮箱** | hsliup@163.com |
| **微信公众号** | TradingAgents-CN |
| **讨论区** | GitHub Discussions |

---

## 📝 版本信息

```
项目名: TradingAgents-CN
版本: v1.0.1
Python: 3.10+
Node.js: 16+
许可证: Apache 2.0 (开源) + 商业授权 (app/frontend)
维护者: hsliuping
最后更新: 2026-07-17
```

---

## 🗺️ 路线图

### v1.0.1 (当前稳定版)
- ✅ 配置管理优化
- ✅ 聚合厂家支持
- ✅ 页面切换修复
- ✅ 单股同步增强

### v1.1 (计划中)
- 🔄 高级筛选功能
- 🔄 AI 辅助提示词
- 🔄 更多数据源

### v2.0 (开发中)
- 🔜 完整商业化版本
- 🔜 增强的模型管理
- 🔜 企业级功能

---

**最后更新**: 2026-07-17  
**维护者**: hsliuping  
**许可证**: 查看 [LICENSE](../LICENSE)

