# 游戏性能实验室 · OpenRevo 插件 v0.1.0

> 第一阶段为可用的离线帧时间分析器 + Intel 官方 PresentMon 录制助手。暂未实现实时 OSD、自动游戏识别或水冷温度联动，不会伪造实时数据。

## 功能
- OpenRevo 原生 tab 插件，不修改主程序、不接触 EC、水泵或风扇。
- 本地导入/拖拽 PresentMon CSV，识别 MsBetweenDisplayChange、MsBetweenPresents、FrameType、Application。
- 显示平均 FPS、1% Low、0.1% Low、P99 帧时间、采集帧数和帧率趋势。
- 当 CSV 含多个进程时，可以在界面切换进程后独立分析。
- 可下载 JSON 报告，数据始终在本地浏览器中解析。
- 随包提供 capture.cmd，调用官方 PresentMon 2.6.0 控制台程序录制指定游戏进程。

## 安装
将包含 manifest.json 的 gozxiao-game-performance-lab 插件文件夹复制到：
%APPDATA%\OpenRevo\plugins\gozxiao-game-performance-lab\

或在 OpenRevo 插件管理器中安装单独的插件 ZIP。然后启用「游戏性能实验室」。

## 录制流程
1. 在插件目录双击 capture.cmd，只在你主动操作时开始录制。
2. 输入游戏实际 exe 名称（如 game.exe）和采集时长（默认 60 秒）。
3. 游戏运行结束后，脚本在「文档\OpenRevo-Performance\captures」输出 CSV。
4. 回到插件页面导入该 CSV。

录制可能需要管理员权限。某些游戏/反作弊可能限制采集，程序不会尝试绕过限制。

## 统计口径
优先选取 MsBetweenDisplayChange 中可用的显示帧数据；字段不存在时回退 MsBetweenPresents。忽略 NA、空值、负数和非数值样本。平均 FPS = 1000 / 平均帧间隔(ms)。1% Low = 1000 / 帧间隔 P99；0.1% Low = 1000 / P99.9。与游戏加加等使用其他统计定义的程序可能有差异。帧生成类型只有在 CSV 提供 FrameType 时才会统计，不通过驱动型号猜测。

## 安全和许可
- 无遥测后台常驻，无游戏内注入，无自动扫描进程、无联网传输个人记录。
- 仅随明确的录制操作启动 Intel PresentMon。
- 本插件作者 Gozxiao；Intel PresentMon 二进制依据其 MIT 许可再分发，保留第三方许可文件。
- 安装包为测试性质，需在 Windows 电脑上验证实际采集与 iframe 插件兼容性。

## 后续阶段（尚未实现）
- 实时 PresentMon 数据伴随服务和自动识别活动游戏。
- OpenRevo CPU/GPU/水冷只读遥测与游戏记录融合。
- 可选 RTSS 游戏内 OSD（需独立兼容/反作弊验证）。
- 游戏场次历史数据库和可对比报告。
