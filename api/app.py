import os
import json
import requests
import logging
import math
from io import BytesIO
from datetime import datetime
from flask import Flask, request, render_template, redirect, url_for, make_response, send_file, session

# PDF生成相关库
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.fonts import addMapping
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.units import cm

# --------------------------- 配置区 --------------------------- 
API_DIR = os.path.abspath(os.path.dirname(__file__))
CONFIG = {
    "SECRET_KEY": "your_secret_key",  # 用于session存储
    "DEBUG": True,
    "PORT": int(os.environ.get("PORT", 5001)),
    "HOST": "127.0.0.1",
    "AMAP_API_KEY": "1389a7514ce65016496e0ee1349282b7",
    "ROUTE_DATA_PATH": os.path.join(API_DIR, "../static/route_data.json"),
    # 10条航线的文件映射配置
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

# --------------------------- 工具函数 --------------------------- 
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
    """根据起点终点匹配对应的航线文件"""
    if not start_point or not end_point:
        return []
        
    # 标准化输入（去除空格并转为小写）
    start = start_point.strip().lower()
    end = end_point.strip().lower()
    
    # 尝试直接匹配原始名称
    for (s, e), filename in CONFIG["PRESET_ROUTE_FILES"].items():
        if (start == s.lower() or start == LOCATION_TRANSLATIONS.get(s, "").lower()) and \
           (end == e.lower() or end == LOCATION_TRANSLATIONS.get(e, "").lower()):
            return load_route_file(filename)
    
    # 尝试反向匹配（例如用户输入拼音或英文）
    for (s, e), filename in CONFIG["PRESET_ROUTE_FILES"].items():
        if (start in s.lower() or start in LOCATION_TRANSLATIONS.get(s, "").lower()) and \
           (end in e.lower() or end in LOCATION_TRANSLATIONS.get(e, "").lower()):
            return load_route_file(filename)
    
    return []

def load_route_file(filename: str) -> list:
    """加载指定航线文件"""
    file_path = os.path.join(API_DIR, f"../static/{filename}")
    if not os.path.exists(file_path):
        logger.warning(f"⚠️  航线文件不存在: {file_path}")
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f).get("points", [])
    except Exception as e:
        logger.error(f"❌ 读取航线文件失败 {filename}: {str(e)}")
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

# 优化后的地点翻译函数（含调试日志）
def translate_location(chinese_name):
    """优化的中文地点到英文翻译函数，添加调试日志"""
    # 记录原始输入以便调试
    logger.debug(f"翻译地点: {chinese_name}")
    
    if not chinese_name:
        logger.warning("尝试翻译空的地点名称")
        return "Not Specified"
    
    # 预处理：去除空格、常见后缀（港、市），统一处理
    cleaned_name = chinese_name.strip().replace(" ", "").replace("港", "").replace("市", "")
    logger.debug(f"清理后的地点名称: {cleaned_name}")
    
    # 1. 尝试精确匹配
    translated = LOCATION_TRANSLATIONS.get(cleaned_name, None)
    if translated:
        logger.debug(f"精确匹配成功: {translated}")
        return translated
    
    # 2. 尝试反向包含匹配（如"上海市"包含"上海"）
    for cn, en in LOCATION_TRANSLATIONS.items():
        if cleaned_name in cn or cn in cleaned_name:
            logger.debug(f"反向匹配成功: {en}")
            return en
    
    # 3. 处理拼音输入（支持全拼匹配）
    pinyin_mapping = {
        "shanghai": "Shanghai", "beijing": "Beijing", "guangzhou": "Guangzhou",
        "shenzhen": "Shenzhen", "ningbo": "Ningbo", "tianjin": "Tianjin",
        "qingdao": "Qingdao", "dalian": "Dalian", "xiamen": "Xiamen",
        "hongkong": "Hong Kong", "xianggang": "Hong Kong", "macau": "Macau",
        "aomen": "Macau", "chongqing": "Chongqing", "nanjing": "Nanjing",
        "hangzhou": "Hangzhou", "suzhou": "Suzhou", "wuhan": "Wuhan"
    }
    
    # 转换为小写并尝试拼音匹配
    lower_name = cleaned_name.lower()
    if lower_name in pinyin_mapping:
        logger.debug(f"拼音匹配成功: {pinyin_mapping[lower_name]}")
        return pinyin_mapping[lower_name]
    
    # 4. 所有匹配失败时，记录警告并返回处理后的名称
    logger.warning(f"无法翻译地点: {chinese_name}")
    return chinese_name.title()

# --------------------------- PDF生成核心函数 ---------------------------
def generate_route_report(route_points, fuel_data):
    buffer = BytesIO()
    
    # 1. 严格控制A4纵向布局，边距最小化
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,  # 保持纵向A4
        rightMargin=0.8*cm,  # 边距压缩至0.8cm
        leftMargin=0.8*cm,
        topMargin=0.8*cm,
        bottomMargin=0.8*cm
    )

    # 2. PDF使用英文默认字体
    font_name = 'Helvetica'  # 英文标准字体

    # 3. 紧凑样式配置
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
    # 标题和时间（英文）
    elements.append(Paragraph("Ship Route Visualization System Report", styles['Title_EN']))
    elements.append(Paragraph(f"Generation Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal_EN']))
    elements.append(Spacer(1, 6))

    # 4. 航线坐标表格
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

    # 5. 节油量表格（使用翻译后的地点名称）
    elements.append(Paragraph("2. Fuel Saving Calculation Results", styles['Heading2_EN']))
    if fuel_data:
        # 翻译起点和终点
        translated_start = translate_location(fuel_data.get('start'))
        translated_end = translate_location(fuel_data.get('end'))
        
        fuel_table_data = [
            ["Parameter", "Value"],
            ["Start Point", translated_start],  # 使用翻译后的值
            ["End Point", translated_end],      # 使用翻译后的值
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

    # 构建PDF
    doc.build(elements)
    buffer.seek(0)
    return buffer

# --------------------------- Flask 应用初始化 --------------------------- 
def create_app():
    root_path = os.path.dirname(API_DIR)
    static_path = os.path.join(root_path, "static")
    template_path = os.path.join(root_path, "templates")

    if not os.path.exists(static_path):
        os.makedirs(static_path)
        # 初始化默认航线文件
        with open(CONFIG["ROUTE_DATA_PATH"], "w", encoding="utf-8") as f:
            json.dump({"points": [[121.487899, 31.249162], [121.506302, 31.238938]]}, f, indent=2)

        # 初始化10条预设航线的空文件
        default_route = {"points": []}
        for (_, _), filename in CONFIG["PRESET_ROUTE_FILES"].items():
            file_path = os.path.join(static_path, filename)
            if not os.path.exists(file_path):
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(default_route, f, indent=2)

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
        # 登录成功时初始化session
        session['username'] = user
        return redirect(url_for("login_success", username=user))
    if user == "judge" and pwd == "ship2025":
        session['username'] = user
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

    # 保存起点终点到session，作为备份
    if start and end:
        session['last_start'] = start
        session['last_end'] = end

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
        
        # 保存起点终点到session，作为备份
        if start and end:
            session['last_start'] = start
            session['last_end'] = end
            
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
        # 1. 获取起点终点参数
        start = request.args.get("start_point", "").strip()
        end = request.args.get("end_point", "").strip()
        
        # 2. 参数验证与备份获取
        if not start or not end:
            # 从session获取最近一次的起点终点
            start = session.get("last_start", start)
            end = session.get("last_end", end)
            logger.warning(f"参数不完整，尝试从session获取: start={start}, end={end}")
        
        # 3. 再次检查，确保有可用值
        if not start or not end:
            error_msg = "无法获取起点和终点信息，请先设置航线再导出报告"
            logger.error(error_msg)
            return error_msg, 400
        
        # 4. 记录接收到的起点终点（调试日志）
        logger.debug(f"导出PDF - 起点: {start}, 终点: {end}")
        
        route_points = get_preset_route(start, end)
        if not route_points:
            route_points = read_route_data()
            logger.debug("使用默认航线数据")

        fuel_data = {
            "start": start,
            "end": end,
            "original": request.args.get("original_speed", "未填写"),
            "optimized": request.args.get("optimized_speed", "未填写"),
            "distance": request.args.get("distance", str(calculate_route_distance(route_points))),
            "saving": request.args.get("saving", "未计算")
        }
        
        # 5. 记录传入PDF的数据（调试日志）
        logger.debug(f"传入PDF的燃料数据: {fuel_data}")

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

# --------------------------- 应用启动 --------------------------- 
if __name__ == "__main__":
    app.run(debug=CONFIG["DEBUG"], port=CONFIG["PORT"], host=CONFIG["HOST"])
