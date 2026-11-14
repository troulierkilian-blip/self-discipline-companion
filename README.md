# 自律伴侣

自律伴侣是一款中文 Windows 桌面软件，用来安排每天的学习、运动和睡眠。工作日和周末可以分别设置目标。记录保存在本机，离线也能使用。

**[下载 Windows 免安装版 v1.1.0](https://github.com/troulierkilian-blip/self-discipline-companion/releases/tag/v1.1.0)**  
适用于 Windows 10（1809 或更新版本）和 Windows 11 x64。可以直接下载 exe，也可以下载附有中文使用说明的便携 ZIP。两种方式都无需安装 Python。

## 首次使用

1. 双击 **自律伴侣.exe**。从旧版升级时，请先右键系统托盘中的自律伴侣图标，选择「退出」，再运行新版。
2. 填写工作日和周末的学习目标、运动目标、提醒时间及就寝和起床时间。
3. 在「学习专注」添加任务并开始计时。已完成的学习可以点「补记学习」，填写日期、名称和分钟数。补记时长会与专注计时合计，自动更新首页进度、历史趋势和 CSV 导出。

在「日常记录」可以登记运动时长、确认就寝与起床时间，或修正过去的记录。关闭窗口后，软件会在系统托盘中继续提醒。个人数据存放在 `%LOCALAPPDATA%\自律伴侣`，可以在「计划与设置」备份或恢复。[完整使用说明](使用说明.md)

## 从源码构建

在 Windows x64 上安装 Python 3.10 x64，在项目根目录打开 PowerShell，运行以下命令。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

构建脚本会运行核心与界面测试，生成 `dist\自律伴侣.exe`，并验证打包后的程序。只想从源码启动时，安装依赖后运行 `.\.venv\Scripts\python.exe main.py`。

本版测试环境、结果和验证范围见[验收报告](验收报告.md)。Python、Qt 和其他依赖的许可见[第三方软件声明](THIRD_PARTY_NOTICES.md)。
