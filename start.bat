@echo off
title Ship-System 一键启动脚本

echo ============================
echo 1. 创建虚拟环境...
python -m venv .venv  

echo 2. 激活虚拟环境...
call .\.venv\Scripts\activate.bat  

echo 3. 安装依赖（根据 requirements.txt）...
pip install -r requirements.txt  

echo 4. 启动 Flask 服务（api目录下的app.py）...
python api/app.py  

echo ============================
echo 服务已启动！访问 http://localhost:5001
echo 按 Ctrl+C 停止服务...