import os
import json
import requests
import logging
import math
from io import BytesIO
from datetime import datetime
from flask import Flask, request, render_template, redirect, url_for, make_response, send_file
from flask_cors import CORS

# PDF生成相关库
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import cm

# --------------------------- 配置与初始化 --------------------------- 
API_DIR = os.path.abspath(os.path.dirname(__file__))

# 修复上海-宁波航线坐标数据（更精确的坐标点）
ALL_PRESET_ROUTES = {
    ("上海", "宁波"): {
        "filename": "shanghai_ningbo.json",
        "points": [
            [121.507812, 31.237057],  # 上海港
            [121.552376, 31.202274],
            [121.619159, 31.159024],
            [121.688468, 31.107377],
            [121.752846, 31.086428],
            [121.837651, 31.051066],
            [121.901726, 30.96938],
            [121.981797, 30.729212],
            [122.01298,  30.542215],
            [121.99094,  30.455198],
            [121.859322, 30.369414],
            [121.78957,  30.264341],
            [121.824434, 30.157196],
            [121.854434, 30.057196],
            [121.890951, 29.984561],
            [121.932784, 29.967126],
            [121.98619,  29.935834],
            [122.029602, 29.891468],
            [121.998266, 29.859254],
            [121.976948, 29.837783],
            [121.880901, 29.816987],
            [121.81136,  29.802932]   # 宁波港
        ]
    },
    ("宁波", "上海"): {
        "filename": "ningbo_shanghai.json",
        "points": [
            [121.81136,  29.802932],   # 宁波港
            [121.880901, 29.816987],
            [121.976948, 29.837783],
            [121.998266, 29.859254],
            [122.029602, 29.891468],
            [121.98619,  29.935834],
            [121.932784, 29.967126],
            [121.890951, 29.984561],
            [121.854434, 30.057196],
            [121.824434, 30.157196],
            [121.78957,  30.264341],
            [121.859322, 30.369414],
            [121.99094,  30.455198],
            [122.01298,  30.542215],
            [121.981797, 30.729212],
            [121.901726, 30.96938],
            [121.837651, 31.051066],
            [121.752846, 31.086428],
            [121.688468, 31.107377],
            [121.619159, 31.159024],
            [121.552376, 31.202274],
            [121.507812, 31.237057]   # 上海港
        ]
    },
    # 其他航线保持不变...
    ("广州", "深圳"): {
        "filename": "guangzhou_shenzhen.json",
        "points": [[113.264434, 23.129162], [113.548813, 22.906414], [114.057868, 22.543096]]
    }
}

# 系统配置
CONFIG = {
    "SECRET_KEY": "your_secret_key",
    "DEBUG": True,
    "PORT": int(os.environ.get("PORT", 5001)),
    "HOST": "127.0.0.1",
    "AMAP_API_KEY": "1389a7514ce65016496e0ee1349282b7",  # 确保API密钥有效
    "ROUTE_DATA_PATH": os.path.join(API_DIR, "../static/route_data.json"),
    "PRESET_ROUTE_FILES": {k: v["filename"] for k, v in ALL_PRESET_ROUTES.items()},
    "VALID_USER": {"admin": "123456"}
}

# 中文到英文地点映射
LOCATION_TRANSLATIONS = {
    "上海": "Shanghai", "宁波": "Ningbo", "广州": "Guangzhou", "深圳": "Shenzhen"
}

# 日志配置
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# --------------------------- 工具函数 --------------------------- 
def read_route_data():
    """读取默认航线数据"""
    file_path = CONFIG["ROUTE_DATA_PATH"]
    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump({"points": []}, f, indent=2)
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f).get("points", [])
    except Exception as e:
        logger.error(f"读取默认航线失败: {str(e)}")
        return []

def load_route_file(filename: str) -> list:
    """加载航线文件"""
    file_path = os.path.join(API_DIR, f"../static/{filename}")
    if not os.path.exists(file_path):
        # 如果文件不存在，从预设数据中创建
        logger.warning(f"航线文件不存在，从预设数据创建: {file_path}")
        for (s, e), route_info in ALL_PRESET_ROUTES.items():
            if route_info["filename"] == filename:
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump({"points": route_info["points"]}, f, indent=2)
                return route_info["points"]
        return []
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f).get("points", [])
    except Exception as e:
        logger.error(f"读取航线文件失败 {filename}: {str(e)}")
        return []

def get_preset_route(start_point: str, end_point: str) -> list:
    """获取预设航线，特别优化上海-宁波航线匹配"""
    if not start_point or not end_point:
        return []
        
    start = start_point.strip().lower()
    end = end_point.strip().lower()
    
    # 上海-宁波航线特别处理，增加更多匹配方式
    if (start in ["上海", "shanghai", "sh"]) and (end in ["宁波", "ningbo", "nb"]):
        logger.debug("匹配上海-宁波航线")
        return ALL_PRESET_ROUTES[("上海", "宁波")]["points"]
    
    if (start in ["宁波", "ningbo", "nb"]) and (end in ["上海", "shanghai", "sh"]):
        logger.debug("匹配宁波-上海航线")
        return ALL_PRESET_ROUTES[("宁波", "上海")]["points"]
    
    # 通用航线匹配
    for (s, e), route_info in ALL_PRESET_ROUTES.items():
        if (start == s.lower() or start == LOCATION_TRANSLATIONS.get(s, "").lower()) and \
           (end == e.lower() or end == LOCATION_TRANSLATIONS.get(e, "").lower()):
            logger.debug(f"匹配航线: {s} -> {e}")
            return route_info["points"]
    
    return []

def calculate_route_distance(points: list) -> float:
    """计算航程（海里），修复计算精度问题"""
    if len(points) < 2:
        logger.warning("计算航程失败：点数不足")
        return 0.0
        
    total_km = 0.0
    for i in range(len(points)-1):
        # 确保坐标有效
        try:
            lng1, lat1 = float(points[i][0]), float(points[i][1])
            lng2, lat2 = float(points[i+1][0]), float(points[i+1][1])
        except (ValueError, IndexError) as e:
            logger.error(f"坐标格式错误: {e}")
            continue
            
        # 哈弗辛公式计算两点距离
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lng = math.radians(lng2 - lng1)
        
        a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lng/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        
        # 地球半径取6371公里
        distance_km = 6371 * c
        total_km += distance_km
    
    # 转换为海里 (1海里 = 1.852公里)
    total_nm = total_km / 1.852
    logger.debug(f"计算航程: {total_km:.2f}公里 = {total_nm:.2f}海里")
    return round(total_nm, 2)

# --------------------------- Flask应用 --------------------------- 
def create_app():
    root_path = os.path.dirname(API_DIR)
    static_path = os.path.join(root_path, "static")
    template_path = os.path.join(root_path, "templates")

    # 创建目录
    if not os.path.exists(static_path):
        os.makedirs(static_path)
        # 创建默认航线文件
        with open(CONFIG["ROUTE_DATA_PATH"], "w", encoding="utf-8") as f:
            json.dump({"points": []}, f, indent=2)
        
        # 创建所有预设航线文件
        for (start, end), route_info in ALL_PRESET_ROUTES.items():
            file_path = os.path.join(static_path, route_info["filename"])
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump({"points": route_info["points"]}, f, indent=2)
            logger.debug(f"创建航线文件: {file_path}")

    if not os.path.exists(template_path):
        os.makedirs(template_path)
        # 这里省略模板文件创建代码，确保使用修复后的前端模板

    app = Flask(__name__, static_folder=static_path, template_folder=template_path)
    app.config.from_mapping(CONFIG)
    CORS(app)
    
    return app

app = create_app()

# --------------------------- 路由 --------------------------- 
@app.route("/")
def index():
    return redirect(url_for("login_page"))

@app.route("/login_page")
def login_page():
    return render_template("login.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form.get("username", "").strip()
        pwd = request.form.get("password", "").strip()
        if app.config["VALID_USER"].get(user) == pwd:
            # 登录成功，跳转到上海-宁波航线
            return redirect(url_for("route_map", start_point="上海", end_point="宁波"))
        return "用户名或密码错误（正确：admin/123456）", 401
    return render_template("login.html")

@app.route("/route_map")
def route_map():
    start = request.args.get("start_point", "").strip()
    end = request.args.get("end_point", "").strip()
    original = request.args.get("original_speed", "").strip()
    optimized = request.args.get("optimized_speed", "").strip()
    user_dist = request.args.get("distance", "").strip()

    # 获取航线数据，特别记录上海-宁波航线调试信息
    if start == "上海" and end == "宁波":
        logger.debug("请求上海-宁波航线数据")
    
    route_points = get_preset_route(start, end) if (start and end) else []
    logger.debug(f"获取航线点数量: {len(route_points)}")

    # 计算航程
    default_dist = calculate_route_distance(route_points) if route_points else ""
    final_dist = user_dist if user_dist else str(default_dist) if default_dist else ""
    
    # 上海-宁波航线特别输出调试信息
    if start == "上海" and end == "宁波":
        logger.debug(f"上海-宁波航线计算航程: {final_dist}海里")

    return render_template(
        "route_map.html",
        route_points=route_points,
        start_point=start,
        end_point=end,
        original_speed=original,
        optimized_speed=optimized,
        distance=final_dist,
        route_exists=len(route_points) > 0,
        amap_api_key=app.config["AMAP_API_KEY"]  # 传递API密钥到前端
    )

@app.route("/fuel_saving", methods=["GET"])
def fuel_saving():
    # 节油量计算逻辑保持不变...
    start = request.args.get("start_point", "").strip()
    end = request.args.get("end_point", "").strip()
    
    original_speed = request.args.get("original_speed", "").strip()
    optimized_speed = request.args.get("optimized_speed", "").strip()
    distance = request.args.get("distance", "").strip()
    
    if not distance and start and end:
        route_points = get_preset_route(start, end)
        if route_points:
            distance = str(calculate_route_distance(route_points))
    
    try:
        original = float(original_speed)
        optimized = float(optimized_speed)
        dist = float(distance)
        
        if original <= 0 or optimized <= 0 or dist <= 0 or optimized >= original:
            return "参数错误（优化航速需小于原航速且均为正数）", 400
            
        saving = round((original - optimized) * dist * 0.8, 2)
        route_points = get_preset_route(start, end) if (start and end) else []
        
        return render_template(
            "fuel_result.html",
            start_point=start,
            end_point=end,
            original=original,
            optimized=optimized,
            distance=dist,
            saving=saving,
            route_points=route_points
        )
    except ValueError:
        return "参数格式错误，请输入有效的数字", 400

@app.route("/export_pdf")
def export_pdf():
    # PDF导出逻辑保持不变...
    try:
        start = request.args.get("start_point", "").strip()
        end = request.args.get("end_point", "").strip()
        route_points = get_preset_route(start, end) if (start and end) else []
        
        fuel_data = {
            "start": start or "未知起点",
            "end": end or "未知终点",
            "original": request.args.get("original_speed", "未填写"),
            "optimized": request.args.get("optimized_speed", "未填写"),
            "distance": request.args.get("distance", str(calculate_route_distance(route_points)) if route_points else "未计算"),
            "saving": request.args.get("saving", "未计算")
        }

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        # PDF内容生成...
        
        buffer.seek(0)
        return send_file(buffer, mimetype='application/pdf', as_attachment=True,
                        download_name=f"船舶航线报告_{datetime.now().strftime('%Y%m%d')}.pdf")
    except Exception as e:
        return f"PDF导出失败：{str(e)}", 500

if __name__ == "__main__":
    print(f"启动服务：http://{CONFIG['HOST']}:{CONFIG['PORT']}")
    print("上海-宁波航线已特别优化，确保可正常显示")
    app.run(debug=CONFIG["DEBUG"], port=CONFIG["PORT"], host=CONFIG["HOST"])
    