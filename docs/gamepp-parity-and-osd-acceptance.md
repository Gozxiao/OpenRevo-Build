# GamePP 对标与 OpenRevo 游戏性能中心验收标准

日期：2026-11-03。此文档明确将 v0.1 认定为**离线 CSV 实验版**，不可宣称替代游戏加加。

## 对标依据
- https://gamepp.com/log.html：2026-10-20 游戏加加轻量版 V6.1.282.1016；2026-01-01 渲染帧/插帧显示；2024-12-27 监控项/折线图与性能统计增强
- https://gamepp.com/ ：游戏内/桌面实时 OSD、字体/位置/尺寸/透明度、自定义监控、性能报告、滤镜、录制
- 用户实际截图：FPS、FPS FG Type、FPS Game、Game 1% Low、Game 0.1% Low、FrameTime、CPU Package、电源功耗、P/E 核频、GPU 温度/负载/频率、显存、内存、游戏时长、曲线

## 严格发布门槛：v0.2 不得只有离线 CSV

### P0 必须全部完成
1. 游戏启动后，无须手动生成 CSV，可显示持续更新的 **FPS + 帧时间 + CPU/GPU 温度/负载 + 内存/显存**，未提供数据时显示 --，不得伪造数值。
2. **真正的游戏内 OSD**：优先使用成熟的 RTSS 共享内存/OverlayEditor，用户装有 RTSS 时显示于支持的游戏中；支持窗口化游戏桌面 HUD 备选。应在游戏中而不只是 OpenRevo 窗口中验证。
3. OSD 可设置位置、字号、透明度、显隐字段、热键和刷新频率。提供紧凑模式与详细模式。
4. 采集来自 PresentMon API/Service（实时 ETW）或经过实测的实时读数通道；不得依赖“录完导入 CSV”冒充实时。
5. 采集进程可选、启动/退出自动停止采集；不在无游戏时常驻进行高频 GPU 轮询，不妨碍独显 D3Cold 休眠。
6. 保留已修复的 GM6PX8X GPU 水冷 r5，**禁止插件写入 EC、泵速、风扇、电源模式**；水冷数据只读。
7. 记录运行性能和一局游戏实时数据，结束后自动生成 FPS、1%/0.1% Low、P99 帧时间、CPU/GPU 温度和功耗曲线；无可用传感器时报告缺失而非 0。
8. Windows GitHub CI 验证协议单元测试、性能统计测试和真正编译，附完整可安装插件包。OSD 必须另外在实机游戏内验收。

### P1 之后加入
- **真帧/生成帧/总帧**：区分 PresentMon FrameType/应用帧/显示帧，兼容性取决于驱动、游戏、DLSS/FSR 实际信号；不支持时标注“不可用”，不把总帧减真帧假定为生成帧。
- 游戏场次自动记录、历史曲线、事件打点、帧生成/水冷对比报告、阈值预警。
- CPU P/E 核频、GPU 功耗、显存/内存占用、可选磁盘、风扇/水冷泵档位（只读；优先复用 OpenRevo 遥测，缺项可接 LibreHardwareMonitor）。
- 自定义 OSD 字段列表和预设皮肤。

### P2 独立模块，不能占用 P0 资源
- 截图录制：优先 OBS Studio/Windows Graphics Capture 成熟实现；绝不强制开启常驻视频录制。
- 滤镜：评估 ReShade 授权及反作弊风险，作为独立可选模块，不自动注入游戏。
- FPS 上限/电源优化：需明确用户启用，不改用户原有控制中心设置或水冷策略。
- 游戏笔记、AI 报告/进程管理等 GamePP 轻量版功能，单独规划。

## 成熟组件
- Intel PresentMon v2.6.0（https://github.com/GameTechDev/PresentMon）：MIT，具有 ETW/API/服务/完整 GUI OSD。CLI 是数据录制工具，**不是**实时 OSD。应对比复用其自带 GUI OSD 与 RTSS 两条路线。
- RTSS（https://www.guru3d.com/download/rtss-rivatuner-statistics-server-download/）：游戏内显示引擎，使用安装在用户机器上的 RTSS，不捆绑其专有二进制；可考虑复用 https://github.com/Avaxerrr/pc-stats-tray 的 MIT OSD 桥实现和 https://github.com/HeyOkay/Slick-Overlay-for-RTSS 的布局资产，遵循各自许可。
- LibreHardwareMonitor（https://github.com/LibreHardwareMonitor/LibreHardwareMonitor）：MPL-2.0，可选补充硬件传感器；不可替代游戏帧时间采集。
- OBS Studio / ReShade：可选后续；不随 v0.2 默认引入。

## 安全/质量验证
- 支持 DX11/DX12/Vulkan 中的实际目标游戏验收，记录是否反作弊阻止 OSD；禁止自主绕过反作弊、禁止未经许可注入受保护进程。
- 非兼容独占全屏游戏显示清晰降级提示和桌面监控选项。
- 采集 FPS 和硬件信息分层，默认间隔较长的传感器订阅，控制资源占用。
- RTSS/PresentMon 缺失时提供诊断与明确安装指引，不显示“已连接”的假状态。
- 第三方许可证、源文件、二进制 SHA256 和独立测试报告随包保留。
- 未经过完整闭环实机验证不得描述为“可替代 GamePP”或发布为稳定版本。

## 当前实际状态
- v0.1：仅 Intel PresentMon CLI + CSV 导入/离线图表/JSON；无 OSD、无实时数据和游戏自动记录。
- v0.2：以上 P0 **尚未实现**；必须先完成 P0 再产生新测试版 ZIP。
- 当前 GitHub Draft PR #1 继续保持未合并、未发布稳定版。
