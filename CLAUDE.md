# Yapotato Tool - AI 项目说明

## 项目概述

一个本地运行的无水印视频下载工具，支持 **抖音** 和 **B站（哔哩哔哩）**。
Python Flask 后端 + 原生 HTML/CSS/JS 前端，浏览器访问 `http://127.0.0.1:8888` 使用。

## 技术栈

- **后端**: Python + Flask + flask-cors
- **前端**: 原生 HTML/CSS/JS（无框架），Fetch API 异步请求
- **浏览器自动化**: DrissionPage（用于抖音页面抓取）
- **音视频合并**: FFmpeg（外置二进制，自动下载到 `bin/ffmpeg.exe`）
- **打包**: PyInstaller（`build.bat` + `YapotatoTool.spec`）

## 当前版本

```
VERSION = "3.9.1"   # 位于 server.py 第71行
```

## 文件结构

```
├── server.py              # 主程序（Flask 后端，所有 API 路由）
├── index.html             # 首页
├── select.html            # 平台选择页（抖音 / B站）
├── welcome.html           # 欢迎页
├── bilibili.html          # B站下载页
├── douyin.html            # 抖音下载页
├── build_exe.py           # PyInstaller 打包入口
├── build.bat              # 一键打包脚本
├── YapotatoTool.spec      # PyInstaller 配置
├── requirements.txt       # Python 依赖（flask, flask-cors, DrissionPage）
├── PNG/                   # 图标和界面图片
├── fonts/                 # Zpix 像素字体
├── hooks/                 # PyInstaller hook（hook-DrissionPage.py）
├── bin/                   # FFmpeg 二进制（运行时自动下载，不入 Git）
├── downloads/             # 下载的视频（不入 Git）
├── build/                 # PyInstaller 构建产物（不入 Git）
└── dist/                  # 打包输出（不入 Git，上传到 GitHub Releases）
```

## 核心功能

### 抖音
- 输入分享链接，自动解析视频 ID（支持短链接 `v.douyin.com`、标准链接 `douyin.com`）
- 通过 DrissionPage 浏览器自动化抓取页面数据，提取无水印视频 URL
- 浏览器内预览 + 下载

### B站
- 支持 BV/AV 号、番剧 EP 号解析
- Cookie 认证登录（可获取 1080P+ 画质）
- 支持视频 / 音频分离下载（FFmpeg 合并音画）
- 番剧/电影 PGC 内容支持

### 通用
- FFmpeg 自动下载和管理（首次运行自动下载便携版）
- 浏览器自动检测（便携版 Edge → Chrome → 系统 Edge）
- PyInstaller 打包成独立 exe，无需 Python 环境

## API 路由一览

```
GET  /                                  # 首页
POST /api/parse                         # 抖音解析
GET  /api/download                      # 抖音下载
POST /api/close                         # 关闭浏览器实例
POST /api/bilibili/parse                # B站解析
GET  /api/bilibili/download             # B站视频下载
GET  /api/bilibili/download-audio       # B站音频下载
GET  /api/bilibili/ffmpeg-status        # FFmpeg 状态
GET  /api/bilibili/cookie-status        # Cookie 状态
POST /api/bilibili/set-cookies          # 设置 Cookie
POST /api/bilibili/clear-cookies        # 清除 Cookie
POST /api/bilibili/validate-cookies     # 验证 Cookie
GET  /<path:filename>                   # 静态文件托管
```

## 打包流程

```bash
python build_exe.py     # 或直接运行 build.bat
```

打包输出在 `dist/YapotatoTool V{版本号}/`，包含 exe 和 `_internal/` 依赖目录。
压缩成 zip 后上传到 GitHub Releases 供用户下载。

## 开发注意事项

- **版本号**：修改代码后必须同时更新 `server.py`（第71行）和 `welcome.html` 两处的版本号
  - **Major（第一位）**：架构性大改动（极少触发）
  - **Minor（第二位）**：新增功能（如新平台支持）
  - **Patch（第三位）**：修 bug 或一般改动
- B站 Cookie 存储在 `bilibili_cookies.json`（本地敏感文件，不入 Git）
- FFmpeg 二进制通过 `ensure_ffmpeg()` 自动管理，首次运行自动下载
- 前端页面通过 Flask 的 `send_from_directory` 托管，所有 HTML 文件放在项目根目录

## 更新日志

**v1.0.0 — 2026-04-28**
- 初始版本发布，支持抖音无水印下载

**v3.6.0 — 2026-05-05**
- 新增 B站视频下载支持
- FFmpeg 音画合并
- Cookie 认证

**v3.8.0 — 2026-05-12**
- 新增 B站番剧/电影 PGC 支持
- 音频分离下载

**v3.8.3 — 2026-05-14**
- 多浏览器支持（便携版 Edge / Chrome / 系统 Edge）
- FFmpeg 自动下载

**v3.9.0 — 2026-05-18**
- 新增 Web 管理面板（admin.html），双击 YM.png 进入
- 实时日志流（SSE）、服务器状态监控
- 一键关闭服务并清理临时文件
