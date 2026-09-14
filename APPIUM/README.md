# Appium 可视化自动化测试平台

> 基于 Flask + Appium 的 Android 自动化测试 Web 平台，支持 USB/WiFi 连接设备、实时截图、UI元素抓取、可视化脚本编排、脚本一键生成与执行。

---

## 项目简介

这是一个分层架构清晰、稳定可靠的内部自动化测试平台。经过完整重构后，项目具备以下能力：

- **设备管理**：USB/WiFi 双模式连接、ADB 自动管理、Appium Server 生命周期管理、心跳保活
- **截图与元素**：实时屏幕截图、UI 元素树抓取、元素定位、高亮标注
- **脚本编排**：可视化拖拽编排测试步骤、支持 10+ 种动作（click/swipe/input/press/wait/back/home 等）
- **脚本生成**：一键生成可独立运行的 Appium Python 测试脚本，支持下载和内联执行
- **数据持久化**：SQLite 数据库 + JSON 双存储，测试用例 CRUD
- **模拟模式**：无真实设备时可用模拟模式演示和测试平台功能
- **稳定性保障**：DriverProxy 重试机制、渐进式恢复、线程安全、全局错误处理

## 技术栈

| 组件 | 版本 | 说明 |
|------|------|------|
| Python | 3.12+ | 后端语言 |
| Flask | 3.0.3 | Web 框架 |
| SQLAlchemy | 2.0+ | ORM 数据持久化 |
| Appium Python Client | 4.x | Appium 客户端 |
| Node.js | 22+ | Appium 运行时环境 |
| Appium | 3.x | 移动端自动化框架 |
| UiAutomator2 | 8.x | Android 驱动 |
| pytest | 8.x | 自动化测试框架 |

## 项目架构

```
APPIUM/
├── app.py                              # Flask 主入口（工厂模式 create_app）
├── config.yaml                         # 应用配置
├── requirements.txt                    # Python 依赖清单
├── pytest.ini                          # pytest 配置
├── run_tests.py                        # 测试运行脚本
├── environment_check.py                # 环境自检工具
├── generate_mock_screenshot.py         # 模拟截图生成工具
│
├── backend/                            # ========== 后端核心 ==========
│   ├── api/                            # API 层（Flask Blueprint）
│   │   ├── device.py                   #   设备管理 API
│   │   ├── element.py                  #   元素/截图 API
│   │   ├── script.py                   #   脚本编排/生成 API
│   │   ├── health.py                   #   健康检查 API
│   │   ├── response.py                 #   统一响应格式
│   │   ├── errors.py                   #   全局错误处理
│   │   ├── cors.py                     #   CORS 跨域支持
│   │   └── service_registry.py         #   服务注册/获取
│   │
│   ├── services/                       # Service 层（业务逻辑）
│   │   └── screenshot_service.py       #   截图处理服务
│   │
│   ├── device_manager/                 # Manager 层（设备管理）
│   │   ├── manager.py                  #   DeviceManager 核心编排器
│   │   ├── adb_client.py               #   ADB 客户端封装
│   │   ├── appium_server.py            #   Appium Server 生命周期管理
│   │   ├── driver_proxy.py             #   WebDriver 代理（重试/恢复）
│   │   ├── driver_pool.py              #   Driver 实例池/连接监听
│   │   ├── device_discovery.py         #   设备发现（USB/WiFi扫描）
│   │   └── udid.py                     #   UDID 解析工具
│   │
│   ├── appium_manager/                 # Appium 管理
│   │   ├── appium_server.py            #   Appium Server 进程管理
│   │   └── capabilities.py             #   Desired Capabilities 构建
│   │
│   ├── repositories/                   # 数据层（Repository 模式）
│   │   ├── test_case_repository.py     #   测试用例 CRUD
│   │   ├── device_repository.py        #   设备/会话 CRUD
│   │   └── element_repository.py       #   元素快照/定位器 CRUD
│   │
│   ├── models/                         # 数据模型（SQLAlchemy ORM）
│   │   ├── base.py                     #   Base 模型基类
│   │   ├── test_case.py                #   测试用例模型
│   │   ├── device.py                   #   设备模型
│   │   ├── appium_session.py           #   Appium 会话模型
│   │   ├── element_snapshot.py         #   元素快照模型
│   │   ├── element.py                  #   元素模型
│   │   ├── element_map.py              #   元素定位器模型
│   │   ├── execution_record.py         #   执行记录模型
│   │   ├── script.py                   #   脚本模型
│   │   ├── app.py                      #   应用模型
│   │   └── system_config.py            #   系统配置模型
│   │
│   ├── database/                       # 数据库
│   │   ├── db.py                       #   数据库引擎/Session管理
│   │   └── migrate_json_cases.py       #   JSON→DB 迁移工具
│   │
│   └── utils/                          # 工具模块
│       ├── logger.py                   #   统一日志配置
│       ├── config.py                   #   YAML 配置加载
│       ├── paths.py                    #   路径常量管理
│       ├── adb.py                      #   ADB 路径解析
│       └── exceptions.py              #   自定义异常
│
├── drivers/                            # ========== 驱动层 ==========
│   └── appium_driver.py                # Appium Driver 兼容层
│
├── services/                           # ========== Service Facade 层 ==========
│   ├── device_service.py               # 设备服务 Facade
│   ├── element_service.py              # 元素/截图服务 Facade
│   ├── script_design_service.py        # 脚本编排服务
│   └── script_gen_service.py           # 脚本生成/执行服务
│
├── tests/                              # ========== 测试 ==========
│   ├── conftest.py                     # pytest fixtures
│   ├── unit/                           # 单元测试
│   │   ├── test_api_response.py        #   API 响应工具测试
│   │   ├── test_repositories.py        #   Repository CRUD 测试
│   │   └── test_services.py            #   Service 业务逻辑测试
│   └── integration/                    # 集成测试
│       └── test_api.py                 #   HTTP 接口全链路测试
│
├── static/                             # 前端静态资源
│   ├── css/style.css
│   └── js/main.js
├── templates/
│   └── index.html                      # 前端单页应用
│
├── bin/                                # 自带工具
│   ├── adb.exe                         # ADB v1.0.41
│   ├── AdbWinApi.dll
│   └── AdbWinUsbApi.dll
│
└── data/                               # 运行时数据（自动创建）
    ├── appium_test.db                  # SQLite 数据库
    ├── screenshots/                    # 截图
    ├── generated_scripts/              # 生成的测试脚本
    ├── test_cases/                     # JSON 用例备份
    ├── logs/                           # 日志
    └── backups/                        # 迁移备份
```

---

## 快速开始

### 1. 环境检查

```powershell
# 运行环境自检
.\venv\Scripts\python.exe environment_check.py
```

### 2. 启动服务

```powershell
# 方式一：直接启动（Flask 会自动管理 Appium Server 生命周期）
.\venv\Scripts\python.exe app.py
```

启动后访问 http://127.0.0.1:5001

### 3. 运行测试

```powershell
# 运行全部 80 个测试
python run_tests.py

# 仅单元测试
python run_tests.py unit

# 仅集成测试
python run_tests.py integration
```

---

## API 文档

### 设备管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/device/status` | 获取设备连接状态 |
| POST | `/api/connect` | 连接设备（JSON: `{method, device_name, pair_code?}`） |
| POST | `/api/disconnect` | 断开设备 |
| POST | `/api/mock/enable` | 启用模拟模式 |
| POST | `/api/mock/disable` | 退出模拟模式 |
| GET | `/api/devices/scan` | 扫描可用设备 |
| GET | `/api/device/keepalive` | 心跳保活状态 |
| GET | `/api/diagnostics` | ADB/Appium 诊断信息 |

### 截图与元素

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/screenshot` | 获取当前截图（PNG） |
| POST | `/api/elements/refresh` | 刷新 UI 元素树 |
| POST | `/api/screenshot/highlight` | 标注元素高亮（JSON: `{bounds}`） |
| POST | `/api/elements/locate` | 坐标定位元素（JSON: `{x, y}`） |

### 脚本编排

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/script/actions` | 获取支持的动作类型 |
| GET | `/api/script/design` | 获取当前编排设计 |
| POST | `/api/script/clear` | 清空编排设计 |
| GET | `/api/script/elements` | 获取已添加元素 |
| POST | `/api/script/elements` | 添加元素（JSON: 元素对象） |
| POST | `/api/script/steps` | 添加步骤（JSON: `{element?, action, action_params?, description?}`） |
| POST | `/api/script/steps/reorder` | 重排步骤 |
| GET | `/api/script/cases` | 列出已保存用例 |
| POST | `/api/script/save` | 保存用例（JSON: `{name}`） |
| GET | `/api/script/load/<name>` | 加载用例 |
| GET | `/api/script/gen/preview?name=xxx` | 预览生成脚本 |
| GET | `/api/script/gen/download?name=xxx` | 下载生成脚本 |
| POST | `/api/script/gen/execute` | 内联执行脚本 |
| GET | `/api/script/gen/status` | 获取执行状态 |
| POST | `/api/script/gen/stop` | 停止执行 |

---

## 部署指南（新机器部署）

### 前置要求

- Python 3.12+
- Node.js 22+
- Android 手机（开启开发者选项和 USB/WiFi 调试）

### 步骤

```powershell
# 1. 创建虚拟环境并安装依赖
python -m venv venv
.\venv\Scripts\pip.exe install --upgrade pip
.\venv\Scripts\pip.exe install -r requirements.txt

# 2. 安装 Appium
npm install -g appium
appium driver install uiautomator2

# 3. MIUI 兼容补丁（小米/红米手机必需）
# 编辑文件：%USERPROFILE%\.appium\node_modules\appium-uiautomator2-driver\node_modules\io.appium.settings\build\lib\client.js
#   - async isRunningInForeground() 方法体改为 return true;
#   - 注释掉 requireRunning 中的 else if (await this.isRunningInForeground()) 分支

# 4. 启动服务
.\venv\Scripts\python.exe app.py
```

---

## 手机连接方式

### USB 连接
1. 手机开启 USB 调试
2. USB 线连接电脑
3. 平台选择 USB，点击"连接设备"

### WiFi 连接（Android 11+）
1. 手机与电脑在同一局域网
2. 开启「开发者选项 → 无线调试」
3. 点击「使用配对码配对设备」
4. 电脑执行：`.\bin\adb.exe pair <IP:配对端口> <配对码>`
5. 配对成功后：`.\bin\adb.exe connect <IP:连接端口>`
6. 平台选择 WiFi，输入 `<IP:连接端口>`，点击"连接设备"

---

## 测试

项目包含 **80 个测试用例**，覆盖单元测试和集成测试：

```
tests/
├── unit/test_api_response.py  (14 tests) - 统一响应格式
├── unit/test_repositories.py  (12 tests) - 数据层 CRUD
├── unit/test_services.py      (17 tests) - Service 业务逻辑
└── integration/test_api.py    (37 tests) - HTTP 接口全链路
```

运行测试：`python run_tests.py`

---

## 常见问题

**Q: 连接后显示"模拟数据"？**
A: Appium 连接失败。检查 Appium Server 是否运行（`GET /api/diagnostics`），ADB 设备是否在线。

**Q: WiFi 连接超时？**
A: 确保手机和电脑在同一局域网，信号良好。可尝试先手动 `adb pair` 再在平台连接。

**Q: 截图黑屏或元素为空？**
A: Appium Settings 服务可能未启动，尝试在手机上手动打开 io.appium.settings，或重启无线调试。

**Q: 端口被占用？**
A: 修改 `config.yaml` 中的端口配置。

---

## 架构分层原则

```
API 层 (Blueprint)     → 参数校验、统一响应格式、HTTP 状态码
    ↓
Service 层 (Facade)    → 业务编排、异常保护、线程安全
    ↓
Manager 层             → 设备管理、Driver生命周期、心跳保活、重试恢复
    ↓
Repository 层          → 数据持久化、DB/JSON 双存储
    ↓
Infrastructure 层      → ADB Client、Appium Server、Logger、Config
```
