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
# 10条航线文件路径配置（与static文件夹中的JSON文件对应）
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

# 中文到英文地点名称映射表（覆盖所有10条航线涉及的城市）
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

# 日志配置 - 增加文件日志记录便于调试
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(API_DIR, "app.log"), encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)

# --------------------------- 工具函数 --------------------------- 
def read_route_data():
    """读取默认航线（备用）"""
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
    """匹配10条预设航线，增强匹配容错性"""
    if not start_point or not end_point:
        logger.debug(f"⚠️  起点或终点为空: {start_point}→{end_point}")
        return []
    
    # 统一输入格式，支持中文、拼音、英文匹配
    start = start_point.strip().lower()
    end = end_point.strip().lower()
    logger.debug(f"处理航线查询: {start}→{end}")
    
    # 地点别名映射（增强匹配容错）
    location_aliases = {
        "上海": ["上海", "shanghai", "沪", "sh"],
        "宁波": ["宁波", "ningbo", "甬", "nb"],
        "广州": ["广州", "guangzhou", "穗", "gz"],
        "深圳": ["深圳", "shenzhen", "sz"],
        "青岛": ["青岛", "qingdao", "qd"],
        "大连": ["大连", "dalian", "dl"],
        "天津": ["天津", "tianjin", "津", "tj"],
        "厦门": ["厦门", "xiamen", "xm"],
        "香港": ["香港", "hong kong", "hk", "港"]
    }
    
    # 匹配标准城市名称
    matched_start = None
    matched_end = None
    for std_name, aliases in location_aliases.items():
        if any(alias in start for alias in aliases) and not matched_start:
            matched_start = std_name
            logger.debug(f"匹配起点: {start} → {std_name}")
        if any(alias in end for alias in aliases) and not matched_end:
            matched_end = std_name
            logger.debug(f"匹配终点: {end} → {std_name}")
    
    if not matched_start or not matched_end:
        logger.warning(f"⚠️  未匹配到有效城市：{start_point}→{end_point}")
        return []
    
    # 构建航线键（如“广州-深圳”）
    route_key = f"{matched_start}-{matched_end}"
    if route_key not in PRESET_ROUTE_FILES:
        logger.warning(f"⚠️  无预设航线：{route_key}（支持航线：{list(PRESET_ROUTE_FILES.keys())}）")
        return []
    
    # 验证文件是否存在
    file_path = PRESET_ROUTE_FILES[route_key]
    if not os.path.exists(file_path):
        logger.error(f"❌ 航线文件不存在: {file_path}")
        return []
    
    # 读取对应的航线JSON文件
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            route_data = json.load(f)
            points = route_data.get("points", [])
            logger.debug(f"成功加载航线 {route_key}，包含 {len(points)} 个坐标点")
            return points
    except Exception as e:
        logger.error(f"❌ 读取航线{route_key}失败: {str(e)}")
        return []

def calculate_route_distance(points: list) -> float:
    """计算航线距离（海里），使用Haversine公式"""
    if len(points) < 2:
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
        
        # Haversine公式
        a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lng/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        
        # 地球半径约为6371公里
        distance_km = 6371 * c
        total_km += distance_km
    
    # 转换为海里（1海里 = 1.852公里）
    total_nm = total_km / 1.852
    logger.debug(f"计算航线距离: {total_km:.2f}公里 = {total_nm:.2f}海里")
    return round(total_nm, 2)

def translate_location(chinese_name):
    """将中文地名转换为英文（用于PDF导出）"""
    if not chinese_name:
        return "Not Specified"
    
    # 清理输入
    name = chinese_name.strip()
    
    # 优先精确匹配
    translated = LOCATION_TRANSLATIONS.get(name, None)
    if translated:
        logger.debug(f"地名翻译: {name} → {translated}")
        return translated
    
    # 部分匹配（如输入“广州港”→“Guangzhou”）
    for cn, en in LOCATION_TRANSLATIONS.items():
        if cn in name:
            logger.debug(f"地名部分匹配翻译: {name} → {en}")
            return en
    
    # 无匹配时返回原名称，但记录日志
    logger.warning(f"⚠️  未找到地名翻译: {name}")
    return name

# --------------------------- PDF生成核心函数（确保地名英文转换） ---------------------------
def generate_route_report(route_points, fuel_data):
    """生成包含航线信息和节油量的PDF报告，确保地名英文转换"""
    buffer = BytesIO()
    
    # A4纵向布局
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=0.8*cm,
        leftMargin=0.8*cm,
        topMargin=0.8*cm,
        bottomMargin=0.8*cm
    )

    # 样式配置
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name='Title_EN',
        parent=styles['Title'],
        fontName='Helvetica',
        fontSize=18,
        alignment=1,
        spaceAfter=8
    ))
    styles.add(ParagraphStyle(
        name='Normal_EN',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=12
    ))
    styles.add(ParagraphStyle(
        name='Heading2_EN',
        parent=styles['Heading2'],
        fontName='Helvetica',
        fontSize=14,
        spaceBefore=6,
        spaceAfter=6
    ))

    elements = []
    # 标题和生成时间
    elements.append(Paragraph("Ship Route Visualization System Report", styles['Title_EN']))
    elements.append(Paragraph(f"Generation Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal_EN']))
    elements.append(Spacer(1, 6))

    # 航线坐标表格
    elements.append(Paragraph("1. Route Coordinate Information", styles['Heading2_EN']))
    if route_points and len(route_points) > 0:
        table_data = [["No.", "Longitude", "Latitude"]]
        for idx, (lng, lat) in enumerate(route_points, 1):
            table_data.append([str(idx), f"{lng:.6f}", f"{lat:.6f}"])
        
        table_width = 21*cm - 1.6*cm
        col_widths = [table_width*0.15, table_width*0.425, table_width*0.425]
        row_height = 0.7*cm
        
        route_table = Table(table_data, colWidths=col_widths, rowHeights=row_height)
        route_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))
        elements.append(route_table)
    else:
        elements.append(Paragraph("⚠️ No route coordinate data obtained", styles['Normal_EN']))
    elements.append(Spacer(1, 6))

    # 节油量表格（确保地名英文转换）
    elements.append(Paragraph("2. Fuel Saving Calculation Results", styles['Heading2_EN']))
    if fuel_data:
        # 强制转换为英文
        translated_start = translate_location(fuel_data.get('start'))
        translated_end = translate_location(fuel_data.get('end'))
        
        fuel_table_data = [
            ["Parameter", "Value"],
            ["Start Point", translated_start],  # 英文地名
            ["End Point", translated_end],      # 英文地名
            ["Original Speed", f"{fuel_data.get('original')} knots"],
            ["Optimized Speed", f"{fuel_data.get('optimized')} knots"],
            ["Route Distance", f"{fuel_data.get('distance')} nautical miles"],
            ["Fuel Saved", f"{fuel_data.get('saving')} tons"]
        ]
        
        fuel_table = Table(fuel_table_data, colWidths=[table_width*0.3, table_width*0.7])
        fuel_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
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
    """初始化Flask应用，确保必要文件夹存在"""
    root_path = os.path.dirname(API_DIR)
    static_path = os.path.join(root_path, "static")
    template_path = os.path.join(root_path, "templates")

    # 确保static和templates文件夹存在
    if not os.path.exists(static_path):
        os.makedirs(static_path)
        logger.debug(f"创建static文件夹: {static_path}")
        # 初始化默认航线文件（备用）
        with open(CONFIG["ROUTE_DATA_PATH"], "w", encoding="utf-8") as f:
            json.dump({"points": [[121.487899, 31.249162], [121.506302, 31.238938]]}, f, indent=2)

    if not os.path.exists(template_path):
        os.makedirs(template_path)
        logger.debug(f"创建templates文件夹: {template_path}")
        # 生成基础模板base.html
        with open(os.path.join(template_path, "base.html"), "w", encoding="utf-8") as f:
            f.write("""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>{% block title %}船舶系统{% endblock %}</title>{% block head_css %}{% endblock %}</head><body style="margin:0; padding:20px; background:#f5f7fa; font-family:Arial,sans-serif;">{% block content %}{% endblock %}</body></html>""")

    app = Flask(__name__, static_folder=static_path, template_folder=template_path)
    app.config.from_mapping(CONFIG)
    return app

# --------------------------- 路由定义 --------------------------- 
app = create_app()

@app.route("/")
def index():
    """首页重定向到登录页"""
    return redirect(url_for("login_page"))

@app.route("/get_location/<lng>/<lat>")
def get_location(lng, lat):
    """通过经纬度获取地址信息"""
    try:
        res = requests.get(
            f"https://restapi.amap.com/v3/geocode/regeo?location={lng},{lat}&key={app.config['AMAP_API_KEY']}",
            timeout=10
        )
        return res.json()
    except Exception as e:
        logger.error(f"获取地址信息失败: {str(e)}")
        return {"error": str(e)}, 500

@app.route("/login_page")
def login_page():
    """显示登录页面"""
    return render_template("login.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    """处理登录请求"""
    if request.method == "GET":
        return render_template("login.html")
    
    user = request.form.get("username", "").strip()
    pwd = request.form.get("password", "").strip()
    
    if not user or not pwd:
        return "用户名和密码不能为空", 400
    
    # 普通用户登录
    if app.config["VALID_USER"].get(user) == pwd:
        logger.info(f"用户登录成功: {user}")
        return redirect(url_for("login_success", username=user))
    
    # 评委彩蛋账号
    if user == "judge" and pwd == "ship2025":
        logger.info("评委账号登录成功")
        return render_template("judge_easter_egg.html", team_info={
            "team_name": "海算云帆",
            "members": ["陈倚薇（队长/计算机组）", "刘迪瑶（计算机组）", "唐辉婷（计算机组）","吴珊（金融组）","周子煜（设计组）"],
            "project_intro": "船舶航线可视化与节油系统：支持航线展示、油耗计算和PDF报告导出功能，帮助优化船舶航行效率。",
            "tech_stack": ["Flask（后端框架）", "高德地图API（地图服务）", "ReportLab（PDF生成）", "HTML/CSS（前端界面）"],
            "development_time": "2025年8月12日-8月25日",
            "achievements": ["完成基础框架搭建", "实现航线可视化", "开发节油计算功能", "支持PDF报告导出", "适配移动端访问"]
        })
    
    # 密码错误提示
    logger.warning(f"用户登录失败: {user}")
    return "用户名或密码错误（正确：admin/123456）", 401

@app.route("/login_success")
def login_success():
    """登录成功页面"""
    username = request.args.get("username", "用户")
    return render_template("login_success.html", username=username)

@app.route("/route_map")
def route_map():
    """航线地图页面，核心功能：确保留白时自动计算航线距离"""
    start = request.args.get("start_point", "").strip()
    end = request.args.get("end_point", "").strip()
    original = request.args.get("original_speed", "")
    optimized = request.args.get("optimized_speed", "")
    user_dist = request.args.get("distance", "").strip()

    logger.debug(f"访问航线地图: {start}→{end}, 原航速: {original}, 优化航速: {optimized}")
    
    # 核心逻辑：仅当同时有起点和终点时才加载航线，否则返回空列表（无航线）
    route_points = get_preset_route(start, end) if (start and end) else []
    
    # 计算航程：用户输入优先，否则自动计算，无航线时留空
    final_dist = ""
    if user_dist:
        final_dist = user_dist
        logger.debug(f"使用用户输入的航程: {final_dist}")
    elif route_points:
        calculated_dist = calculate_route_distance(route_points)
        final_dist = str(calculated_dist)
        logger.debug(f"自动计算航程: {final_dist}")

    return render_template(
        "route_map.html",
        route_points=json.dumps(route_points),  # 传递JSON字符串，避免前端解析错误
        start_point=start,
        end_point=end,
        original_speed=original,
        optimized_speed=optimized,
        distance=final_dist
    )

@app.route("/fuel_saving", methods=["GET"])
def fuel_saving():
    """节油量计算结果页面"""
    start = request.args.get("start_point", "").strip()
    end = request.args.get("end_point", "").strip()
    required = ["original_speed", "optimized_speed", "distance"]
    
    # 验证参数完整性
    if not all(request.args.get(p) for p in required):
        logger.warning("节油量计算参数不完整")
        return "参数不完整，请填写所有必填项", 400
    
    try:
        # 转换参数并验证
        original = float(request.args["original_speed"])
        optimized = float(request.args["optimized_speed"])
        dist = float(request.args["distance"])
        
        if original <= 0 or optimized <= 0 or dist <= 0:
            logger.warning(f"节油量计算参数为非正数: 原航速={original}, 优化航速={optimized}, 航程={dist}")
            return "参数错误：航速和航程必须为正数", 400
            
        if optimized >= original:
            logger.warning(f"节油量计算参数不合理: 优化航速({optimized}) >= 原航速({original})")
            return "参数错误：优化航速必须小于原航速", 400
        
        # 节油量计算公式
        saving = round((original - optimized) * dist * 0.8, 2)
        logger.debug(f"节油量计算完成: {original}节 → {optimized}节, 航程{dist}海里, 节油量{saving}吨")
        
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
        logger.error("节油量计算参数格式错误", exc_info=True)
        return "参数格式错误，请输入有效的数字", 400

@app.route("/export_pdf")
def export_pdf():
    """导出PDF报告，确保地名英文转换"""
    try:
        start = request.args.get("start_point", "").strip()
        end = request.args.get("end_point", "").strip()
        logger.debug(f"导出PDF报告: {start}→{end}")
        
        # 加载航线数据
        route_points = get_preset_route(start, end)
        if not route_points:
            logger.warning(f"无航线数据，使用默认航线: {start}→{end}")
            # 使用上海-宁波作为默认航线
            with open(PRESET_ROUTE_FILES["上海-宁波"], "r", encoding="utf-8") as f:
                route_points = json.load(f).get("points", [])

        # 节油量数据（确保地名会被转换为英文）
        fuel_data = {
            "start": start or "上海",
            "end": end or "宁波",
            "original": request.args.get("original_speed", "未填写"),
            "optimized": request.args.get("optimized_speed", "未填写"),
            "distance": request.args.get("distance", str(calculate_route_distance(route_points))),
            "saving": request.args.get("saving", "未计算")
        }

        # 生成PDF
        pdf_buffer = generate_route_report(route_points, fuel_data)
        
        # 返回PDF下载响应
        response = make_response(send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"船舶航线报告_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
        ))
        response.headers['Cache-Control'] = 'no-store, no-cache'
        logger.debug(f"PDF报告生成成功: {start}→{end}")
        return response

    except Exception as e:
        logger.error(f"PDF导出失败: {str(e)}", exc_info=True)
        return f"PDF导出失败：{str(e)}", 500

if __name__ == "__main__":
    """应用入口"""
    logger.info("船舶航线可视化系统启动")
    app.run(debug=CONFIG["DEBUG"], port=CONFIG["PORT"], host=CONFIG["HOST"])
