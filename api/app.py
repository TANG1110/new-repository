import os
import json
import requests
import logging
import math
from io import BytesIO
from datetime import datetime
from flask import Flask, request, render_template, redirect, url_for, make_response, send_file
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# --------------------------- 配置区（适配 Vercel 路径） --------------------------- 
API_DIR = os.path.abspath(os.path.dirname(__file__))
# Vercel 静态文件目录默认是 /static，这里自动适配
STATIC_DIR = os.path.join(API_DIR, "static")
if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR)

CONFIG = {
    "SECRET_KEY": os.environ.get("SECRET_KEY", "your_secret_key"),  # Vercel 环境变量获取
    "DEBUG": os.environ.get("DEBUG", "False") == "True",
    "PORT": int(os.environ.get("PORT", 3000)),  # Vercel 默认端口
    "HOST": "0.0.0.0",  # Vercel 必须监听 0.0.0.0
    "AMAP_API_KEY": os.environ.get("AMAP_API_KEY", "1389a7514ce65016496e0ee1349282b7"),
    "ROUTE_DATA_PATH": os.path.join(STATIC_DIR, "route_data.json"),
    "PRESET_ROUTE_FILES": {
        ("上海", "宁波"): "shanghai_ningbo.json",
        ("宁波", "上海"): "ningbo_shanghai.json",
        ("广州", "深圳"): "guangzhou_shenzhen.json",
        ("深圳", "广州"): "shenzhen_guangzhou.json",
        ("青岛", "大连"): "qingdao_dalian.json",
        ("大连", "青岛"): "dalian_qingdao.json",
        ("天津", "青岛"): "tianjin_qingdao.json",
        ("青岛", "天津"): "qingdao_tianjin.json",
        ("厦门", "香港"): "xiamen_hongkong.json",
        ("香港", "厦门"): "hongkong_xiamen.json"
    },
    "VALID_USER": {"admin": os.environ.get("ADMIN_PWD", "123456")}
}

# 中文到英文地点映射（确保 PDF 英文显示兼容）
LOCATION_TRANSLATIONS = {
    "上海": "Shanghai", "北京": "Beijing", "广州": "Guangzhou",
    "深圳": "Shenzhen", "宁波": "Ningbo", "天津": "Tianjin",
    "青岛": "Qingdao", "大连": "Dalian", "厦门": "Xiamen",
    "香港": "Hong Kong", "澳门": "Macau", "重庆": "Chongqing",
    "南京": "Nanjing", "杭州": "Hangzhou", "苏州": "Suzhou", "武汉": "Wuhan"
}

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# --------------------------- 工具函数 --------------------------- 
def read_route_data():
    """读取默认航线（仅在无起点终点时返回空）"""
    file_path = CONFIG["ROUTE_DATA_PATH"]
    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump({"points": []}, f, indent=2)  # 初始化空航线
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f).get("points", [])
    except Exception as e:
        logger.error(f"读取默认航线失败: {str(e)}")
        return []

def get_preset_route(start_point: str, end_point: str) -> list:
    """根据起点终点匹配航线（仅在两者都存在时生效）"""
    if not start_point or not end_point:
        return []
        
    start = start_point.strip().lower()
    end = end_point.strip().lower()
    
    # 匹配预设航线
    for (s, e), filename in CONFIG["PRESET_ROUTE_FILES"].items():
        if (start == s.lower() or start == LOCATION_TRANSLATIONS.get(s, "").lower()) and \
           (end == e.lower() or end == LOCATION_TRANSLATIONS.get(e, "").lower()):
            return load_route_file(filename)
    
    for (s, e), filename in CONFIG["PRESET_ROUTE_FILES"].items():
        if (start in s.lower() or start in LOCATION_TRANSLATIONS.get(s, "").lower()) and \
           (end in e.lower() or end in LOCATION_TRANSLATIONS.get(e, "").lower()):
            return load_route_file(filename)
    
    return []

def load_route_file(filename: str) -> list:
    """加载静态目录下的航线文件"""
    file_path = os.path.join(STATIC_DIR, filename)
    if not os.path.exists(file_path):
        logger.warning(f"航线文件不存在: {file_path}")
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f).get("points", [])
    except Exception as e:
        logger.error(f"读取航线文件失败 {filename}: {str(e)}")
        return []

def calculate_route_distance(points: list) -> float:
    """计算航线距离（海里）"""
    total_km = 0.0
    for i in range(len(points)-1):
        lng1, lat1 = points[i]
        lng2, lat2 = points[i+1]
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2-lat1)
        delta_lng = math.radians(lng2-lng1)
        a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad)*math.cos(lat2_rad)*math.sin(delta_lng/2)**2
        total_km += 6371 * (2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))
    return round(total_km / 1.852, 2)  # 转换为海里

def translate_location(chinese_name):
    """中文地点转英文（适配 PDF 英文显示）"""
    if not chinese_name:
        return "Not Specified"
    translated = LOCATION_TRANSLATIONS.get(chinese_name.strip(), None)
    if translated:
        return translated
    for cn, en in LOCATION_TRANSLATIONS.items():
        if cn in chinese_name:
            return en
    return chinese_name

# --------------------------- PDF 生成（适配 Vercel 无中文字体环境） ---------------------------
def generate_route_report(route_points, fuel_data):
    """生成英文 PDF 报告（避免 Vercel 字体依赖）"""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=0.8*cm,
        leftMargin=0.8*cm,
        topMargin=0.8*cm,
        bottomMargin=0.8*cm
    )

    # 使用系统默认英文字体（Vercel 环境兼容）
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

    # 航线坐标信息
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

    # 节油计算结果（英文显示，避免中文问题）
    elements.append(Paragraph("2. Fuel Saving Calculation Results", styles['Heading2_EN']))
    if fuel_data:
        # 强制转换为英文显示
        fuel_table_data = [
            ["Parameter", "Value"],
            ["Start Point", translate_location(fuel_data.get('start'))],
            ["End Point", translate_location(fuel_data.get('end'))],
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

# --------------------------- Flask 应用（适配 Vercel） --------------------------- 
def create_app():
    """创建 Flask 应用（适配 Vercel 目录结构）"""
    app = Flask(__name__, 
                static_folder=STATIC_DIR,
                template_folder=os.path.join(API_DIR, "templates"))  # 模板目录
    app.config.from_mapping(CONFIG)
    
    # 初始化默认航线文件（空）
    if not os.path.exists(CONFIG["ROUTE_DATA_PATH"]):
        with open(CONFIG["ROUTE_DATA_PATH"], "w", encoding="utf-8") as f:
            json.dump({"points": []}, f, indent=2)
    
    return app

app = create_app()

# 路由定义
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
        return "Username and password cannot be empty", 400
    if app.config["VALID_USER"].get(user) == pwd:
        return redirect(url_for("login_success", username=user))
    if user == "judge" and pwd == "ship2025":
        return render_template("judge_easter_egg.html", team_info={
            "team_name": "HaiSuan YunFan",
            "members": ["Chen Yiwei (Leader/Dev)", "Liu Diyao (Dev)", "Tang Huiting (Dev)", 
                       "Wu Shan (Finance)", "Zhou Ziyu (Design)"],
            "project_intro": "Ship Route Visualization & Fuel Saving System: Supports route display, fuel calculation, and PDF report export to optimize ship navigation efficiency.",
            "tech_stack": ["Flask (Backend)", "AMAP API (Maps)", "ReportLab (PDF)", "HTML/CSS (Frontend)"],
            "development_time": "Aug 12-25, 2025",
            "achievements": ["Basic framework completed", "Route visualization", "Fuel saving calculation", 
                           "PDF report export", "Mobile adaptation"]
        })
    return "Incorrect username or password (correct: admin/123456)", 401

@app.route("/login_success")
def login_success():
    return render_template("login_success.html", username=request.args.get("username", "User"))

@app.route("/route_map")
def route_map():
    """航线地图页面（仅在输入起点终点后加载航线）"""
    start = request.args.get("start_point", "").strip()
    end = request.args.get("end_point", "").strip()
    original = request.args.get("original_speed", "")
    optimized = request.args.get("optimized_speed", "")
    user_dist = request.args.get("distance", "")

    # 核心修改：仅在起点和终点都存在时加载航线
    route_points = get_preset_route(start, end) if (start and end) else []
    
    # 计算距离（仅在有航线且用户未输入时自动计算）
    default_dist = calculate_route_distance(route_points) if route_points else ""
    final_dist = user_dist if user_dist else str(default_dist) if default_dist else ""

    return render_template(
        "route_map.html",
        route_points=route_points,
        start_point=start,
        end_point=end,
        original_speed=original,
        optimized_speed=optimized,
        distance=final_dist
    )

@app.route("/fuel_saving", methods=["GET"])
def fuel_saving():
    """节油量计算"""
    start = request.args.get("start_point", "").strip()
    end = request.args.get("end_point", "").strip()
    required = ["original_speed", "optimized_speed", "distance"]
    if not all(request.args.get(p) for p in required):
        return "Missing parameters", 400
    try:
        original = float(request.args["original_speed"])
        optimized = float(request.args["optimized_speed"])
        dist = float(request.args["distance"])
        if original <=0 or optimized <=0 or dist <=0 or optimized >= original:
            return "Invalid parameters (optimized speed must be less than original)", 400
        saving = round((original - optimized) * dist * 0.8, 2)
        return render_template(
            "fuel_result.html",
            start_point=start,
            end_point=end,
            original=original,
            optimized=optimized,
            distance=dist,
            saving=saving
        )
    except ValueError:
        return "Invalid parameter format", 400

@app.route("/export_pdf")
def export_pdf():
    """导出 PDF 报告（英文显示，适配 Vercel）"""
    try:
        start = request.args.get("start_point", "").strip()
        end = request.args.get("end_point", "").strip()
        route_points = get_preset_route(start, end) if (start and end) else []

        fuel_data = {
            "start": start or "Unknown",
            "end": end or "Unknown",
            "original": request.args.get("original_speed", "Not specified"),
            "optimized": request.args.get("optimized_speed", "Not specified"),
            "distance": request.args.get("distance", str(calculate_route_distance(route_points)) if route_points else "Not calculated"),
            "saving": request.args.get("saving", "Not calculated")
        }

        pdf_buffer = generate_route_report(route_points, fuel_data)
        response = make_response(send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"ship_route_report_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
        ))
        response.headers['Cache-Control'] = 'no-store, no-cache'
        return response

    except Exception as e:
        logger.error(f"PDF export failed: {str(e)}")
        return f"PDF export failed: {str(e)}", 500

# Vercel 入口
if __name__ == "__main__":
    app.run(
        debug=app.config["DEBUG"],
        port=app.config["PORT"],
        host=app.config["HOST"]
    )