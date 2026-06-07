# Scripts 资产索引

> 生成: 2026-06-07 | 本次审计: v111#3
> 总计: 87 脚本 (44 核心 + 39 工具 + 4 非脚本) | 废弃/实验: 8 移入 archive/

---

## 核心脚本 (44) — 系统基础组件，高频使用，被cron/sche_tasks引用

### 系统启动与恢复
| 脚本 | 用途 |
|------|------|
| `agent_resume.sh` | Agent恢复入口，断电续跑 |
| `start_tmwd_master.py` | 启动tmwebdriver浏览器引擎 |
| `knowledge_startup.sh` | 知识库启动脚本 |
| `manage_services.sh` | 服务管理(启动/停止/重启) |

### 浏览器自动化
| 脚本 | 用途 |
|------|------|
| `browser_click.py` | 浏览器点击操作 |
| `browser_interact.py` | 浏览器交互(输入/滚动/选择) |
| `browser-vision.py` | 浏览器视觉集成(截图+OCR) |

### AgentMail 通信
| 脚本 | 用途 |
|------|------|
| `agentmail_bridge.py` | AgentMail桥接器(与邮件系统互通) |
| `agentmail_env.py` | AgentMail环境配置 |
| `agentmail_local.py` | 本地文件交换模式AgentMail |

### Hermes 子系统
| 脚本 | 用途 |
|------|------|
| `hermes_api_proxy.py` | Hermes API代理 |
| `hermes_api_wrapper.py` | Hermes API包装器 |
| `hermes_bridge.py` | Hermes桥接(核心组件) |
| `hermes_process_manager.sh` | Hermes进程管理(cron调用) |
| `hermes_relay.py` | Hermes中继(任务分发) |
| `hermes_tool.py` | Hermes工具集 |

### 健康监控与OOM防护
| 脚本 | 用途 |
|------|------|
| `ga-health` | 健康检查入口(cron每5分钟) |
| `ga_watchdog.sh` | GA看门狗(cron调用) |
| `health_unified.sh` | 统一健康检查(cron调用) |
| `heartbeat_weekly.sh` | 周心跳通知(cron) |
| `health_collector.py` | 健康数据采集 |
| `health_dashboard.py` | 健康仪表盘终端UI (v111#1产出) |
| `service_health_dashboard.py` | 服务健康仪表盘 |
| `cgroup_memory_limit.sh` | cgroup内存限制策略 |
| `oom_protect.sh` | OOM保护脚本 |
| `memory_pressure_monitor.py` | 内存压力监控 |
| `memory_tool.py` | 内存状态工具 |
| `cleanup_disk.py` | 磁盘清理 |
| `preflight_check.py` | 飞行前检查(启动时) |
| `pre_delivery_check.py` | 交付前质量检查 |

### 质量保证
| 脚本 | 用途 |
|------|------|
| `autonomous_quality_gate.py` | 自主质量门禁 |
| `self_discriminator.py` | 自我判别器(输出质量评估) |
| `supervisor_tool.py` | 监督者工具(子任务管理) |

### 状态报告
| 脚本 | 用途 |
|------|------|
| `ga_status_reporter.py` | GA状态报告 |
| `ga_tool.py` | GA工具集 |

### AI/模型
| 脚本 | 用途 |
|------|------|
| `ai_cli.py` | AI命令行界面 |
| `model_router.py` | 模型路由(多模型负载均衡) |
| `svc.py` | 服务CLI |

### 视觉管线
| 脚本 | 用途 |
|------|------|
| `vision_api.py` | 视觉API封装 |
| `vision_integration.py` | 视觉管线集成(裁剪/OCR/描述) |

### 工具
| 脚本 | 用途 |
|------|------|
| `system_utils.py` | 系统工具集 |
| `nanobot_wrapper.py` | Nanobot API包装器 (v111#2产出) |
| `batch_task_selector.py` | 批量任务选择器 |
| `auto_repair.py` | 自动修复模块 |

---

## 工具脚本 (39) — 辅助功能，按需使用

| 脚本 | 用途 |
|------|------|
| `agent_liveness.sh` | Agent存活检查(小脚本) |
| `agentmail_cmd_handler.py` | AgentMail命令处理器 |
| `agentmail_tool.py` | AgentMail工具 |
| `alert_manager.py` | 告警管理器 |
| `api_tester.py` | API测试脚本 |
| `archive_l4_sessions.py` | L4会话归档脚本 |
| `arena_benchmark.py` | 竞技场基准测试(Agent能力评估) |
| `arena_benchmark_suite.py` | 基准测试套件 |
| `benchmarker.py` | 基准测试器 |
| `brainstormer.py` | 头脑风暴(规划辅助) |
| `check_agentmail.py` | AgentMail检查 |
| `cron_python.sh` | Cron Python运行器 |
| `dep_scanner.py` | 依赖扫描 |
| `describe_screenshot.py` | 截图描述(视觉辅助) |
| `dingtalk_notifier.py` | 钉钉通知推送 |
| `discriminator_tool.py` | 判别器命令行工具 |
| `drift_detector.py` | 漂移检测(监控数据偏差) |
| `env_sanitizer.py` | 环境安全清理 |
| `feishu_bridge.py` | 飞书消息桥接 |
| `file_watcher.py` | 文件变更监视器 |
| `ga-diskcheck` | 磁盘空间检查 |
| `ga_search.py` | GA搜索工具 |
| `hackernews_scraper.py` | HackerNews爬取(一次性) |
| `health_server.py` | 健康指标HTTP服务 |
| `health_vision.py` | 健康视觉监控(屏幕OCR) |
| `health_watchdog.sh` | 健康看门狗 |
| `hermes_health_collector.py` | Hermes健康数据采集 |
| `idle_guard.sh` | 空闲保护(无人时降级) |
| `prompt_optimizer.py` | 提示词优化(实验性) |
| `scheduler_dashboard.html` | 调度器Dashboard(HTML) |
| `service_health_report.py` | 服务健康报告生成 |
| `solver_team_proto.py` | 解决者团队原型(多Agent协作) |
| `sop_dep_analyzer.py` | SOP依赖分析 |
| `sop_graph.py` | SOP图谱可视化 |
| `sop_recommender.py` | SOP推荐 |
| `sop_script_audit.py` | SOP脚本审计 |
| `system_snapshot_db.py` | 系统快照数据库 |
| `vision_agent.py` | 视觉Agent(自动化视觉任务) |
| `vision_chinese_ocr.py` | 中文OCR(基于PaddleOCR) |
| `vision_repair.py` | 视觉修复工具 |
| `whiteboard_protocol.py` | 白板协议(任务协作) |

---

## 非脚本文件 (4)

| 文件 | 用途 |
|------|------|
| `VISION_PIPELINE_README.md` | 视觉管线文档 |
| `code_dep_dashboard.html` | 代码依赖Dashboard |
| `code_dependency_graph.html` | 代码依赖图 |
| `vue_health_dashboard.html` | Vue健康Dashboard |

---

## 归档文件

`archive/` — 废弃/实验性脚本，不参与日常使用
- `health_server.py.bak` — 备份文件(已删除冗余)
- `health_watchdog.sh.bak` — 备份文件(已删除冗余)
- `api_test.py` — 软链冗余(已移除，原文件api_tester.py保留)
- `experimental/` — 对抗训练实验脚本(3个)，非核心管线

---

*注: 分类依据 — 核心=被cron/sche_tasks引用/被agent工作流调用/系统基础组件; 工具=按需调用; 实验=一次性/原型; 废弃=备份/冗余*
