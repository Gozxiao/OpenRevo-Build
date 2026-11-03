# OpenRevo-Build

私有构建工作区：从上游 [faintonce/open-revo](https://github.com/faintonce/open-revo) 的固定源码提交生成 Windows 测试安装包。

- 本仓库不包含用户设备密钥，不修改现有控制中心。
- GPU 35°C 温度采集与外置水冷智能策略修复在独立分支验证。
- 生成的 NSIS 安装包为**未签名、未经过实机验证的测试版本**；不要直接替换正常工作的控制台。
- 上游源代码遵循 GPL-3.0-or-later；任何再分发应遵循相应许可。
