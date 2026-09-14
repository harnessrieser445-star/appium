# 环境记录

> 本文档记录项目运行环境的基线版本，用于环境复现和问题排查。
> Phase 0 创建，后续每次依赖变更时更新。

## 系统信息

| 项 | 值 |
|---|---|
| 操作系统 | Windows 10.0.26100 |
| 系统Python | 3.10.11 |
| venv Python | 3.12.10 |
| 记录日期 | 2026-08-08 |
| 重构阶段 | Phase 0 - 基线 |

## Python 依赖（requirements.lock）

### 核心框架
| 包名 | 版本 | 用途 |
|------|------|------|
| Flask | 3.0.3 | Web框架 |
| Werkzeug | 3.1.8 | WSGI工具 |
| Jinja2 | 3.1.6 | 模板引擎 |
| itsdangerous | 2.2.0 | 安全签名 |
| click | 8.4.2 | 命令行工具 |
| blinker | 1.9.0 | 信号机制 |

### 自动化测试
| 包名 | 版本 | 用途 |
|------|------|------|
| Appium-Python-Client | 5.0.0 | Appium客户端 |
| selenium | 4.46.0 | Selenium基础库 |
| urllib3 | 2.7.0 | HTTP客户端 |
| certifi | 2026.7.22 | SSL证书 |
| h11 | 0.16.0 | HTTP/1.1协议 |
| sniffio | 1.3.1 | 异步库检测 |
| trio | 0.33.0 | 异步IO |
| trio-websocket | 0.12.2 | WebSocket |
| wsproto | 1.3.2 | WebSocket协议 |
| websocket-client | 1.9.0 | WebSocket客户端 |
| outcome | 1.3.0.post0 | 异步结果 |
| sortedcontainers | 2.4.0 | 有序容器 |
| PySocks | 1.7.1 | SOCKS代理 |
| cffi | 2.1.1 | C接口 |
| pycparser | 3.0 | C解析器 |

### 数据处理
| 包名 | 版本 | 用途 |
|------|------|------|
| lxml | 5.2.1 | XML/HTML解析 |
| pillow | 10.3.0 | 图像处理 |
| PyYAML | 6.0.1 | YAML解析 |

### 工具
| 包名 | 版本 | 用途 |
|------|------|------|
| typing_extensions | 4.16.0 | 类型注解扩展 |
| colorama | 0.4.6 | 终端颜色 |
| MarkupSafe | 3.0.3 | 安全标记 |
| idna | 3.18 | 国际化域名 |
| attrs | 26.1.0 | 类属性工具 |

## ADB 信息

| 项 | 值 |
|---|---|
| ADB路径 | bin/adb.exe |
| ADB版本 | 1.0.41 (v36.0.0-13206524) |

## 启动方式

```bash
# 使用虚拟环境Python启动
venv\Scripts\python.exe app.py

# 环境自检
venv\Scripts\python.exe environment_check.py
```

服务启动后访问: http://127.0.0.1:5001

## Appium 环境（需手动启动）

```bash
# 启动Appium Server（需要Node.js环境）
appium --allow-cors
```

Appium Server 地址: http://127.0.0.1:4723

### 已知问题
- MIUI系统需要手动修改 node_modules 中的设置（参考README.md），后续Phase将解决此问题

## 重构进度

| Phase | 名称 | 状态 | 完成日期 | Tag |
|-------|------|------|---------|-----|
| 0 | 准备阶段 | ✅ 已完成 | 2026-08-08 | - |
| 1 | 数据库迁移 | ✅ 已完成 | 2026-08-08 | - |
| 2 | Service层拆分 | 待开始 | - | - |
| 3 | Appium管理优化 | 待开始 | - | - |
| 4 | 执行引擎优化 | 待开始 | - | - |
| 5 | 安全优化 | 待开始 | - | - |

## 数据库信息（Phase 1新增）

| 项 | 值 |
|---|---|
| 数据库类型 | SQLite 3 |
| 数据库文件 | data/appium_test.db |
| ORM | Flask-SQLAlchemy 3.1.1 |
| SQLAlchemy版本 | 2.0.51 |
| 表数量 | 12 |
| Feature Flag | database.enabled=false（旧内存模式保持不变） |
| 已迁移用例 | 2个（login_test, 登录退出） |
| 已迁移步骤 | 8个 |
