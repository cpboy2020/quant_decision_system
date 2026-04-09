# 🚀 量化交易分析系统 (Quantitative Decision System)

一个专业级的量化交易分析系统，集成了机器学习、风险管理、实时监控和自动化交易功能。

## 📊 系统概览

**量化交易分析系统**是一个完整的量化交易解决方案，支持从数据获取、策略研发、回测验证到实盘交易的全流程自动化。系统采用模块化设计，支持多市场、多策略并行运行。

### ✨ 核心特性

- **📈 多市场支持**: A股、港股、美股、期货、加密货币
- **🤖 机器学习集成**: LightGBM + Optuna超参数优化 + SHAP可解释性
- **🛡️ 高级风险管理**: 动态风险控制、仓位管理、止损止盈
- **📊 实时监控**: Prometheus + Grafana监控面板，实时性能指标
- **🔧 容器化部署**: Docker + Kubernetes，支持云原生部署
- **🧪 完整测试**: 单元测试、集成测试、回测验证
- **⚡ 高性能**: 异步处理、缓存机制、批量操作

## 🏗️ 系统架构

```
quant_decision_system/
├── core/              # 核心接口和抽象类
├── data/              # 数据获取和预处理
│   └── providers/     # 数据源接口 (iFind、Tushare等)
├── ml/                # 机器学习模块
│   └── pipeline.py    # ML训练和推理管道
├── strategies/        # 交易策略库
│   ├── base.py        # 策略基类
│   └── momentum.py    # 动量策略示例
├── execution/         # 交易执行
│   ├── gateway.py     # 交易网关接口
│   └── connector.py   # 网关连接器
├── risk/              # 风险管理
│   └── manager.py     # 风险管理系统
├── backtest/          # 回测引擎
│   ├── engine.py      # 回测核心引擎
│   └── walkforward.py # 前向滚动验证
├── monitoring/        # 系统监控
│   ├── metrics.py     # 性能指标收集
│   └── model_decay.py # 模型衰减监控
├── config/            # 配置文件
├── infra/             # 基础设施
│   ├── docker/        # Docker配置
│   ├── k8s/          # Kubernetes部署
│   └── grafana/       # 监控面板
├── tests/             # 测试套件
├── scripts/           # 工具脚本
└── main.py           # 系统入口
```

## 🚀 快速开始

### 环境要求

- Python 3.11+
- Docker 20.10+ (可选)
- 8GB+ RAM (推荐16GB)
- 20GB+ 磁盘空间

### 安装步骤

1. **克隆仓库**
   ```bash
   git clone https://github.com/cpboy2020/quant_decision_system.git
   cd quant_decision_system
   ```

2. **创建虚拟环境**
   ```bash
   make venv
   ```

3. **安装依赖**
   ```bash
   make install-dev
   ```

4. **运行质量检查**
   ```bash
   make qa
   ```

### 运行系统

#### 模拟盘模式 (推荐用于测试)
```bash
make run-sim
```

#### 回测模式
```bash
make backtest
```

#### Docker运行
```bash
docker-compose -f docker-compose.dev.yml up
```

## 📈 功能模块详解

### 1. 数据获取模块 (`data/providers/`)

支持多种数据源：
- **iFind数据接口**: 专业的金融数据服务
- **Tushare**: 免费的A股数据
- **缓存机制**: 自动缓存，减少API调用
- **重试逻辑**: 网络异常自动重试

### 2. 机器学习模块 (`ml/pipeline.py`)

- **特征工程**: 自动特征提取和选择
- **模型训练**: LightGBM梯度提升树
- **超参数优化**: Optuna自动调参
- **模型解释**: SHAP特征重要性分析
- **模型监控**: 实时监控模型性能衰减

### 3. 风险管理模块 (`risk/manager.py`)

- **仓位管理**: 动态仓位调整
- **止损止盈**: 多级止损策略
- **风险暴露**: 实时风险敞口监控
- **压力测试**: 极端市场情景模拟

### 4. 交易执行模块 (`execution/`)

- **多网关支持**: QMT、PTrade、CTP、IB等
- **订单管理**: 智能订单路由
- **执行算法**: TWAP、VWAP等算法交易
- **错误处理**: 完善的异常处理机制

### 5. 监控系统 (`monitoring/`)

- **实时指标**: Prometheus指标收集
- **告警系统**: AlertManager实时告警
- **可视化**: Grafana监控面板
- **日志系统**: 结构化日志记录

## 🔧 开发指南

### 代码规范
- 使用 `make lint` 进行代码格式化
- 使用 `make type-check` 进行类型检查
- 遵循 PEP 8 编码规范

### 测试
```bash
# 运行所有测试
make test

# 运行测试并生成覆盖率报告
make test-cov

# 运行回测
make backtest
```

### 添加新策略
1. 在 `strategies/` 目录创建新策略文件
2. 继承 `StrategyBase` 基类
3. 实现 `generate_signals` 方法
4. 添加单元测试

## 🐳 容器化部署

### Docker构建
```bash
docker build -t quant-system:latest .
```

### Docker Compose开发环境
```bash
docker-compose -f docker-compose.dev.yml up
```

### Kubernetes部署
```bash
# 部署到Kubernetes集群
kubectl apply -k infra/k8s/production/
```

## 📊 监控与告警

系统内置完整的监控体系：

### 监控指标
- **系统指标**: CPU、内存、磁盘使用率
- **交易指标**: 成交率、滑点、延迟
- **策略指标**: 夏普比率、最大回撤、胜率
- **模型指标**: 预测准确率、特征重要性

### 访问监控面板
1. 启动系统后访问: http://localhost:3000 (Grafana)
2. 默认用户名/密码: admin/admin
3. 查看Prometheus指标: http://localhost:9090

## 🔐 安全特性

- **密钥管理**: 环境变量加密存储
- **访问控制**: 基于角色的权限管理
- **审计日志**: 完整的操作日志记录
- **漏洞扫描**: 定期安全扫描

## 📚 文档

- [API文档](./docs/api.md) - 系统API接口说明
- [部署指南](./docs/deployment.md) - 生产环境部署指南
- [策略开发](./docs/strategy_development.md) - 策略开发教程
- [故障排除](./docs/troubleshooting.md) - 常见问题解决

## 🤝 贡献指南

1. Fork 本仓库
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

## 📄 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情

## 📞 支持与联系

如有问题或建议，请通过以下方式联系：

- GitHub Issues: [问题反馈](https://github.com/cpboy2020/quant_decision_system/issues)
- 邮箱: [项目维护者邮箱]

## 🎯 路线图

- [ ] 支持更多数据源 (Bloomberg、Wind等)
- [ ] 添加深度学习模型 (LSTM、Transformer)
- [ ] 实现分布式回测引擎
- [ ] 开发Web管理界面
- [ ] 支持更多交易市场 (期权、外汇)

---

**⚠️ 风险提示**: 量化交易存在风险，请在充分理解系统原理和风险的前提下使用。建议先在模拟盘环境中充分测试，再考虑实盘交易。

**📈 祝您交易顺利！**