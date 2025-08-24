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

# --------------------------- 配置区（新增10条航线文件映射） --------------------------- 
API_DIR = os.path.abspath(os.path.dirname(__file__))
CONFIG = {
    "SECRET_KEY": "your_secret_key",
    "DEBUG": True,
    "PORT": int(os.environ.get("PORT", 5001)),
    "HOST": "127.0.0.1",
    "AMAP_API_KEY": "1389a7514ce65016496e0ee1349282b7",
    "ROUTE_DATA_PATH": os.path.join(API_DIR, "../static/route_data.json"),
    # 新增：10条预设航线的「起点-终点-文件名」映射表
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

# 中文到英文地点名称映射表（保持不变）
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

# 日志配置（保持不变）
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# --------------------------- 工具函数（新增多航线加载逻辑） --------------------------- 
def read_route_data():
    # 保持原有逻辑：读取默认航线（无匹配时备用）
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

# 新增：通用航线文件加载函数（复用逻辑，避免代码冗余）
def load_route_file(filename: str) -> list:
    """根据文件名加载对应的航线JSON文件，返回经纬度点列表"""
    file_path = os.path.join(API_DIR, f"../static/{filename}")  # 航线文件统一放在static目录
    if not os.path.exists(file_path):
        logger.warning(f"⚠️  航线文件不存在: {file_path}")
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f).get("points", [])  # 约定JSON格式为{"points": [[lng1, lat1], [lng2, lat2], ...]}
    except Exception as e:
        logger.error(f"❌ 读取航线文件[{filename}]失败: {str(e)}")
        return []

# 修改：支持10条航线的匹配逻辑（兼容中文/英文/拼音输入）
def get_preset_route(start_point: str, end_point: str) -> list:
    """
    根据用户输入的起点和终点，匹配对应的预设航线
    支持输入格式：中文（如“上海”）、英文（如“Shanghai”）、小写拼音（如“shanghai”）
    """
    if not start_point or not end_point:
        logger.warning("⚠️  起点或终点为空，无法匹配航线")
        return []
    
    # 标准化输入：去除空格、转为小写（统一匹配规则）
    start = start_point.strip().lower()
    end = end_point.strip().lower()
    
    # 遍历10条预设航线，尝试精确匹配（中文/英文）
    for (preset_start, preset_end), filename in CONFIG["PRESET_ROUTE_FILES"].items():
        # 预设起点的匹配维度：中文小写、英文小写
        preset_start_cn = preset_start.lower()
        preset_start_en = LOCATION_TRANSLATIONS.get(preset_start, "").lower()
        # 预设终点的匹配维度：中文小写、英文小写
        preset_end_cn = preset_end.lower()
        preset_end_en = LOCATION_TRANSLATIONS.get(preset_end, "").lower()
        
        # 满足“起点匹配且终点匹配”则返回对应航线
        if (start == preset_start_cn or start == preset_start_en) and \
           (end == preset_end_cn or end == preset_end_en):
            logger.info(f"✅ 匹配到航线：{preset_start} → {preset_end}（文件：{filename}）")
            return load_route_file(filename)
    
    # 若未精确匹配，尝试模糊匹配（如输入“上海港”匹配“上海”）
    for (preset_start, preset_end), filename in CONFIG["PRESET_ROUTE_FILES"].items():
        preset_start_cn = preset_start.lower()
        preset_start_en = LOCATION_TRANSLATIONS.get(preset_start, "").lower()
        preset_end_cn = preset_end.lower()
        preset_end_en = LOCATION_TRANSLATIONS.get(preset_end, "").lower()
        
        if (preset_start_cn in start or preset_start_en in start) and \
           (preset_end_cn in end or preset_end_en in end):
            logger.info(f"✅ 模糊匹配到航线：{preset_start} → {preset_end}（文件：{filename}）")
            return load_route_file(filename)
    
    logger.warning(f"⚠️  未找到匹配航线：{start_point} → {end_point}")
    return []

# 其他工具函数（保持原有逻辑不变）
def calculate_route_distance(points: list) -> float:
    """计算航线总距离（单位：海里，1海里=1.852公里）"""
    total_km = 0.0
    for i in range(len(points)-1):
        lng1, lat1 = points[i]
        lng2, lat2 = points[i+1]
        # 经纬度转弧度
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lng = math.radians(lng2 - lng1)
        # 哈弗辛公式（计算两点间球面距离）
        a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lng/2)**2
        total_km += 6371 * (2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))  # 地球半径6371公里
    return round(total_km / 1.852, 2)  # 转为海里并保留2位小数

def translate_location(chinese_name):
    """将中文地点转换为英文（用于PDF报告）"""
    if not chinese_name:
        return "Not Specified"
    
    # 精确匹配映射表
    translated = LOCATION_TRANSLATIONS.get(chinese_name.strip(), None)
    if translated:
        return translated
    
    # 模糊匹配（如“上海港”匹配“上海”）
    for cn, en in LOCATION_TRANSLATIONS.items():
        if cn in chinese_name:
            return en
    
    # 无匹配时返回原名称（兼容英文/拼音输入）
    return chinese_name

# --------------------------- PDF生成核心函数（保持不变） ---------------------------
def generate_route_report(route_points, fuel_data):
    buffer = BytesIO()
    
    # 1. A4纵向布局配置（边距最小化，提升内容密度）
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=0.8*cm,
        leftMargin=0.8*cm,
        topMargin=0.8*cm,
        bottomMargin=0.8*cm
    )

    # 2. 英文默认字体配置
    font_name = 'Helvetica'  # 英文标准无衬线字体，适配PDF显示

    # 3. 紧凑样式定义（减少冗余空格，适配多航线数据）
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name='Title_EN',
        parent=styles['Title'],
        fontName=font_name,
        fontSize=18,
        alignment=1,  # 居中对齐
        spaceAfter=8  # 标题后间距
    ))
    styles.add(ParagraphStyle(
        name='Normal_EN',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=10,
        leading=12  # 行高
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
    # 报告标题与生成时间
    elements.append(Paragraph("Ship Route Visualization System Report", styles['Title_EN']))
    elements.append(Paragraph(f"Generation Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal_EN']))
    elements.append(Spacer(1, 6))

    # 4. 航线坐标表格（适配任意航线的经纬度点数量）
    elements.append(Paragraph("1. Route Coordinate Information", styles['Heading2_EN']))
    if route_points:
        table_data = [["No.", "Longitude", "Latitude"]]  # 表头
        for idx, (lng, lat) in enumerate(route_points, 1):
            table_data.append([str(idx), f"{lng:.6f}", f"{lat:.6f}"])  # 保留6位小数，确保精度
        
        # 表格宽度自适应A4页面（减去左右边距）
        table_width = 21*cm - 1.6*cm  # A4宽度21cm，左右边距各0.8cm
        col_widths = [table_width*0.15, table_width*0.425, table_width*0.425]  # 列宽比例15%:42.5%:42.5%
        
        # 行高自适应（根据数据量动态调整，避免分页异常）
        max_rows_per_page = len(table_data)
        row_height = (24*cm) / max_rows_per_page  # A4高度24cm，减去上下边距
        
        # 表格样式配置（深色表头、网格线、居中对齐）
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

    # 5. 节油量表格（使用翻译后的英文地点名称）
    elements.append(Paragraph("2. Fuel Saving Calculation Results", styles['Heading2_EN']))
    if fuel_data:
        # 翻译起点和终点（兼容中文输入）
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
        
        # 节油量表格宽度与航线表格一致，确保页面统一
        fuel_table = Table(fuel_table_data, colWidths=[table_width*0.3, table_width*0.7])
        fuel_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), font_name),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkgreen),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),  # 参数列左对齐
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),  # 值列居中对齐
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(fuel_table)
    else:
        elements.append(Paragraph("⚠️ No fuel saving calculation data obtained", styles['Normal_EN']))

    # 构建PDF并返回缓冲区
    doc.build(elements)
    buffer.seek(0)  # 重置缓冲区指针，确保读取完整
    return buffer

# --------------------------- Flask 应用初始化（新增多航线文件初始化） --------------------------- 
def create_app():
    root_path = os.path.dirname(API_DIR)
    static_path = os.path.join(root_path, "static")
    template_path = os.path.join(root_path, "templates")

    # 1. 确保static目录存在（用于存放航线文件和默认数据）
    if not os.path.exists(static_path):
        os.makedirs(static_path)
        # 初始化默认航线文件（无匹配时备用）
        with open(CONFIG["ROUTE_DATA_PATH"], "w", encoding="utf-8") as f:
            json.dump({"points": [[121.487899, 31.249162], [121.506302, 31.238938]]}, f, indent=2)
        
        # 初始化10条预设航线的空文件（避免首次运行时文件不存在报错）
        default_route = {"points": []}  # 空航线模板（实际使用时需填充真实经纬度）
        for (_, _), filename in CONFIG["PRESET_ROUTE_FILES"].values():
            file_path = os.path.join(static_path, filename)
            if not os.path.exists(file_path):
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(default_route, f, indent=2)
                logger.info(f"✅ 初始化航线文件：{filename}")

    # 2. 确保templates目录存在（用于存放HTML模板）
    if not os.path.exists(template_path):
        os.makedirs(template_path)
        # 初始化基础模板文件
        with open(os.path.join(template_path, "base.html"), "w", encoding="utf-8") as f:
            f.write("""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>{% block title %}船舶系统{% endblock %}</title>{% block head_css %}{% endblock %}</head><body style="margin:0; padding:20px; background:#f5f7fa; font-family:Arial,sans-serif;">{% block content %}{% endblock %}</body></html>""")

    # 3. 初始化Flask应用
    app = Flask(__name__, static_folder=static_path, template_folder=template_path)
    app.config.from_mapping(CONFIG)
    return app

# --------------------------- 路由定义（保持原有逻辑，自动适配多航线） --------------------------- 
app = create_app()

@app.route("/")
def index():
    return redirect(url_for("login_page"))

@app.route("/get_location/<lng>/<lat>")
def get_location(lng, lat):
    """调用高德地图API，根据经纬度获取地址信息（保持不变）"""
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
    """登录逻辑（保持不变，含评委彩蛋账号）"""
    if request.method == "GET":
        return render_template("login.html")
    user = request.form.get("username", "").strip()
    pwd = request.form.get("password", "").strip()
    if not user or not pwd:
        return "用户名和密码不能为空", 400
    # 普通用户登录（admin/123456）
    if app.config["VALID_USER"].get(user) == pwd:
        return redirect(url_for("login_success", username=user))
    # 评委彩蛋账号（judge/ship2025）
    if user == "judge" and pwd == "ship2025":
        return render_template("judge_easter_egg.html", team_info={
            "team_name": "海算云帆",
            "members": ["陈倚薇（队长/计算机组）", "刘迪瑶（计算机组）", "唐辉婷（计算机组）","吴珊（金融组）","周子煜（设计组）"],
            "project_intro": "船舶航线可视化与节油系统：支持10条预设航线展示、油耗计算和PDF报告导出功能，帮助优化船舶航行效率。",
            "tech_stack": ["Flask（后端框架）", "高德地图API（地图服务）", "ReportLab（PDF生成）", "HTML/CSS（前端界面）"],
            "development_time": "2025年8月12日-8月25日",
            "achievements": ["完成基础框架搭建", "实现10条航线可视化", "开发节油计算功能", "支持PDF报告导出", "适配移动端访问"]
        })
    # 登录失败
    return "用户名或密码错误（正确：admin/123456）", 401

@app.route("/login_success")
def login_success():
    return render_template("login_success.html", username=request.args.get("username", "用户"))

@app.route("/route_map")
def route_map():
    """航线地图页面（自动匹配10条预设航线，逻辑不变）"""
    start = request.args.get("start_point", "").strip()
    end = request.args.get("end_point", "").strip()
    original = request.args.get("original_speed", "")
    optimized = request.args.get("optimized_speed", "")
    user_dist = request.args.get("distance", "")

    # 核心逻辑：根据起点终点匹配对应的预设航线（支持10条）
    route_points = get_preset_route(start, end) if (start and end) else read_route_data()
    # 计算航线距离（兼容任意航线的点数量）
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
    """节油量计算（保持原有逻辑，与航线数量无关）"""
    start = request.args.get("start_point", "").strip()
    end = request.args.get("end_point", "").strip()
    required = ["original_speed", "optimized_speed", "distance"]
    # 校验必填参数
    if not all(request.args.get(p) for p in required):
        return "参数不完整", 400
    try:
        # 转换参数类型并校验合理性
        original = float(request.args["original_speed"])
        optimized = float(request.args["optimized_speed"])
        dist = float(request.args["distance"])
        if original <= 0 or optimized <= 0 or dist <= 0 or optimized >= original:
            return "参数错误（优化航速需小于原航速，且所有参数需为正数）", 400
        # 节油量计算公式（保持原有逻辑：(原速-优化速)*距离*0.8）
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
        return "参数格式错误（航速和距离需为数字）", 400

@app.route("/export_pdf")
def export_pdf():
    """PDF报告导出（自动适配当前航线，逻辑不变）"""
    try:
        # 获取当前航线的起点、终点和经纬度点
        start = request.args.get("start_point", "").strip()
        end = request.args.get("end_point", "").strip()
        route_points = get_preset_route(start, end)
        # 若未匹配到航线，使用默认航线
        if not route_points:
            route_points = read_route_data()

        # 组装节油量数据（兼容未填写的情况）
        fuel_data = {
            "start": start or "未知起点",
            "end": end or "未知终点",
            "original": request.args.get("original_speed", "未填写"),
            "optimized": request.args.get("optimized_speed", "未填写"),
            "distance": request.args.get("distance", str(calculate_route_distance(route_points))),
            "saving": request.args.get("saving", "未计算")
        }

        # 生成PDF并返回下载响应
        pdf_buffer = generate_route_report(route_points, fuel_data)
        response = make_response(send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"船舶航线报告_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
        ))
        # 禁止缓存，确保每次下载最新报告
        response.headers['Cache-Control'] = 'no-store, no-cache'
        return response

    except Exception as e:
        logger.error(f"❌ PDF导出失败: {str(e)}")
        return f"PDF导出失败：{str(e)}", 500

# --------------------------- 应用启动 --------------------------- 
if __name__ == "__main__":
    app.run(debug=CONFIG["DEBUG"], port=CONFIG["PORT"], host=CONFIG["HOST"])