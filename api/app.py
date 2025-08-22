import os
import json
import requests
import logging
from datetime import datetime
from flask import Flask, request, render_template, redirect, url_for, make_response

# --------------------------- 配置区（适配 api 子目录） --------------------------- 
API_DIR = os.path.abspath(os.path.dirname(__file__))
CONFIG = {
    "SECRET_KEY": "your_secret_key",
    "DEBUG": True,
    "PORT": int(os.environ.get("PORT", 5001)),
    "HOST": "127.0.0.1",
    "AMAP_API_KEY": "1389a7514ce65016496e0ee1349282b7",
    "ROUTE_DATA_PATH": os.path.join(API_DIR, "../static/route_data.json"),  # 上级目录找 static
    "VALID_USER": {"admin": "123456"}
}

# 日志配置
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# --------------------------- 工具函数（安全读取航线数据） --------------------------- 
def read_route_data():
    file_path = CONFIG["ROUTE_DATA_PATH"]
    if not os.path.exists(file_path):
        logger.warning(f"⚠️  航线数据文件不存在: {file_path}，返回空数据")
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("points", [])
    except json.JSONDecodeError:
        logger.error(f"❌ JSON 格式错误: {file_path}，请检查文件内容")
        return []
    except Exception as e:
        logger.error(f"❌ 读取航线数据失败: {str(e)}")
        return []

# --------------------------- Flask 应用初始化（自动创建依赖） --------------------------- 
def create_app():
    # 1. 确保 static 和 templates 目录存在（上级目录）
    root_path = os.path.dirname(API_DIR)  # 项目根目录（ship - system/）
    static_path = os.path.join(root_path, "static")
    template_path = os.path.join(root_path, "templates")

    # 自动创建 static 目录 + 示例数据
    if not os.path.exists(static_path):
        os.makedirs(static_path)
        sample_route_data = {"points": [
            [121.487899, 31.249162],
            [121.506302, 31.238938],
            [121.525374, 31.227871],
            [121.544446, 31.216804]
        ]}
        with open(CONFIG["ROUTE_DATA_PATH"], "w", encoding="utf-8") as f:
            json.dump(sample_route_data, f, ensure_ascii=False, indent=2)
        logger.info(f"✅ 自动创建 static 目录及航线数据: {static_path}")

    # 自动创建 templates 目录 + 基础模板
    if not os.path.exists(template_path):
        os.makedirs(template_path)
        with open(os.path.join(template_path, "base.html"), "w", encoding="utf-8") as f:
            f.write("""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>{% block title %}船舶系统{% endblock %}</title>
    {% block head_css %}{% endblock %}
</head>
<body style="margin: 0; padding: 20px; background-color: #f5f7fa; font-family: Arial, sans-serif;">
    {% block content %}{% endblock %}
</body>
</html>
            """)
        logger.info(f"✅ 自动创建 templates 目录及基础模板: {template_path}")

    # 2. 初始化 Flask 应用
    app = Flask(
        __name__,
        static_folder=static_path,
        template_folder=template_path
    )
    app.config.from_mapping(CONFIG)
    return app

# --------------------------- 路由定义（严格前后端分离） --------------------------- 
app = create_app()

@app.route("/")
def index():
    return redirect(url_for("login_page"))

@app.route("/get_location/<lng>/<lat>")
def get_location(lng, lat):
    api_url = f"https://restapi.amap.com/v3/geocode/regeo?location={lng},{lat}&key={app.config['AMAP_API_KEY']}"
    try:
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        return {"error": "请求超时"}, 408
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}, 500

@app.route("/login_page")
def login_page():
    return render_template("login.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    user = request.form.get("username", "").strip()
    pwd = request.form.get("password", "").strip()

    if not user or not pwd:
        return "用户名和密码不能为空", 400

    if app.config["VALID_USER"].get(user) == pwd:
        route_points = read_route_data()
        return render_template("route_map.html", route_points=route_points)
    else:
        return "用户名或密码错误（正确：admin/123456）", 401

@app.route("/route_map")
def route_map():
    route_points = read_route_data()
    return render_template("route_map.html", route_points=route_points)

@app.route("/fuel_saving", methods=["GET"])
def fuel_saving():
    required_params = ["original_speed", "optimized_speed", "distance"]
    if not all(request.args.get(param) for param in required_params):
        return "参数不完整", 400

    try:
        original = float(request.args["original_speed"])
        optimized = float(request.args["optimized_speed"])
        distance = float(request.args["distance"])
    except ValueError:
        return "参数格式错误", 400

    if original <= 0 or optimized <= 0 or distance <= 0 or optimized >= original:
        return "参数错误", 400

    saving = round((original - optimized) * distance * 0.8, 2)
    return render_template("fuel_result.html",
                           original=original,
                           optimized=optimized,
                           distance=distance,
                           saving=saving)

@app.route("/export_pdf")
def export_pdf():
    # （PDF 导出逻辑保持不变，若需修复可补充）
    return "PDF 导出功能待完善", 501  # 临时占位，避免报错

# --------------------------- 启动入口（本地 + 生产适配） --------------------------- 
if __name__ == "__main__":
    logger.info("📋 系统路由表:")
    for rule in app.url_map.iter_rules():
        logger.info(f"  {rule.rule} -> {rule.endpoint}")

    app.run(
        debug=app.config["DEBUG"],
        port=app.config["PORT"],
        host=app.config["HOST"]
    )