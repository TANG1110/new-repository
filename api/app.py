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

# --------------------------- 1. 配置与初始化 --------------------------- 
API_DIR = os.path.abspath(os.path.dirname(__file__))

# 所有预设航线配置（重点检查上海-宁波航线数据）
ALL_PRESET_ROUTES = {
    ("上海", "宁波"): {
        "filename": "shanghai_ningbo.json",
        "points": [
            [121.582812, 31.372057], [121.642376, 31.372274], [121.719159, 31.329024],
            [121.808468, 31.277377], [121.862846, 31.266428], [122.037651, 31.251066],
            [122.101726, 31.06938],  [122.201797, 30.629212], [122.11298,  30.442215],
            [121.89094,  30.425198], [121.819322, 30.269414], [121.69957,  30.164341],
            [121.854434, 29.957196], [121.854434, 29.957196], [121.910951, 29.954561],
            [121.952784, 29.977126], [122.02619,  29.925834], [122.069602, 29.911468],
            [122.168266, 29.929254], [122.176948, 29.897783], [122.150901, 29.866987],
            [122.02136,  29.822932]
        ]
    },
    ("宁波", "上海"): {
        "filename": "ningbo_shanghai.json",
        "points": [
            [122.02136,  29.822932], [122.150901, 29.866987], [122.176948, 29.897783],
            [122.168266, 29.929254], [122.069602, 29.911468], [122.02619,  29.925834],
            [121.952784, 29.977126], [121.910951, 29.954561], [121.854434, 29.957196],
            [121.854434, 29.957196], [121.69957,  30.164341], [121.819322, 30.269414],
            [121.89094,  30.425198], [122.11298,  30.442215], [122.201797, 30.629212],
            [122.101726, 31.06938],  [122.037651, 31.251066], [121.862846, 31.266428],
            [121.808468, 31.277377], [121.719159, 31.329024], [121.642376, 31.372274],
            [121.582812, 31.372057]
        ]
    },
    # 其他航线保持不变...
    ("广州", "深圳"): {
        "filename": "guangzhou_shenzhen.json",
        "points": [[113.264434, 23.129162], [113.548813, 22.906414], [114.057868, 22.543096]]
    },
    ("深圳", "广州"): {
        "filename": "shenzhen_guangzhou.json",
        "points": [[114.057868, 22.543096], [113.548813, 22.906414], [113.264434, 23.129162]]
    }
}

# 系统配置
CONFIG = {
    "SECRET_KEY": "your_secret_key",
    "DEBUG": True,
    "PORT": int(os.environ.get("PORT", 5001)),
    "HOST": "0.0.0.0",  # 修改为0.0.0.0允许外部访问
    "AMAP_API_KEY": "1389a7514ce65016496e0ee1349282b7",  # 确保此API密钥有效
    "ROUTE_DATA_PATH": os.path.join(API_DIR, "../static/route_data.json"),
    "PRESET_ROUTE_FILES": {k: v["filename"] for k, v in ALL_PRESET_ROUTES.items()},
    "VALID_USER": {"admin": "123456"}
}

# 中文到英文地点映射
LOCATION_TRANSLATIONS = {
    "上海": "Shanghai", "北京": "Beijing", "广州": "Guangzhou",
    "深圳": "Shenzhen", "宁波": "Ningbo", "天津": "Tianjin",
    "青岛": "Qingdao", "大连": "Dalian", "厦门": "Xiamen",
    "香港": "Hong Kong"
}

# 日志配置 - 增强日志详细度以便调试
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# --------------------------- 2. 工具函数 --------------------------- 
def read_route_data():
    """读取默认航线数据"""
    try:
        file_path = CONFIG["ROUTE_DATA_PATH"]
        if not os.path.exists(file_path):
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump({"points": []}, f, indent=2)
            return []
            
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            logger.debug(f"读取默认航线数据: {len(data.get('points', []))}个点")
            return data.get("points", [])
    except Exception as e:
        logger.error(f"读取默认航线失败: {str(e)}")
        return []

def load_route_file(filename: str) -> list:
    """加载航线文件（增加详细日志）"""
    try:
        file_path = os.path.join(API_DIR, f"../static/{filename}")
        logger.debug(f"尝试加载航线文件: {file_path}")
        
        if not os.path.exists(file_path):
            logger.warning(f"航线文件不存在: {file_path}")
            return []
            
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            points = data.get("points", [])
            logger.debug(f"成功加载航线文件 {filename}, 共{len(points)}个坐标点")
            return points
    except Exception as e:
        logger.error(f"读取航线文件失败 {filename}: {str(e)}")
        return []

def get_preset_route(start_point: str, end_point: str) -> list:
    """获取预设航线（增强调试日志）"""
    if not start_point or not end_point:
        logger.debug("起点或终点为空，无法获取航线")
        return []
        
    start = start_point.strip().lower()
    end = end_point.strip().lower()
    logger.debug(f"尝试获取航线: {start} -> {end}")
    
    # 1. 精确匹配
    for (s, e), filename in CONFIG["PRESET_ROUTE_FILES"].items():
        if (start == s.lower() or start == LOCATION_TRANSLATIONS.get(s, "").lower()) and \
           (end == e.lower() or end == LOCATION_TRANSLATIONS.get(e, "").lower()):
            logger.debug(f"精确匹配到航线: {s} -> {e}, 文件名: {filename}")
            return load_route_file(filename)
    
    # 2. 部分匹配
    for (s, e), filename in CONFIG["PRESET_ROUTE_FILES"].items():
        if (start in s.lower() or start in LOCATION_TRANSLATIONS.get(s, "").lower()) and \
           (end in e.lower() or end in LOCATION_TRANSLATIONS.get(e, "").lower()):
            logger.debug(f"部分匹配到航线: {s} -> {e}, 文件名: {filename}")
            return load_route_file(filename)
    
    logger.debug(f"未找到匹配的航线: {start} -> {end}")
    return []

def calculate_route_distance(points: list) -> float:
    """计算航程（海里）- 优化算法并增加日志"""
    try:
        if len(points) < 2:
            logger.debug(f"计算航程失败: 坐标点不足({len(points)}个)")
            return 0.0
            
        total_km = 0.0
        for i in range(len(points)-1):
            lng1, lat1 = points[i]
            lng2, lat2 = points[i+1]
            
            # 转换为弧度
            lat1_rad = math.radians(lat1)
            lat2_rad = math.radians(lat2)
            delta_lat = math.radians(lat2 - lat1)
            delta_lng = math.radians(lng2 - lng1)
            
            # 哈弗辛公式计算两点之间的距离
            a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lng/2)**2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
            distance_km = 6371 * c  # 地球半径约6371公里
            total_km += distance_km
            
        # 转换为海里 (1海里 = 1.852公里)
        total_nm = round(total_km / 1.852, 2)
        logger.debug(f"计算航程完成: {total_km:.2f}公里 = {total_nm:.2f}海里")
        return total_nm
    except Exception as e:
        logger.error(f"计算航程时发生错误: {str(e)}")
        return 0.0

def translate_location(chinese_name):
    """中文地点转英文"""
    if not chinese_name:
        return "Not Specified"
    return LOCATION_TRANSLATIONS.get(chinese_name.strip(), chinese_name)

# --------------------------- 3. PDF生成 ---------------------------
def generate_route_report(route_points, fuel_data):
    # 保持不变...
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=0.8*cm,
        leftMargin=0.8*cm,
        topMargin=0.8*cm,
        bottomMargin=0.8*cm
    )

    font_name = 'Helvetica'
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name='Title_EN',
        parent=styles['Title'],
        fontName=font_name,
        fontSize=18,
        alignment=1,
        spaceAfter=8
    ))
    styles.add(ParagraphStyle(
        name='Normal_EN',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=10,
        leading=12
    ))
    styles.add(ParagraphStyle(
        name='Heading2_EN',
        parent=styles['Heading2'],
        fontName=font_name,
        fontSize=14,
        spaceBefore=6,
        spaceAfter=6
    ))

    elements = []
    elements.append(Paragraph("Ship Route Visualization System Report", styles['Title_EN']))
    elements.append(Paragraph(f"Generation Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal_EN']))
    elements.append(Spacer(1, 6))

    # 航线坐标表格
    elements.append(Paragraph("1. Route Coordinate Information", styles['Heading2_EN']))
    if route_points:
        table_data = [["No.", "Longitude", "Latitude"]]
        for idx, (lng, lat) in enumerate(route_points, 1):
            table_data.append([str(idx), f"{lng:.6f}", f"{lat:.6f}"])
        
        table_width = 21*cm - 1.6*cm
        col_widths = [table_width*0.15, table_width*0.425, table_width*0.425]
        row_height = (24*cm) / len(table_data)
        
        route_table = Table(table_data, colWidths=col_widths, rowHeights=row_height)
        route_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), font_name),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(route_table)
    else:
        elements.append(Paragraph("⚠️ No route coordinate data obtained", styles['Normal_EN']))
    elements.append(Spacer(1, 6))

    # 节油量表格
    elements.append(Paragraph("2. Fuel Saving Calculation Results", styles['Heading2_EN']))
    if fuel_data:
        translated_start = translate_location(fuel_data.get('start'))
        translated_end = translate_location(fuel_data.get('end'))
        
        fuel_table_data = [
            ["Parameter", "Value"],
            ["Start Point", translated_start],
            ["End Point", translated_end],
            ["Original Speed", f"{fuel_data.get('original')} knots"],
            ["Optimized Speed", f"{fuel_data.get('optimized')} knots"],
            ["Route Distance", f"{fuel_data.get('distance')} nautical miles"],
            ["Fuel Saved", f"{fuel_data.get('saving')} tons"]
        ]
        
        fuel_table = Table(fuel_table_data, colWidths=[table_width*0.3, table_width*0.7])
        fuel_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), font_name),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkgreen),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(fuel_table)
    else:
        elements.append(Paragraph("⚠️ No fuel saving calculation data obtained", styles['Normal_EN']))

    doc.build(elements)
    buffer.seek(0)
    return buffer

# --------------------------- 4. Flask应用初始化 --------------------------- 
def create_app():
    root_path = os.path.dirname(API_DIR)
    static_path = os.path.join(root_path, "static")
    template_path = os.path.join(root_path, "templates")

    # 创建静态目录和航线文件
    if not os.path.exists(static_path):
        os.makedirs(static_path)
        logger.debug(f"创建静态目录: {static_path}")
        
        # 生成空默认航线
        with open(CONFIG["ROUTE_DATA_PATH"], "w", encoding="utf-8") as f:
            json.dump({"points": []}, f, indent=2)
        
        # 批量生成所有航线文件
        for (start, end), route_info in ALL_PRESET_ROUTES.items():
            file_path = os.path.join(static_path, route_info["filename"])
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump({"points": route_info["points"]}, f, indent=2)
            logger.debug(f"生成航线文件: {file_path}, 包含{len(route_info['points'])}个点")

    # 创建模板目录
    if not os.path.exists(template_path):
        os.makedirs(template_path)
        logger.debug(f"创建模板目录: {template_path}")
        # 模板文件内容保持不变...

    app = Flask(__name__, static_folder=static_path, template_folder=template_path)
    app.config.from_mapping(CONFIG)
    
    # 跨域支持
    CORS(app, resources={r"/*": {"origins": "*"}})
    
    return app

app = create_app()

# --------------------------- 5. 路由 --------------------------- 
@app.route("/")
def index():
    return redirect(url_for("login_page"))

@app.route("/get_location/<lng>/<lat>")
def get_location(lng, lat):
    try:
        res = requests.get(
            f"https://restapi.amap.com/v3/geocode/regeo?location={lng},{lat}&key={app.config['AMAP_API_KEY']}", 
            timeout=10
        )
        return res.json()
    except Exception as e:
        logger.error(f"获取地理位置失败: {str(e)}")
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
        
    # 普通用户登录
    if app.config["VALID_USER"].get(user) == pwd:
        logger.debug(f"用户 {user} 登录成功，跳转到上海-宁波航线")
        return redirect(url_for("route_map", start_point="上海", end_point="宁波"))
        
    # 评委账号
    if user == "judge" and pwd == "ship2025":
        return render_template("judge_easter_egg.html", team_info={
            "team_name": "海算云帆",
            "members": ["陈倚薇（队长/计算机组）", "刘迪瑶（计算机组）", "唐辉婷（计算机组）","吴珊（金融组）","周子煜（设计组）"],
            "project_intro": "船舶航线与节油计算系统：全航线统一管理，支持航线展示、油耗计算与PDF导出。",
            "tech_stack": ["Flask（后端框架）", "高德地图API（地图服务）", "HTML/CSS（前端界面）"],
            "development_time": "2025年8月12日-8月25日",
            "achievements": ["实现全航线统一管理", "完成航线可视化", "开发节油计算功能", "支持系统嵌套", "适配移动端访问"]
        })
        
    logger.warning(f"用户 {user} 登录失败")
    return "用户名或密码错误（正确：admin/123456）", 401

@app.route("/route_map")
def route_map():
    # 获取参数
    start = request.args.get("start_point", "").strip()
    end = request.args.get("end_point", "").strip()
    original = request.args.get("original_speed", "").strip()
    optimized = request.args.get("optimized_speed", "").strip()
    user_dist = request.args.get("distance", "").strip()

    logger.debug(f"访问航线地图: {start} -> {end}")
    
    # 获取航线（重点调试上海-宁波航线）
    route_points = get_preset_route(start, end) if (start and end) else []
    logger.debug(f"获取到航线点数量: {len(route_points)}")
    
    # 计算航程（修复上海-宁波航线计算问题）
    default_dist = 0.0
    if route_points:
        default_dist = calculate_route_distance(route_points)
        logger.debug(f"自动计算航程: {default_dist} 海里")
    
    final_dist = user_dist if user_dist else (str(default_dist) if default_dist else "")

    # 特别检查上海-宁波航线
    if start == "上海" and end == "宁波":
        logger.debug(f"上海-宁波航线检查: 点数量={len(route_points)}, 计算航程={default_dist}")

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
    # 代码保持不变...
    start = request.args.get("start_point", "").strip()
    end = request.args.get("end_point", "").strip()
    
    original_speed = request.args.get("original_speed", "").strip()
    optimized_speed = request.args.get("optimized_speed", "").strip()
    distance = request.args.get("distance", "").strip()
    
    # 航程为空时自动计算
    if not distance and start and end:
        route_points = get_preset_route(start, end)
        if route_points:
            distance = str(calculate_route_distance(route_points))
    
    required = ["original_speed", "optimized_speed"]
    if not all(request.args.get(p) for p in required) or not distance:
        return "参数不完整，请确保填写了航速且航程已计算", 400
        
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
    # 代码保持不变...
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

        pdf_buffer = generate_route_report(route_points, fuel_data)
        response = make_response(send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"船舶航线报告_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
        ))
        response.headers['Cache-Control'] = 'no-store, no-cache'
        return response

    except Exception as e:
        logger.error(f"PDF导出失败: {str(e)}")
        return f"PDF导出失败：{str(e)}", 500

if __name__ == "__main__":
    logger.info(f"启动船舶航线系统，访问地址: http://{CONFIG['HOST']}:{CONFIG['PORT']}")
    app.run(debug=CONFIG["DEBUG"], port=CONFIG["PORT"], host=CONFIG["HOST"])
    