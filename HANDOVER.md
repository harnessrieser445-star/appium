# Appium 自动化平台 · 工作交接文档

> 生成时间：2026-09-11
> 项目路径：`C:\Users\Acv\Desktop\APPIUM\APPIUM`（Flask + Appium，端口 5001，启动入口 `start.bat`）

---

## 一、项目现状一句话

平台已完成**稳定性三批修复** + **AI 助理适配阶段一（P0）**，代码全部通过 80 项单元测试，**尚缺真机浸泡验证**。接手人第一件事：接真机跑验收，再决定后续批次。

---

## 二、当前进度

### 2.1 已完成：稳定性修复（3 批）

| 批次 | 内容 | 关键文件 | 状态 |
|---|---|---|---|
| 第一批 | 截图读写竞态（内存直传+原子写）、隐式等待恢复 bug、前端轮询节流、Flask `threaded=True` | `backend/api/element.py`、`screenshot_service.py`、`script_gen_service.py`、`main.js`、`app.py` | ✅ 已验证 |
| 第二批 | **Appium Server 管道饿死修复**（输出从无人消费的 PIPE 改为写入 `data/logs/appium_server.log`，10MB 滚动，启动失败读日志尾部诊断） | `backend/appium_manager/appium_server.py` | ✅ 已验证 |
| 第三批 | `/api/snapshot` 同源快照（元素树+截图同一帧，解决坐标/高亮错位）、前端全面接入、`disableWindowAnimation=true` | `element.py`、`element_service.py`、`main.js`、`appium_driver.py` | ✅ 已验证 |

### 2.2 已完成：AI 助理适配 · 阶段一（P0）

| 项 | 内容 | 状态 |
|---|---|---|
| 1.1 会话生命周期 | `new_command_timeout` 提至 1800s；`/api/device/status` 新增 `disconnect_reason`、`current_page`；连接丢失**即时唤醒恢复**（`_wake_event`，不再等 60s 心跳周期） | ✅ |
| 1.2 单动作直执行 | `POST /api/action`，一次调用一个动作，**零用例污染**（已断言验证），每次返回 `elapsed_ms` | ✅ |
| 1.3 条件等待 | `wait_until`（visible/gone，0.5s 轮询），超时返回 `TIMEOUT` + `page_digest` 页面摘要 | ✅ |
| 1.4 元素树升级 | 元素增量 `parent_id/children/visible/obscured_by/scrollable_ancestor` + 响应增量 `tree` 骨架；新接口 `GET /api/elements/scrollables`；旧字段全保留 | ✅ |
| 1.5 动作补齐 | `long_press / double_click / swipe_xy / clear_input / press_hold`（8 方向含斜向，√2/2 归一化） | ✅ |
| 配套 | 5001 端口单实例检查（重复启动直接退出）；错误码体系 `SESSION_LOST/ELEMENT_NOT_FOUND/TIMEOUT/BAD_REQUEST/ACTION_FAILED/NO_DEVICE` | ✅ |

### 2.3 未开始 / 待办

| 优先级 | 事项 | 说明 |
|---|---|---|
| 高 | **真机浸泡验证** | 所有已交付内容只过了 mock/单测，未在真机长跑（详见第四节验收清单） |
| 高 | 阶段二（P1） | 批量动作 `/api/actions/batch`、页面标识 `/api/page/current`、坐标长按、JPEG/区域截图、错误码扩展 |
| 中 | 孤儿 Session 治理 | Session 创建 60s 超时后 daemon 线程仍可能建成 Session 无人回收（原"第四批"），1.1 的即时恢复只缓解了表象 |
| 中 | 恢复机制与在飞操作隔离 | 恢复时 `adb kill-server`/重启 Server 会打死正在执行的命令，需操作串行锁（设计级，勿轻动） |
| 低 | 阶段三（P2） | 操作录制沉淀用例、定位器库、OpenAPI 文档、异步执行 job_id、耗时统计导出 |
| 低 | XPath 兜底语义错误 | `element_service.py` 兜底 `//tag[@index]` 全局匹配语义不对；`adbExecPath` 缺 `appium:` 前缀 |

---

## 三、架构速览（接手必读）

```
网页端 main.js ──轮询──> Flask(5001, threaded)
                            ├─ /api/snapshot ──> ElementService(解析XML建树) + ScreenshotService(原子写)
                            ├─ /api/action ────> ActionService ──> DeviceService(Facade)
                            └─ /api/device/* ──> DeviceManager
                                                    ├─ DriverPool ── DriverProxy(重试/连接丢失回调)
                                                    ├─ AppiumDriver(Session创建/重连)
                                                    ├─ AppiumServer(进程生命周期, 日志→data/logs/)
                                                    └─ 心跳线程(60s) + _wake_event 即时唤醒 + 四级恢复
```

关键设计约定：
- **截图一律内存直传**（`get_screenshot_bytes` 链路），`current.png` 仅作高亮功能副产物且必须原子写；
- **元素与截图必须同源**（`/api/snapshot` 内先 page_source 紧跟截图）；
- **DriverProxy 是操作设备的唯一推荐入口**（自带重试与连接丢失上报），raw driver 仅兼容旧代码；
- 心跳在脚本执行期间会被 `pause_keepalive()` 暂停，此时连接丢失只标记不恢复（保护执行中的测试）。

---

## 四、验收清单（真机，按序执行）

1. **回归**：网页端连接设备 → 截图/元素刷新/高亮/坐标反查 → 编排执行一条旧用例，确认人工流程无回归；
2. **稳定性**：开自动刷新连续挂机 ≥30 分钟，观察断连次数（目标 0 次人工干预）；期间翻 `data/logs/appium_server.log` 确认 Server 日志正常滚动；
3. **断连恢复**：执行中拔掉 USB（或 `adb kill-server`），确认 10s 级自动重连，`/api/device/status` 的 `disconnect_reason` 有值、恢复后清零、`current_page` 可读；
4. **P0 动作**：真机跑 `click/input/wait_until/long_press/swipe_xy/press_hold(斜向)/clear_input` 各一遍；
5. **效率对比**：50 个标准动作的 HTTP 次数与总耗时（对比优化前基线）。

---

## 五、隐患与风险（按严重度排序）

### P0 - 必须知道
1. **全部改动未过真机**。单元测试/mock 覆盖不了 Appium 真实会话行为，真机首跑大概率暴露小问题（坐标系、时序、厂商 ROM 差异）。
2. **孤儿 Session 根因未除**：连接超时后主线程放弃但 Appium Server 端可能稍后建成 Session 无人 quit，UiAutomator2 单设备单 Session，会导致后续连接被挂起。临时对策：连不上时重启 Appium Server（或重启服务）。根治方案已设计（超时后 `GET /sessions` + `DELETE` 清理），未实施。
3. **遮挡判断是启发式**：`obscured_by/visible` 基于"文档序≈z-order"，普通弹窗/抽屉有效；SurfaceView、悬浮窗、自绘容器会漏判。AI 决策不能完全依赖它，关键操作建议配合 `wait_until` 验证结果。

### P1 - 需要盯
4. **恢复与在飞操作互踩**：心跳线程恢复时 `adb kill-server` / 重启 Server 会打死同一时刻正在执行的截图/脚本命令。表现为偶发的单命令失败。需要操作串行锁，属设计级改动，改之前先想清锁粒度（粗了会把"卡死"换个地方复现）。
5. **`obscured_by` 计算是 O(n²)**：元素几百个时每次解析几十万次比较，当前可接受；超大页面（>1000 元素）可能拖慢 `/api/snapshot`，届时需换矩形索引。
6. **`page_digest` 会刷新元素缓存**：`wait_until` 超时分支调用 `refresh_from_page_source`，网页端元素列表会随之变化——这是有意设计（保持同源），但如果网页端正选中某元素，选中态可能丢失。

### P2 - 择机处理
7. `refresh_elements` 持锁做网络调用（page_source 慢时阻塞其他元素 API）；`adbExecPath` capability 缺 `appium:` 前缀可能被忽略；XPath 兜底 `//tag[@index]` 语义错误（命中全局第一个同 index 元素）。
8. Appium Server 日志只保留一份 `.old`，长时间排查历史问题时可能不够用。
9. 生成的 `generated_scripts/` 下旧脚本绕过 DriverProxy，重连后会持有失效 driver，逐脚本迁移前不要在长跑任务里混用。

---

## 六、常用运维入口

| 事项 | 位置 |
|---|---|
| 启动 | 双击 `start.bat`（自动用 venv） |
| 平台日志 | 控制台输出（`backend/utils/logger.py`） |
| Appium Server 日志 | `APPIUM/data/logs/appium_server.log`（10MB 滚动） |
| 保活状态 | `GET /api/device/keepalive` |
| 诊断信息 | `GET /api/diagnostics` |
| 配置 | `config.yaml`（超时/心跳间隔/重连次数均可调） |
| 测试 | `venv/Scripts/python.exe -m pytest tests/ -q`（当前 80 项） |
| 工作日志 | `.workbuddy/memory/2026-09-08 ~ 09-10.md`（每批修复的详细记录） |

---

## 七、给接手人的三条建议

1. **先验证再开发**：真机验收清单（第四节）没过完之前，不要开始阶段二。
2. **动恢复机制前先读日志**：`manager.py` 的心跳/恢复是状态机，`_wake_event` 引入后时序变了，改动前先用 30 分钟浸泡确认基线行为。
3. **保持三条铁律**：截图内存直传、元素截图同源、操作走 DriverProxy——新功能违反任意一条都会把已修掉的病带回来。
