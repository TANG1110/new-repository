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
from reportlab.lib.fonts import addMapping
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.units import cm

# --------------------------- 配置区（关键：调整路径计算逻辑） --------------------------- 
# API_DIR = 当前app.py所在的API文件夹路径
API_DIR = os.path.abspath(os.path.dirname(__file__))
# PROJECT_ROOT = 项目根目录（API文件夹的上一级目录）
PROJECT_ROOT = os.path.abspath(os.path.join(API_DIR, ".."))

# 所有预设航线的文件路径（基于项目根目录定位static文件夹）
PRESET_ROUTE_FILES = {
    "上海-宁波": os.path.join(PROJECT_ROOT, "static/shanghai_ningbo.json"),
    "宁波-上海": os.path.join(PROJECT_ROOT, "static/ningbo_shanghai.json"),
    "广州-深圳": os.path.join(PROJECT_ROOT, "static/guangzhou_shenzhen.json"),
    "深圳-广州": os.path.join(PROJECT_ROOT, "static/shenzhen_guangzhou.json"),
    "青岛-大连": os.path.join(PROJECT_ROOT, "static/qingdao_dalian.json"),
    "大连-青岛": os.path.join(PROJECT_ROOT, "static/dalian_qingdao.json"),
    "天津-青岛": os.path.join(PROJECT_ROOT, "static/tianjin_qingdao.json"),
    "青岛-天津": os.path.join(PROJECT_ROOT, "static/qingdao_tianjin.json"),
    "厦门-香港": os.path.join(PROJECT_ROOT, "static/xiamen_hongkong.json"),
    "香港-厦门": os.path.join(PROJECT_ROOT, "static/hongkong_xiamen.json")
}

CONFIG = {
    "SECRET_KEY": "your_secret_key",
    "DEBUG": True,
    "PORT": int(os.environ.get("PORT", 5001)),
    "HOST": "127.0.0.1",
    "AMAP_API_KEY": "1389a7514ce65016496e0ee1349282b7",
    "ROUTE_DATA_PATH": os.path.join(PROJECT_ROOT, "static/route_data.json"),  # 基于项目根目录
    "PRESET_ROUTE_PATH": os.path.join(PROJECT_ROOT, "static/shanghai_ningbo.json"),  # 基于项目根目录
    "VALID_USER": {"admin": "123456"}
}

# 中文到英文地点名称映射表（不变）
LOCATION_TRANSLATIONS = {
    "上海": "Shanghai",
    "北京": "Beijing",
    "广州": "Guangzhou",
    "深圳": "Shenzhen",
    "宁波": "Ningbo",
    "天津": "Tianjin",
    "青岛": "Qingdao",
    "大连": "Dalian",
    "厦门": "Xiamen",
    "香港": "Hong Kong",
    "澳门": "Macau",
    "重庆": "Chongqing",
    "南京": "Nanjing",
    "杭州": "Hangzhou",
    "苏州": "Suzhou",
    "武汉": "Wuhan"
}

# 日志配置（不变）
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# --------------------------- 工具函数（路径引用已适配项目根目录） --------------------------- 
def read_route_data():
    file_path = CONFIG["ROUTE_DATA_PATH"]
    if not os.path.exists(file_path):
        logger.warning(f"⚠️  默认航线文件不存在: {file_path}")
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f).get("points", [])
    except Exception as e:
        logger.error(f"❌ 读取默认航线失败: {str(e)}")
        return []

def get_preset_route(start_point: str, end_point: str) -> list:
    """根据起点终点匹配预设航线（支持中英文、正向反向）"""
    start = start_point.strip().lower()
    end = end_point.strip().lower()
    
    # 地点别名映射（兼容简称、英文）
    location_aliases = {
        "上海": ["上海", "shanghai", "沪"],
        "宁波": ["宁波", "ningbo", "甬"],
        "广州": ["广州", "guangzhou", "穗"],
        "深圳": ["深圳", "shenzhen"],
        "青岛": ["青岛", "qingdao"],
        "大连": ["大连", "dalian"],
        "天津": ["天津", "tianjin", "津"],
        "厦门": ["厦门", "xiamen", "鹭"],
        "香港": ["香港", "hong kong", "港"]
    }
    
    # 匹配标准地点名称
    matched_start = None
    matched_end = None
    for std_name, aliases in location_aliases.items():
        if start in aliases and not matched_start:
            matched_start = std_name
        if end in aliases and not matched_end:
            matched_end = std_name
    if not matched_start or not matched_end:
        logger.warning(f"⚠️ 未匹配到有效起点/终点：{start_point}→{end_point}")
        return []
    
    # 匹配航线文件（路径已基于项目根目录）
    route_key = f"{matched_start}-{matched_end}"
    if route_key not in PRESET_ROUTE_FILES:
        logger.warning(f"⚠️ 无预设航线：{route_key}")
        return []
    
    try:
        file_path = PRESET_ROUTE_FILES[route_key]
        if not os.path.exists(file_path):
            logger.error(f"❌ 航线文件不存在：{file_path}")
            return []
        with open(file_path, "r", encoding="utf-8") as f:
            route_points = json.load(f).get("points", [])
            logger.info(f"✅ 成功加载航线：{route_key}（{len(route_points)}个坐标点）")
            return route_points
    except Exception as e:
        logger.error(f"❌ 读取航线{route_key}失败：{str(e)}")
        return []

def calculate_route_distance(points: list) -> float:
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
    """将中文地点转换为英文（不变）"""
    if not chinese_name:
        return "Not Specified"
    translated = LOCATION_TRANSLATIONS.get(chinese_name.strip(), None)
    if translated:
        return translated
    for cn, en in LOCATION_TRANSLATIONS.items():
        if cn in chinese_name:
            return en
    return chinese_name

# --------------------------- PDF生成核心函数（不变） ---------------------------
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

    elements.append(Paragraph("1. Route Coordinate Information", styles['Heading2_EN']))
    if route_points:
        table_data = [["No.", "Longitude", "Latitude"]]
        for idx, (lng, lat) in enumerate(route_points, 1):
            table_data.append([str(idx), f"{lng:.6f}", f"{lat:.6f}"])
        table_width = 21*cm - 1.6*cm
        col_widths = [table_width*0.15, table_width*0.425, table_width*0.425]
        max_rows_per_page = len(table_data)
        row_height = (24*cm) / max_rows_per_page
        route_table = Table(table_data, colWidths=col_widths, rowHeights=row_height)
        route_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), font_name),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('LEADING', (0, 0), (-1, -1), 8)
        ]))
        elements.append(route_table)
    else:
        elements.append(Paragraph("⚠️ No route coordinate data obtained", styles['Normal_EN']))
    elements.append(Spacer(1, 6))

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

# --------------------------- Flask 应用初始化（关键：指定templates和static路径） --------------------------- 
def create_app():
    # 基于项目根目录定位templates和static文件夹
    static_path = os.path.join(PROJECT_ROOT, "static")
    template_path = os.path.join(PROJECT_ROOT, "templates")

    # 确保static文件夹存在（路径基于项目根目录）
    if not os.path.exists(static_path):
        os.makedirs(static_path)
        # 1. 生成默认航线（route_data.json）
        with open(CONFIG["ROUTE_DATA_PATH"], "w", encoding="utf-8") as f:
            json.dump({"points": [[121.487899, 31.249162], [121.506302, 31.238938]]}, f, indent=2)
        
        # 2. 生成上海-宁波航线（正向+反向）
        sh_nb_route = {
            "points": [
                [121.582812, 31.372057], [121.642376, 31.372274], [121.719159, 31.329024],
                [121.808468, 31.277377], [121.862846, 31.266428], [122.037651, 31.251066],
                [122.101726, 31.06938], [122.201797, 30.629212], [122.11298, 30.442215],
                [121.89094, 30.425198], [121.819322, 30.269414], [121.69957, 30.164341],
                [121.854434, 29.957196], [121.854434, 29.957196], [121.910951, 29.954561],
                [121.952784, 29.977126], [122.02619, 29.925834], [122.069602, 29.911468],
                [122.168266, 29.929254], [122.176948, 29.897783], [122.150901, 29.866987],
                [122.02136, 29.822932]
            ]
        }
        with open(PRESET_ROUTE_FILES["上海-宁波"], "w", encoding="utf-8") as f:
            json.dump(sh_nb_route, f, indent=2)
        with open(PRESET_ROUTE_FILES["宁波-上海"], "w", encoding="utf-8") as f:
            json.dump({"points": sh_nb_route["points"][::-1]}, f, indent=2)
        
        # 3. 生成广州-深圳航线（正向+反向）
        gz_sz_route = {
            "points": [
                [113.285128, 23.111923], [113.284727, 23.110575], [113.297272, 23.106393],
                [113.308973, 23.106259], [113.320968, 23.10909], [113.338126, 23.109922],
                [113.373377, 23.107627], [113.391791, 23.105829], [113.402317, 23.098721],
                [113.422089, 23.088875], [113.452281, 23.08773], [113.478383, 23.083281],
                [113.491754, 23.077131], [113.495856, 23.067413], [113.494287, 23.062199],
                [113.511608, 23.036716], [113.567685, 22.886009], [113.569526, 22.853788],
                [113.601735, 22.830041], [113.620141, 22.79526], [113.766466, 22.646709],
                [113.813923, 22.600991]
            ]
        }
        with open(PRESET_ROUTE_FILES["广州-深圳"], "w", encoding="utf-8") as f:
            json.dump(gz_sz_route, f, indent=2)
        with open(PRESET_ROUTE_FILES["深圳-广州"], "w", encoding="utf-8") as f:
            json.dump({"points": gz_sz_route["points"][::-1]}, f, indent=2)
        
        # 4. 生成青岛-大连航线（正向+反向）
        qd_dl_route = {
            "points": [
                [120.30834, 36.082055], [120.263841, 36.070355], [120.26607, 36.034583],
                [121.114344, 36.001208], [123.309681, 35.991833], [123.268417, 38.207562],
                [121.656502, 38.938648]
            ]
        }
        with open(PRESET_ROUTE_FILES["青岛-大连"], "w", encoding="utf-8") as f:
            json.dump(qd_dl_route, f, indent=2)
        with open(PRESET_ROUTE_FILES["大连-青岛"], "w", encoding="utf-8") as f:
            json.dump({"points": qd_dl_route["points"][::-1]}, f, indent=2)
        
        # 5. 生成天津-青岛航线（正向+反向）
        tj_qd_route = {
            "points": [
                [117.855978, 38.952005], [117.889123, 38.994118], [120.655656, 38.357795],
                [121.147563, 38.60534], [123.268417, 38.207562], [123.309681, 35.991833],
                [121.114344, 36.001208], [120.26607, 36.034583], [120.263841, 36.070355],
                [120.30834, 36.082055]
            ]
        }
        with open(PRESET_ROUTE_FILES["天津-青岛"], "w", encoding="utf-8") as f:
            json.dump(tj_qd_route, f, indent=2)
        with open(PRESET_ROUTE_FILES["青岛-天津"], "w", encoding="utf-8") as f:
            json.dump({"points": tj_qd_route["points"][::-1]}, f, indent=2)
        
        # 6. 生成厦门-香港航线（正向+反向）
        xm_hk_route = {
            "points": [
                [118.072762, 24.454891], [118.071395, 24.452599], [118.071395, 24.452599],
                [118.086071, 24.424532], [118.297639, 24.323637], [118.142568, 24.363377],
                [118.297639, 24.323637], [118.25965, 23.61136], [118.062769, 22.125619],
                [114.310954, 22.21122], [114.277649, 22.240508], [114.2584, 22.274573],
                [114.239927, 22.284051], [114.210388, 22.300213], [114.174173, 22.285659],
                [114.162101, 22.293106], [114.169718, 22.29607]
            ]
        }
        with open(PRESET_ROUTE_FILES["厦门-香港"], "w", encoding="utf-8") as f:
            json.dump(xm_hk_route, f, indent=2)
        with open(PRESET_ROUTE_FILES["香港-厦门"], "w", encoding="utf-8") as f:
            json.dump({"points": xm_hk_route["points"][::-1]}, f, indent=2)

    # 确保templates文件夹存在（路径基于项目根目录）
    if not os.path.exists(template_path):
        os.makedirs(template_path)
        with open(os.path.join(template_path, "base.html"), "w", encoding="utf-8") as f:
            f.write("""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>{% block title %}船舶系统{% endblock %}</title>{% block head_css %}{% endblock %}</head><body style="margin:0; padding:20px; background:#f5f7fa; font-family:Arial,sans-serif;">{% block content %}{% endblock %}</body></html>""")

    # 初始化Flask应用：明确指定static和templates文件夹路径（关键）
    app = Flask(
        __name__,
        static_folder=static_path,    # 基于项目根目录的static
        template_folder=template_path # 基于项目根目录的templates
    )
    app.config.from_mapping(CONFIG)
    return app

# --------------------------- 路由定义（完全不变） --------------------------- 
app = create_app()

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
    if app.config["VALID_USER"].get(user) == pwd:
        return redirect(url_for("login_success", username=user))
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
    return render_template("login_success.html", username=request.args.get("username", "用户"))

@app.route("/route_map")
def route_map():
    start = request.args.get("start_point", "").strip()
    end = request.args.get("end_point", "").strip()
    original = request.args.get("original_speed", "")
    optimized = request.args.get("optimized_speed", "")
    user_dist = request.args.get("distance", "")

    route_points = get_preset_route(start, end) if (start and end) else read_route_data()
    default_dist = calculate_route_distance(route_points)
    final_dist = user_dist if user_dist else str(default_dist)

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
            with open(CONFIG["PRESET_ROUTE_PATH"], "r", encoding="utf-8") as f:
                route_points = json.load(f).get("points", [])

        fuel_data = {
            "start": start or "上海",
            "end": end or "宁波",
            "original": request.args.get("original_speed", "未填写"),
            "optimized": request.args.get("optimized_speed", "未填写"),
            "distance": request.args.get("distance", str(calculate_route_distance(route_points))),
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