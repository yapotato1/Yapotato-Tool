@echo off
chcp 65001 >nul
echo ========================================
echo   构建 YapotatoTool.exe (PyInstaller)
echo ========================================
echo.

cd /d "%~dp0"

echo [1/3] 清理旧构建...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

echo [2/3] 开始构建 (onedir 模式调试)...
.venv\Scripts\python.exe -m PyInstaller ^
    --name "YapotatoTool" ^
    --onedir ^
    --console ^
    --icon "PNG\frog.png" ^
    --add-data "index.html;." ^
    --add-data "welcome.html;." ^
    --add-data "select.html;." ^
    --add-data "douyin.html;." ^
    --add-data "bilibili.html;." ^
    --add-data "PNG;PNG" ^
    --add-data "fonts;fonts" ^
    --additional-hooks-dir "hooks" ^
    --collect-all DrissionPage ^
    --collect-all certifi ^
    --hidden-import flask ^
    --hidden-import flask_cors ^
    --hidden-import jinja2 ^
    --hidden-import werkzeug ^
    --hidden-import click ^
    --hidden-import blinker ^
    --hidden-import itsdangerous ^
    --hidden-import markupsafe ^
    --hidden-import lxml ^
    --hidden-import lxml.etree ^
    --hidden-import lxml._elementpath ^
    --hidden-import openpyxl ^
    --hidden-import requests ^
    --hidden-import urllib3 ^
    --hidden-import websocket ^
    --hidden-import psutil ^
    --hidden-import charset_normalizer ^
    --hidden-import idna ^
    --hidden-import tldextract ^
    --hidden-import colorama ^
    --hidden-import et_xmlfile ^
    --hidden-import filelock ^
    --hidden-import requests_file ^
    --exclude-module tkinter ^
    --exclude-module test ^
    --exclude-module unittest ^
    server.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] 构建失败!
    pause
    exit /b 1
)

echo.
echo [3/3] 构建完成!
echo   输出目录: dist\YapotatoTool\
echo   可执行文件: dist\YapotatoTool\YapotatoTool.exe
echo.
echo 测试运行: dist\YapotatoTool\YapotatoTool.exe
pause
