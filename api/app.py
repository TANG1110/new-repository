import os
import json
import requests
import logging
import math
from io import BytesIO
from datetime import datetime
from flask import Flask, request, render_template, redirect, url_for, make_response, send_file
# PDF生成相关库
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import cm

# --------------------------- 配置区 --------------------------- 
API_DIR = os.path.abspath(os.path.dirname(__file__))
CONFIG = {
    "SECRET_KEY": "your_secret_key",
    "DEBUG": True,
    "PORT": int(os.environ.get("PORT", 5001)),
    "HOST": "127.0.0.1",
    "AMAP_API_KEY": "1389a7514ce65016496e0ee1349282b7",
    "ROUTE_DATA_PATH": os.path.join(API_DIR, "../static/route_data.json"),  # 空默认航线
    "PRESET_ROUTE_PATH": os.path.join(API_DIR, "../static/shanghai_ningbo_route.json"),  # 上海-宁波默认航线
    # 10条预设航线
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
    "VALID_USER": {"admin": "123456"}
}

# 中文到英文地点映射（PDF用）
LOCATION_TRANSLATIONS = {
    "上海": "Shanghai", "北京": "Beijing", "广州": "Guangzhou",
    "深圳": "Shenzhen", "宁波": "Ningbo", "天津": "Tianjin",
    "青岛": "Qingdao", "大连": "Dalian", "厦门": "Xiamen",
    "香港": "Hong Kong", "澳门": "Macau", "重庆": "Chongqing",
    "南京": "Nanjing", "杭州": "Hangzhou", "苏州": "Suzhou", "武汉": "Wuhan"
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
    """读取空默认航线（未输入起点终点时返回）"""
    file_path = CONFIG["ROUTE_DATA_PATH"]
    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump({"points": []}, f, indent=2)
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f).get("points", [])
    except Exception as e:
        logger.error(f"❌ 读取默认航线失败: {str(e)}")
        return []

def load_route_file(filename: str) -> list:
    """加载10条预设航线文件"""
    file_path = os.path.join(API_DIR, f"../static/{filename}")
    if not os.path.exists(file_path):
        logger.warning(f"⚠️ 航线文件不存在: {file_path}")
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f).get("points", [])
    except Exception as e:
        logger.error(f"❌ 读取航线文件失败 {filename}: {str(e)}")
        return []

def get_preset_route(start_point: str, end_point: str) -> list:
    """
    航线匹配逻辑：
    1. 仅当起点和终点都输入时才匹配
    2. 优先匹配10条预设航线，再匹配上海-宁波默认航线
    """
    if not start_point or not end_point:  # 核心：未输入起点/终点时返回空
        return []
        
    start = start_point.strip().lower()
    end = end_point.strip().lower()
    
    # 1. 匹配10条预设航线
    for (s, e), filename in CONFIG["PRESET_ROUTE_FILES"].items():
        if (start == s.lower() or start == LOCATION_TRANSLATIONS.get(s, "").lower()) and \
           (end == e.lower() or end == LOCATION_TRANSLATIONS.get(e, "").lower()):
            return load_route_file(filename)
    
    # 2. 部分匹配（如输入"sh"匹配"Shanghai"）
    for (s, e), filename in CONFIG["PRESET_ROUTE_FILES"].items():
        if (start in s.lower() or start in LOCATION_TRANSLATIONS.get(s, "").lower()) and \
           (end in e.lower() or end in LOCATION_TRANSLATIONS.get(e, "").lower()):
            return load_route_file(filename)
    
    # 3. 匹配上海-宁波默认航线
    if (start in ["上海", "shanghai"] and end in ["宁波", "ningbo"]):
        try:
            with open(CONFIG["PRESET_ROUTE_PATH"], "r", encoding="utf-8") as f:
                return json.load(f).get("points", [])
        except Exception as e:
            logger.error(f"❌ 读取上海-宁波航线失败: {str(e)}")
            return []
    
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
    return round(total_km / 1.852, 2)

def translate_location(chinese_name):
    """中文转英文（PDF用）"""
    if not chinese_name:
        return "Not Specified"
    translated = LOCATION_TRANSLATIONS.get(chinese_name.strip(), None)
    if translated:
        return translated
    for cn, en in LOCATION_TRANSLATIONS.items():
        if cn in chinese_name:
            return en
    return chinese_name

# --------------------------- PDF生成（英文输出） ---------------------------
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

# --------------------------- Flask 应用初始化 --------------------------- 
def create_app():
    root_path = os.path.dirname(API_DIR)
    static_path = os.path.join(root_path, "static")
    template_path = os.path.join(root_path, "templates")

    # 创建静态目录+上海-宁波默认航线
    if not os.path.exists(static_path):
        os.makedirs(static_path)
        # 空默认航线
        with open(CONFIG["ROUTE_DATA_PATH"], "w", encoding="utf-8") as f:
            json.dump({"points": []}, f, indent=2)
        # 上海-宁波详细航线（22个坐标点）
        sh_nb_route = {
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
        }
        with open(CONFIG["PRESET_ROUTE_PATH"], "w", encoding="utf-8") as f:
            json.dump(sh_nb_route, f, indent=2)

    # 创建模板目录
    if not os.path.exists(template_path):
        os.makedirs(template_path)
        with open(os.path.join(template_path, "base.html"), "w", encoding="utf-8") as f:
            f.write("""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>{% block title %}船舶系统{% endblock %}</title>{% block head_css %}{% endblock %}</head><body style="margin:0; padding:20px; background:#f5f7fa; font-family:Arial,sans-serif;">{% block content %}{% endblock %}</body></html>""")

    app = Flask(__name__, static_folder=static_path, template_folder=template_path)
    app.config.from_mapping(CONFIG)
    return app

app = create_app()

# --------------------------- 路由（核心：未输入起点终点不画航线） --------------------------- 
@app.route("/")
def index():
    return redirect(url_for("login_page"))

@app.route("/get_location/<lng>/<lat>")
def get_location(lng, lat):
    try:
        res = requests.get(f"https://restapi.amap.com/v3/geocode/regeo?location={lng},{lat}&key={app.config['AMAP_API_KEY']}", timeout=10)
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
    # 普通用户登录：自动跳转上海-宁波航线页
    if app.config["VALID_USER"].get(user) == pwd:
        return redirect(url_for("route_map", start_point="上海", end_point="宁波"))
    # 评委账号
    if user == "judge" and pwd == "ship2025":
        return render_template("judge_easter_egg.html", team_info={
            "team_name": "海算云帆",
            "members": ["陈倚薇（队长/计算机组）", "刘迪瑶（计算机组）", "唐辉婷（计算机组）","吴珊（金融组）","周子煜（设计组）"],
            "project_intro": "船舶航线可视化与节油系统：支持航线展示、油耗计算和PDF报告导出功能，帮助优化船舶航行效率。",
            "tech_stack": ["Flask（后端框架）", "高德地图API（地图服务）", "ReportLab（PDF生成）", "HTML/CSS（前端界面）"],
            "development_time": "2025年8月12日-8月25日",
            "achievements": ["完成基础框架搭建", "实现航线可视化", "开发节油计算功能", "支持PDF报告导出", "适配移动端访问"]
        })
    return "用户名或密码错误（正确：admin/123456）", 401

@app.route("/login_success")
def login_success():
    # 兼容旧跳转：直接转上海-宁波航线页
    return redirect(url_for("route_map", start_point="上海", end_point="宁波"))

@app.route("/route_map")
def route_map():
    # 1. 获取参数：未输入则为空字符串
    start = request.args.get("start_point", "").strip()
    end = request.args.get("end_point", "").strip()
    original = request.args.get("original_speed", "").strip()
    optimized = request.args.get("optimized_speed", "").strip()
    user_dist = request.args.get("distance", "").strip()

    # 2. 核心逻辑：仅当起点和终点都输入时才加载航线
    route_points = []
    if start and end:
        route_points = get_preset_route(start, end)
    
    # 3. 航程计算：有航线+无用户输入时自动计算
    default_dist = ""
    if route_points:  # 仅当有航线数据时才计算
        default_dist = calculate_route_distance(route_points)
    final_dist = user_dist if user_dist else str(default_dist) if default_dist else ""

    return render_template(
        "route_map.html",
        route_points=route_points,  # 未输入起点终点时为[]，不画航线
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
        # 仅当有起点终点时加载航线，否则用上海-宁波默认
        route_points = get_preset_route(start, end) if (start and end) else []
        if not route_points and (start == "上海" and end == "宁波"):
            with open(CONFIG["PRESET_ROUTE_PATH"], "r", encoding="utf-8") as f:
                route_points = json.load(f).get("points", [])

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
        logger.error(f"❌ PDF导出失败: {str(e)}")
        return f"PDF导出失败：{str(e)}", 500

if __name__ == "__main__":
    app.run(debug=CONFIG["DEBUG"], port=CONFIG["PORT"], host=CONFIG["HOST"])