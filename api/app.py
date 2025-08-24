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

# --------------------------- 配置区（关键：新增多航线文件映射） --------------------------- 
API_DIR = os.path.abspath(os.path.dirname(__file__))
CONFIG = {
    "SECRET_KEY": "your_secret_key",
    "DEBUG": True,
    "PORT": int(os.environ.get("PORT", 5001)),
    "HOST": "127.0.0.1",
    "AMAP_API_KEY": "1389a7514ce65016496e0ee1349282b7",
    "ROUTE_DATA_PATH": os.path.join(API_DIR, "../static/route_data.json"),
    # 新增：多航线文件映射（key=航线对，value=对应的JSON文件名）
    "PRESET_ROUTE_FILES": {
        ("上海", "宁波"): "shanghai_ningbo_route.json",
        ("宁波", "上海"): "ningbo_shanghai_route.json",  # 反向航线
        ("广州", "深圳"): "guangzhou_shenzhen_route.json",
        ("深圳", "广州"): "shenzhen_guangzhou_route.json",
        ("青岛", "大连"): "qingdao_dalian_route.json",
        ("大连", "青岛"): "dalian_qingdao_route.json",
        ("天津", "青岛"): "tianjin_qingdao_route.json",
        ("青岛", "天津"): "qingdao_tianjin_route.json",
        ("厦门", "香港"): "xiamen_hongkong_route.json",
        ("香港", "厦门"): "hongkong_xiamen_route.json"
    },
    "VALID_USER": {"admin": "123456"}
}

# 中文到英文地点名称映射表
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

# --------------------------- 工具函数（关键：重构多航线加载逻辑） --------------------------- 
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

# 重构：支持多航线匹配（不再硬编码上海-宁波）
def get_preset_route(start_point: str, end_point: str) -> list:
    """根据起点终点匹配对应的航线文件（支持多航线）"""
    if not start_point or not end_point:
        logger.warning("⚠️ 起点或终点为空，无法匹配航线")
        return []
    
    # 标准化输入（去除空格、转小写，支持中文/英文匹配）
    start = start_point.strip().lower()
    end = end_point.strip().lower()
    
    # 遍历所有预设航线，匹配中文或英文名称
    for (s_cn, e_cn), filename in CONFIG["PRESET_ROUTE_FILES"].items():
        # 获取中文对应的英文（如“上海”→“Shanghai”）
        s_en = LOCATION_TRANSLATIONS.get(s_cn, "").lower()
        e_en = LOCATION_TRANSLATIONS.get(e_cn, "").lower()
        
        # 匹配条件：起点为中文/英文，终点为中文/英文
        if (start == s_cn.lower() or start == s_en) and \
           (end == e_cn.lower() or end == e_en):
            logger.debug(f"✅ 匹配到航线：{s_cn}→{e_cn}，加载文件：{filename}")
            return load_route_file(filename)  # 加载对应航线文件
    
    logger.warning(f"⚠️ 未匹配到航线：{start_point}→{end_point}（支持航线：{[f'{k[0]}→{k[1]}' for k in CONFIG['PRESET_ROUTE_FILES'].keys()]}）")
    return []

# 新增：通用航线文件加载函数（支持所有航线文件）
def load_route_file(filename: str) -> list:
    """加载指定名称的航线JSON文件（路径统一）"""
    file_path = os.path.join(API_DIR, f"../static/{filename}")
    if not os.path.exists(file_path):
        logger.error(f"❌ 航线文件不存在: {file_path}（请检查static文件夹）")
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            route_data = json.load(f)
            points = route_data.get("points", [])
            logger.debug(f"✅ 加载航线成功：{filename}，共{len(points)}个坐标点")
            return points
    except json.JSONDecodeError:
        logger.error(f"❌ 航线文件格式错误: {filename}（请确保JSON格式正确）")
        return []
    except Exception as e:
        logger.error(f"❌ 读取航线文件失败: {str(e)}")
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
    if not chinese_name:
        return "Not Specified"
    translated = LOCATION_TRANSLATIONS.get(chinese_name.strip(), None)
    if translated:
        return translated
    for cn, en in LOCATION_TRANSLATIONS.items():
        if cn in chinese_name:
            return en
    return chinese_name

# --------------------------- PDF生成核心函数（保持不变） ---------------------------
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

# --------------------------- Flask 应用初始化（关键：自动生成多航线文件） --------------------------- 
def create_app():
    root_path = os.path.dirname(API_DIR)
    static_path = os.path.join(root_path, "static")
    template_path = os.path.join(root_path, "templates")

    if not os.path.exists(static_path):
        os.makedirs(static_path)
        # 1. 初始化默认航线文件
        with open(CONFIG["ROUTE_DATA_PATH"], "w", encoding="utf-8") as f:
            json.dump({"points": [[121.487899, 31.249162], [121.506302, 31.238938]]}, f, indent=2)
        
        # 2. 自动生成多航线JSON文件（含坐标数据，确保能直接使用）
        # 上海-宁波航线（原有）
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
        with open(os.path.join(static_path, "shanghai_ningbo_route.json"), "w", encoding="utf-8") as f:
            json.dump(sh_nb_route, f, indent=2)
        
        # 宁波-上海航线（反向）
        nb_sh_route = {"points": sh_nb_route["points"][::-1]}
        with open(os.path.join(static_path, "ningbo_shanghai_route.json"), "w", encoding="utf-8") as f:
            json.dump(nb_sh_route, f, indent=2)
        
        # 广州-深圳航线（示例坐标）
        gz_sz_route = {
            "points": [
                [113.271429, 23.120049], [113.321429, 23.080049], [113.381429, 23.030049],
                [113.451429, 22.980049], [113.521429, 22.930049], [113.581429, 22.880049],
                [113.651429, 22.830049], [113.721429, 22.780049]  # 深圳港附近
            ]
        }
        with open(os.path.join(static_path, "guangzhou_shenzhen_route.json"), "w", encoding="utf-8") as f:
            json.dump(gz_sz_route, f, indent=2)
        
        # 深圳-广州航线（反向）
        sz_gz_route = {"points": gz_sz_route["points"][::-1]}
        with open(os.path.join(static_path, "shenzhen_guangzhou_route.json"), "w", encoding="utf-8") as f:
            json.dump(sz_gz_route, f, indent=2)
        
        # 青岛-大连航线（示例坐标）
        qd_dl_route = {
            "points": [
                [120.369293, 36.067072], [120.569293, 36.167072], [120.869293, 36.367072],
                [121.169293, 36.567072], [121.469293, 36.767072], [121.769293, 36.967072],
                [122.069293, 37.167072], [122.369293, 37.367072], [122.669293, 37.567072]  # 大连港附近
            ]
        }
        with open(os.path.join(static_path, "qingdao_dalian_route.json"), "w", encoding="utf-8") as f:
            json.dump(qd_dl_route, f, indent=2)
        
        # 大连-青岛航线（反向）
        dl_qd_route = {"points": qd_dl_route["points"][::-1]}
        with open(os.path.join(static_path, "dalian_qingdao_route.json"), "w", encoding="utf-8") as f:
            json.dump(dl_qd_route, f, indent=2)
        
        # 其他航线（简化示例，可根据实际需求补充精确坐标）
        # 天津-青岛
        tj_qd_route = {"points": [[117.200983, 39.084158], [118.200983, 38.884158], [119.200983, 38.684158], [120.369293, 36.067072]]}
        with open(os.path.join(static_path, "tianjin_qingdao_route.json"), "w", encoding="utf-8") as f:
            json.dump(tj_qd_route, f, indent=2)
        # 青岛-天津（反向）
        qd_tj_route = {"points": tj_qd_route["points"][::-1]}
        with open(os.path.join(static_path, "qingdao_tianjin_route.json"), "w", encoding="utf-8") as f:
            json.dump(qd_tj_route, f, indent=2)
        # 厦门-香港
        xm_hk_route = {"points": [[118.062342, 24.478636], [118.562342, 24.278636], [119.062342, 24.078636], [114.157696, 22.284621]]}
        with open(os.path.join(static_path, "xiamen_hongkong_route.json"), "w", encoding="utf-8") as f:
            json.dump(xm_hk_route, f, indent=2)
        # 香港-厦门（反向）
        hk_xm_route = {"points": xm_hk_route["points"][::-1]}
        with open(os.path.join(static_path, "hongkong_xiamen_route.json"), "w", encoding="utf-8") as f:
            json.dump(hk_xm_route, f, indent=2)

    if not os.path.exists(template_path):
        os.makedirs(template_path)
        with open(os.path.join(template_path, "base.html"), "w", encoding="utf-8") as f:
            f.write("""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>{% block title %}船舶系统{% endblock %}</title>{% block head_css %}{% endblock %}</head><body style="margin:0; padding:20px; background:#f5f7fa; font-family:Arial,sans-serif;">{% block content %}{% endblock %}</body></html>""")

    app = Flask(__name__, static_folder=static_path, template_folder=template_path)
    app.config.from_mapping(CONFIG)
    return app

# --------------------------- 路由定义（关键：修复航线数据传递格式） --------------------------- 
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
    user_dist = request.args.get("distance", "").strip()

    # 1. 获取匹配的航线（支持多航线）
    route_points = get_preset_route(start, end) if (start and end) else read_route_data()
    # 2. 计算航程（坐标不足时留空）
    default_dist = calculate_route_distance(route_points) if len(route_points) >=2 else ""
    final_dist = user_dist if user_dist else (str(default_dist) if default_dist != "" else "")

    # 关键修复：传递JSON格式数据给前端（避免地图解析失败）
    return render_template(
        "route_map.html",
        route_points=json.dumps(route_points),  # 修复：转为JSON字符串
        start_point=start,
        end_point=end,
        original_speed=original,
        optimized_speed=optimized,
        distance=final_dist,
        amap_key=app.config["AMAP_API_KEY"]  # 传递高德key给前端
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
        # 支持多航线PDF导出
        route_points = get_preset_route(start, end)
        if not route_points:
            # 无匹配航线时，默认用上海-宁波
            route_points = load_route_file("shanghai_ningbo_route.json")
            start = start or "上海"
            end = end or "宁波"

        fuel_data = {
            "start": start or "未知起点",
            "end": end or "未知终点",
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