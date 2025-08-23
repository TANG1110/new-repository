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

# --------------------------- 配置区 --------------------------- 
API_DIR = os.path.abspath(os.path.dirname(__file__))
# 10条航线文件路径（与手动添加的文件名完全对应）
PRESET_ROUTE_FILES = {
    "上海-宁波": os.path.join(API_DIR, "../static/shanghai_ningbo.json"),
    "宁波-上海": os.path.join(API_DIR, "../static/ningbo_shanghai.json"),
    "广州-深圳": os.path.join(API_DIR, "../static/guangzhou_shenzhen.json"),
    "深圳-广州": os.path.join(API_DIR, "../static/shenzhen_guangzhou.json"),
    "青岛-大连": os.path.join(API_DIR, "../static/qingdao_dalian.json"),
    "大连-青岛": os.path.join(API_DIR, "../static/dalian_qingdao.json"),
    "天津-青岛": os.path.join(API_DIR, "../static/tianjin_qingdao.json"),
    "青岛-天津": os.path.join(API_DIR, "../static/qingdao_tianjin.json"),
    "厦门-香港": os.path.join(API_DIR, "../static/xiamen_hongkong.json"),
    "香港-厦门": os.path.join(API_DIR, "../static/hongkong_xiamen.json")
}

CONFIG = {
    "SECRET_KEY": "your_secret_key",
    "DEBUG": True,
    "PORT": int(os.environ.get("PORT", 5001)),
    "HOST": "127.0.0.1",
    "AMAP_API_KEY": "1389a7514ce65016496e0ee1349282b7",
    "ROUTE_DATA_PATH": os.path.join(API_DIR, "../static/route_data.json"),
    "VALID_USER": {"admin": "123456"}
}

# 地点中英文映射
LOCATION_TRANSLATIONS = {
    "上海": "Shanghai",
    "宁波": "Ningbo",
    "广州": "Guangzhou",
    "深圳": "Shenzhen",
    "青岛": "Qingdao",
    "大连": "Dalian",
    "天津": "Tianjin",
    "厦门": "Xiamen",
    "香港": "Hong Kong"
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
        logger.warning(f"默认航线文件不存在: {file_path}")
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f).get("points", [])
    except Exception as e:
        logger.error(f"读取默认航线失败: {str(e)}")
        return []

def get_preset_route(start_point: str, end_point: str) -> list:
    """获取预设航线（所有航线逻辑与上海-宁波完全一致）"""
    if not start_point or not end_point:
        return []
    
    # 统一处理输入，增强匹配容错
    start = start_point.strip().lower()
    end = end_point.strip().lower()
    
    # 地点别名映射（支持多种输入形式）
    location_aliases = {
        "上海": ["上海", "shanghai", "沪"],
        "宁波": ["宁波", "ningbo", "甬"],
        "广州": ["广州", "guangzhou", "穗", "gz"],
        "深圳": ["深圳", "shenzhen", "sz"],
        "青岛": ["青岛", "qingdao", "qd"],
        "大连": ["大连", "dalian", "dl"],
        "天津": ["天津", "tianjin", "津", "tj"],
        "厦门": ["厦门", "xiamen", "xm"],
        "香港": ["香港", "hong kong", "hk", "港"]
    }
    
    # 匹配标准地点名称
    matched_start = None
    matched_end = None
    for std_name, aliases in location_aliases.items():
        if any(alias in start for alias in aliases) and not matched_start:
            matched_start = std_name
        if any(alias in end for alias in aliases) and not matched_end:
            matched_end = std_name
    
    if not matched_start or not matched_end:
        logger.warning(f"未匹配到有效地点: {start_point}→{end_point}")
        return []
    
    # 构建航线键（与文件名对应）
    route_key = f"{matched_start}-{matched_end}"
    if route_key not in PRESET_ROUTE_FILES:
        logger.warning(f"无对应航线文件: {route_key}")
        return []
    
    # 读取航线文件（与上海-宁波读取逻辑完全一致）
    try:
        file_path = PRESET_ROUTE_FILES[route_key]
        if not os.path.exists(file_path):
            logger.error(f"航线文件不存在: {file_path}")
            return []
            
        with open(file_path, "r", encoding="utf-8") as f:
            route_data = json.load(f)
            return route_data.get("points", [])
    except Exception as e:
        logger.error(f"读取航线文件失败: {str(e)}")
        return []

def calculate_route_distance(points: list) -> float:
    """计算航线距离（统一逻辑）"""
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
    """地点翻译"""
    if not chinese_name:
        return "Not Specified"
    return LOCATION_TRANSLATIONS.get(chinese_name.strip(), chinese_name)

# --------------------------- PDF生成函数 ---------------------------
def generate_route_report(route_points, fuel_data):
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
    elements.append(Paragraph("Ship Route Visualization Report", styles['Title_EN']))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles['Normal_EN']))
    elements.append(Spacer(1, 6))

    # 航线坐标表格
    elements.append(Paragraph("1. Route Coordinates", styles['Heading2_EN']))
    if route_points:
        table_data = [["No.", "Longitude", "Latitude"]]
        for idx, (lng, lat) in enumerate(route_points, 1):
            table_data.append([str(idx), f"{lng:.6f}", f"{lat:.6f}"])
        
        table_width = 21*cm - 1.6*cm
        col_widths = [table_width*0.15, table_width*0.425, table_width*0.425]
        route_table = Table(table_data, colWidths=col_widths)
        route_table.setStyle(TableStyle([
            ('FONTNAME', (0,0), (-1,-1), font_name),
            ('BACKGROUND', (0,0), (-1,0), colors.darkblue),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('GRID', (0,0), (-1,-1), 1, colors.black)
        ]))
        elements.append(route_table)
    else:
        elements.append(Paragraph("No route data available", styles['Normal_EN']))
    elements.append(Spacer(1, 6))

    # 节油量表格
    elements.append(Paragraph("2. Fuel Saving Calculation", styles['Heading2_EN']))
    if fuel_data:
        fuel_table_data = [
            ["Parameter", "Value"],
            ["Start", translate_location(fuel_data.get('start'))],
            ["End", translate_location(fuel_data.get('end'))],
            ["Original Speed", f"{fuel_data.get('original')} knots"],
            ["Optimized Speed", f"{fuel_data.get('optimized')} knots"],
            ["Distance", f"{fuel_data.get('distance')} nm"],
            ["Fuel Saved", f"{fuel_data.get('saving')} tons"]
        ]
        fuel_table = Table(fuel_table_data, colWidths=[table_width*0.3, table_width*0.7])
        fuel_table.setStyle(TableStyle([
            ('FONTNAME', (0,0), (-1,-1), font_name),
            ('BACKGROUND', (0,0), (-1,0), colors.darkgreen),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (0,0), (0,-1), 'LEFT'),
            ('ALIGN', (1,0), (-1,-1), 'CENTER'),
            ('GRID', (0,0), (-1,-1), 1, colors.black)
        ]))
        elements.append(fuel_table)
    else:
        elements.append(Paragraph("No fuel data available", styles['Normal_EN']))

    doc.build(elements)
    buffer.seek(0)
    return buffer

# --------------------------- 应用初始化 --------------------------- 
def create_app():
    root_path = os.path.dirname(API_DIR)
    static_path = os.path.join(root_path, "static")
    template_path = os.path.join(root_path, "templates")

    # 确保目录存在
    if not os.path.exists(static_path):
        os.makedirs(static_path)
    if not os.path.exists(template_path):
        os.makedirs(template_path)
        with open(os.path.join(template_path, "base.html"), "w", encoding="utf-8") as f:
            f.write("""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>{% block title %}船舶系统{% endblock %}</title>{% block head_css %}{% endblock %}</head><body style="margin:0; padding:20px; background:#f5f7fa; font-family:Arial,sans-serif;">{% block content %}{% endblock %}</body></html>""")

    app = Flask(__name__, static_folder=static_path, template_folder=template_path)
    app.config.from_mapping(CONFIG)
    return app

# --------------------------- 路由定义 --------------------------- 
app = create_app()

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
        return "用户名和密码不能为空", 400
    if app.config["VALID_USER"].get(user) == pwd:
        return redirect(url_for("login_success", username=user))
    if user == "judge" and pwd == "ship2025":
        return render_template("judge_easter_egg.html", team_info={
            "team_name": "海算云帆",
            "members": ["陈倚薇（队长/计算机组）", "刘迪瑶（计算机组）", "唐辉婷（计算机组）","吴珊（金融组）","周子煜（设计组）"],
            "project_intro": "船舶航线可视化与节油系统：支持航线展示、油耗计算和PDF报告导出功能。",
            "tech_stack": ["Flask（后端框架）", "高德地图API（地图服务）", "ReportLab（PDF生成）"],
            "development_time": "2025年8月12日-8月25日",
            "achievements": ["完成基础框架搭建", "实现航线可视化", "开发节油计算功能", "支持PDF报告导出"]
        })
    return "用户名或密码错误（正确：admin/123456）", 401

@app.route("/login_success")
def login_success():
    return render_template("login_success.html", username=request.args.get("username", "用户"))

@app.route("/route_map")
def route_map():
    start = request.args.get("start_point", "").strip()
    end = request.args.get("end_point", "").strip()
    original = request.args.get("original_speed", "")
    optimized = request.args.get("optimized_speed", "")
    user_dist = request.args.get("distance", "")

    # 加载航线（所有航线使用同一套逻辑）
    route_points = get_preset_route(start, end) if (start and end) else read_route_data()
    default_dist = calculate_route_distance(route_points)
    final_dist = user_dist if user_dist else str(default_dist)

    return render_template(
        "route_map.html",
        route_points=json.dumps(route_points),  # 确保传递正确的JSON格式
        start_point=start,
        end_point=end,
        original_speed=original,
        optimized_speed=optimized,
        distance=final_dist
    )

@app.route("/fuel_saving", methods=["GET"])
def fuel_saving():
    start = request.args.get("start_point", "").strip()
    end = request.args.get("end_point", "").strip()
    required = ["original_speed", "optimized_speed", "distance"]
    if not all(request.args.get(p) for p in required):
        return "参数不完整", 400
    try:
        original = float(request.args["original_speed"])
        optimized = float(request.args["optimized_speed"])
        dist = float(request.args["distance"])
        if original <=0 or optimized <=0 or dist <=0 or optimized >= original:
            return "参数错误（优化航速需小于原航速）", 400
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
        return "参数格式错误", 400

@app.route("/export_pdf")
def export_pdf():
    try:
        start = request.args.get("start_point", "").strip()
        end = request.args.get("end_point", "").strip()
        route_points = get_preset_route(start, end)
        if not route_points:
            #  fallback到上海-宁波航线
            with open(PRESET_ROUTE_FILES["上海-宁波"], "r", encoding="utf-8") as f:
                route_points = json.load(f).get("points", [])

        fuel_data = {
            "start": start or "上海",
            "end": end or "宁波",
            "original": request.args.get("original_speed", "N/A"),
            "optimized": request.args.get("optimized_speed", "N/A"),
            "distance": request.args.get("distance", str(calculate_route_distance(route_points))),
            "saving": request.args.get("saving", "N/A")
        }

        pdf_buffer = generate_route_report(route_points, fuel_data)
        response = make_response(send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"route_report_{datetime.now().strftime('%Y%m%d')}.pdf"
        ))
        response.headers['Cache-Control'] = 'no-store'
        return response
    except Exception as e:
        logger.error(f"PDF导出失败: {str(e)}")
        return f"PDF导出失败：{str(e)}", 500

if __name__ == "__main__":
    app.run(
        debug=CONFIG["DEBUG"],
        port=CONFIG["PORT"],
        host=CONFIG["HOST"]
    )
    