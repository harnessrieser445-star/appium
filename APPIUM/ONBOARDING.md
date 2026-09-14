# Appium 自动化测试平台 · 新机部署与上手指南

> 目标读者：拿到本项目源码、要在新机器上把它跑起来并参与开发的程序员。
> 本文件是对 `README.md` 的"事实校准版"——README 有几处过时（动作类型数量、依赖版本、`appium_server.py` 路径），本文以源码现状为准。

---

## 0. 一句话定位

**Flask + Appium 的 Android 自动化测试 Web 平台**：浏览器里编排测试步骤 → 一键生成独立 Python 脚本 / 内联执行 → 真机或模拟模式跑用例。端口 5001。

---

## 1. 技术栈与实际版本（来自 `requirements.txt` 与运行环境实测）

| 组件 | 实际版本 | 备注 |
|------|---------|------|
| Python | 3.12.10（venv 实测） | `environment_check.py` 要求 ≥ 3.10 |
| Flask | 3.0.3 | Web 框架 |
| Flask-SQLAlchemy | ~3.1 | ORM |
| Appium-Python-Client | **5.0.0** | ⚠️ README 写"4.x"已过时 |
| selenium | ≥ 4.26, < 5.0 | W3C Actions 依赖 |
| PyYAML | 6.0.1 | 配置 |
| Pillow | 10.3.0 | 截图高亮 |
| lxml | 5.2.1 | page_source 解析 |
| Node.js | v22.22.2（实测） | Appium 运行时 |
| Appium | 3.x + UiAutomator2 driver | 全局 npm 安装 |
| ADB | 1.0.41 (36.0.0) | **项目自带** `bin/adb.exe` |

---

## 2. 新机部署 · 三步

```powershell
# 1. Python 虚拟环境 + 依赖
cd C:\path\to\APPIUM\APPIUM
python -m venv venv
.\venv\Scripts\pip.exe install --upgrade pip
.\venv\Scripts\pip.exe install -r requirements.txt

# 2. Appium（全局）
npm install -g appium
appium driver install uiautomator2

# 3. 启动
.\venv\Scripts\python.exe app.py
# 或外层 start.bat（自动用 venv 启动）
```

启动后访问 `http://127.0.0.1:5001`。

### MIUI 兼容补丁（小米/红米手机必需）

文件：`%USERPROFILE%\.appium\node_modules\appium-uiautomator2-driver\node_modules\io.appium.settings\build\lib\client.js`

- `async isRunningInForeground()` 方法体改为 `return true;`
- 注释掉 `requireRunning` 中的 `else if (await this.isRunningInForeground())` 分支

不改此补丁，小米设备会频繁弹"正在运行"通知或截图失败。

### 环境自检

```powershell
.\venv\Scripts\python.exe environment_check.py
```

检测项：Python 版本 / pip 依赖 / 项目目录结构 / ADB 存在 / ADB 设备连接。

---

## 3. 项目结构地图（**实际**路径，纠正 README 过时点）

```
APPIUM/                                # 外层容器
├── start.bat                          # 启动器（cd 进 APPIUM/ 调 venv python app.py）
└── APPIUM/                            # 项目本体
    ├── app.py                         # Flask 入口（create_app 工厂）
    ├── config.yaml                    # 配置
    ├── requirements.txt               # 依赖
    ├── environment_check.py           # 环境自检
    ├── run_tests.py                   # 测试运行器
    │
    ├── backend/                       # 后端
    │   ├── api/                        # Blueprint 路由层
    │   │   ├── device.py  element.py  script.py  health.py
    │   │   ├── response.py            #   统一响应
    │   │   ├── errors.py              #   全局错误处理
    │   │   ├── cors.py                #   CORS
    │   │   └── service_registry.py    #   服务注册/获取
    │   ├── services/                  # 后端子服务
    │   │   └── screenshot_service.py  #   截图处理（PIL 高亮）
    │   ├── device_manager/            # 设备管理
    │   │   ├── manager.py             #   DeviceManager 核心编排器
    │   │   ├── adb_client.py           #   ADB 封装（pair/connect_wifi/list_devices）
    │   │   ├── device_discovery.py     #   设备发现（USB/WiFi/mDNS）
    │   │   ├── driver_proxy.py         #   WebDriver 代理（重试/恢复）
    │   │   ├── driver_pool.py           #   Driver 实例池
    │   │   └── udid.py                 #   UDID 解析
    │   ├── appium_manager/            # ⚠️ README 把这里错列在 device_manager/ 下
    │   │   ├── appium_server.py        #   Appium Server 进程管理
    │   │   └── capabilities.py         #   Desired Capabilities
    │   ├── repositories/              # 数据层
    │   │   ├── test_case_repository.py #   用例 CRUD（DB+JSON 双存储 + delete_case 双删）
    │   │   ├── device_repository.py
    │   │   └── element_repository.py
    │   ├── models/                    # ORM 模型
    │   │   ├── test_case.py            #   TestCase / TestStep（cascade='all, delete-orphan'）
    │   │   ├── device.py  appium_session.py  element_snapshot.py
    │   │   ├── element.py  element_map.py  execution_record.py
    │   │   ├── script.py  app.py  system_config.py
    │   │   └── base.py                 #   BaseModel 基类
    │   ├── database/
    │   │   ├── db.py                   #   init_db / 种子数据 / 自动迁移
    │   │   └── migrate_json_cases.py   #   JSON→DB 迁移工具
    │   └── utils/
    │       ├── logger.py  config.py  paths.py  adb.py  exceptions.py
    │
    ├── drivers/
    │   └── appium_driver.py          # 真实 Appium 会话创建点（_create_session:119）
    │
    ├── services/                     # Service Facade 层
    │   ├── device_service.py
    │   ├── element_service.py        #   元素抓取/解析/坐标反查
    │   ├── script_design_service.py  #   步骤编排 + SUPPORTED_ACTIONS 注册表 + 校验
    │   └── script_gen_service.py     #   脚本生成 + 内联执行 + 半坐标 click + press_hold
    │
    ├── tests/                        # 测试
    │   ├── conftest.py
    │   ├── unit/  (test_api_response / test_repositories / test_services)
    │   └── integration/test_api.py
    │
    ├── templates/index.html          # 前端单页（3 个 Tab）
    ├── static/js/main.js            # 前端交互（约 1050 行）
    ├── static/css/style.css
    │
    ├── bin/                           # 自带工具
    │   ├── adb.exe                    #   ADB v1.0.41
    │   └── AdbWinApi.dll  AdbWinUsbApi.dll
    │
    └── data/                          # 运行时数据（自动创建）
        ├── appium_test.db             #   SQLite 主存
        ├── test_cases/*.json          #   JSON 用例备份（与 DB 双写）
        ├── generated_scripts/*.py     #   生成脚本存档
        ├── screenshots/  test_screenshots/  logs/  backups/  exports/
```

---

## 4. 调用链与分层

```
前端 templates/index.html + static/js/main.js
  ↓ fetch
backend/api/*.py（Blueprint 路由，参数校验/统一响应）
  ↓
services/*.py（Facade，业务编排，线程安全）
  ↓
backend/device_manager/manager.py（DeviceManager 核心编排）
  ↓
drivers/appium_driver.py（真实 Appium 会话创建）
  ↓
backend/repositories/（DB/JSON 双存储）→ backend/models/（ORM）
```

退出清理：`app.py:152 _cleanup_on_exit`（断设备 + 停 Appium Server）。

---

## 5. 配置文件 `config.yaml`

| 段 | 作用 | 默认 |
|---|---|---|
| `app` | Flask host/port/debug | 127.0.0.1:5001 |
| `appium` | Appium Server 地址 + capabilities | 127.0.0.1:4723, UiAutomator2, newCommandTimeout 300 |
| `auto_refresh` | 前端截图自动刷新间隔 | 2000ms |
| `keepalive` | 心跳保活（间隔/auto_reconnect/重连次数/重连延迟） | 60s |
| `database.enabled` | 是否启用 SQLite 持久化（false=纯 JSON） | true |

---

## 6. 数据存储（**双存储**机制）

| 数据 | SQLite（主） | JSON（备份） |
|---|---|---|
| 用例 | `data/appium_test.db` 的 `test_cases` + `test_steps` + `element_snapshots` 三表 | `data/test_cases/<name>.json` |
| 设备/会话 | `devices` / `appium_sessions` 表 | — |
| 执行记录 | `execution_records` / `execution_step_results` | — |

关键事实：`save_case`（`test_case_repository.py:212`）**无论 DB 是否启用，JSON 始终写一份**作永久备份；`load_case` 优先 DB，DB 没有再读 JSON；`delete_case`（新增）SQLite 和 JSON **双删**，DB/JSON 任一失败不阻断另一边，幂等。

启动时若 DB 初始化失败，`app.py:86-119` 自动回退纯 JSON 模式，不会崩。

---

## 7. 支持的动作类型（**7 种**，非 README 写的"10+"）

| 动作 | 参数 | 用途 |
|---|---|---|
| `click` | — | 点击元素（已实现"半坐标方案"：优先 bounds 中心 tap，bounds 失效回退 find_element） |
| `input` | `value` | 输入文本 |
| `swipe` | `direction`(up/down/left/right) | 滑动屏幕（起点固定屏幕中心，500ms） |
| `press_hold` | `direction`, `hold`(秒), `strength`(可选 0.1-1.0 默认0.8) | 摇杆按住保持（机器人遥控） |
| `wait` | `timeout`(1-300 秒) | 等待 |
| `back` | — | 按返回键 |
| `screenshot` | — | 截图 |

注册表在 `services/script_design_service.py:25 SUPPORTED_ACTIONS`；校验在同文件 `_validate_step_params`。

---

## 8. 关键功能 → 代码位置速查

| 功能 | API 路由 | Service | 底层实现 |
|---|---|---|---|
| 连接设备 USB/WiFi | `POST /api/connect` | device_service.py:34 | manager.py:365 → appium_driver.py:179 |
| 模拟模式 | `POST /api/mock/enable\|disable` | device_service.py:69/80 | manager.py:224/254 |
| 心跳保活 | `GET /api/device/keepalive` | device_service.py:105 | manager.py:464-536 |
| 渐进式恢复 | — | — | manager.py:550（session→adb→server 三级） |
| 截图 | `GET /api/screenshot` | element_service.py:137 | manager.py:294 |
| 元素抓取/解析 | `POST /api/elements/refresh` | element_service.py:234 → 163 | page_source XML 解析 |
| 元素高亮 | `POST /api/screenshot/highlight` | — | screenshot_service.py:78（PIL 红框） |
| 坐标反查元素 | `POST /api/elements/locate` | element_service.py:330 | — |
| 添加/修改/删除步骤 | `POST/PUT/DELETE /api/script/steps[/:id]` | script_design_service.py:256/296/392 | — |
| 步骤重排 | `POST /api/script/steps/reorder` | script_design_service.py:372 | — |
| 保存/加载/列出/删除用例 | `POST /api/script/save`、`GET /api/script/load/<name>`、`GET /api/script/cases`、`DELETE /api/script/cases/<name>` | script_design_service.py:476/539/599/(新增) | test_case_repository.py:199/225/252/(新增 delete_case) |
| 预览/下载脚本 | `GET /api/script/gen/preview\|download` | script_gen_service.py:64 | — |
| 内联执行 | `POST /api/script/gen/execute` | script_gen_service.py:368 | _execute_step:537 |
| Appium Server 生命周期 | — | — | appium_manager/appium_server.py（ensure_running:94） |

---

## 9. 测试

```powershell
.\venv\Scripts\python.exe -m pytest tests/unit -q           # 46 个单元测试
.\venv\Scripts\python.exe -m pytest tests/integration -q     # 34 个集成测试
# 或一把跑
.\venv\Scripts\python.exe run_tests.py
```

测试覆盖：API 响应格式 / Repository CRUD / Service 业务逻辑 / HTTP 全链路。

---

## 10. 设备连接方式

### USB
手机开 USB 调试 → USB 线连电脑 → 平台选 USB → 连接。

### WiFi（Android 11+）
1. 手机与电脑同局域网
2. 开「开发者选项 → 无线调试」
3. 点「使用配对码配对设备」
4. `.\bin\adb.exe pair <IP:配对端口> <配对码>`
5. `.\bin\adb.exe connect <IP:连接端口>`
6. 平台选 WiFi，输入 `<IP:连接端口>`，连接

---

## 11. 已知坑与设计限制（开发前必读）

| # | 坑 | 现状 | 解决/绕开 |
|---|---|---|---|
| 1 | **`press_hold` 真机报 `InvalidElementStateException`** | `script_gen_service.py:_do_press_hold` 用 `ActionChains` 默认 `pointerType=mouse`，Android 触摸面只接受 touch | 修法：显式构造 `PointerInput(POINTER_TOUCH, "finger")` 并 `actions.w3c_actions.devices=[touch]`。诊断：`bin\adb.exe logcat -d -s UiAutomator2:V` 看注入报错 |
| 2 | **生成的独立脚本里 click 仍走 find_element** | 半坐标方案只改了内联执行路径（`_execute_step`），脚本生成模板（`_build_step_code`）未同步 | 多模块 ID 复用误定位问题在下载脚本里仍存在，需要的话可同步进模板 |
| 3 | **下载脚本路径敏感** | 脚本第 23 行 `PROJECT_ROOT = 脚本父目录的父目录`，设计预期在 `data/generated_scripts/` 下 | 挪位置必须手动改这行常量指向项目根 |
| 4 | **下载脚本依赖外部 Appium Server** | `create_driver()` 直连 `127.0.0.1:4723`，不会自动拉起 | 先 `appium` 命令起服务，或先跑 `start.bat` 让平台带起 Appium |
| 5 | **swipe 是"划完即松手"** | `driver.swipe(..., 500)` 在 0.5s 内完成落下-移动-抬起 | 不适合摇杆这种需要"按住保持"的场景——已用 `press_hold` 解决，swipe 保留给页面滚动 |
| 6 | **删除用例时若有 Script/ExecutionRecord 关联** | TestCase 与 Script/ExecutionRecord 的关系是 `lazy='dynamic'`，无级联 | DB 删除会因外键约束失败，但 `delete_case` 已 try/except + rollback，不阻断 JSON 删除；message 会标注"DB删除失败" |
| 7 | **README 过时点** | 动作类型写"10+"（实际 7）；Appium-Python-Client 写"4.x"（实际 5.0.0）；`appium_server.py` 路径错列在 `device_manager/`（实际在 `appium_manager/`） | 以本文档为准 |

---

## 12. 与 README 的差异（过时点列表）

| README 行 | README 写法 | 实际 |
|---|---|---|
| 第 13 行 | "10+ 种动作（click/swipe/input/press/wait/back/home 等）" | 7 种：click / input / swipe / press_hold / wait / back / screenshot（无 press / home） |
| 第 26 行 | Appium Python Client 4.x | 5.0.0 |
| 第 64 行 | `device_manager/appium_server.py` | `backend/appium_manager/appium_server.py` |
| 第 270 行 | "80 个测试用例" | 实际 46 单元 + 34 集成 = 80 ✓（这个还对得上） |

---

## 13. 一句话起步

**装好 venv + 依赖 + Appium → `python app.py` → 浏览器开 `http://127.0.0.1:5001` → 连真机或开模拟模式 → Tab1 抓元素 → Tab2 编排步骤 → Tab3 生成/执行脚本。改代码前先看第 11 节的已知坑，省得重踩。**
