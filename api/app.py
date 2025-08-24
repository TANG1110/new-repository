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

# --------------------------- 配置区（统一网络/路由配置） --------------------------- 
API_DIR = os.path.abspath(os.path.dirname(__file__))
CONFIG = {
    "SECRET_KEY": "your_secret_key",
    "DEBUG": True,
    "PORT": int(os.environ.get("PORT", 5000)),  # 统一端口为5000（彩蛋页面原端口）
    "HOST": "0.0.0.0",  # 统一为0.0.0.0（支持外部访问，彩蛋页面原配置）
    "AMAP_API_KEY": "1389a7514ce65016496e0ee1349282b7",
    "ROUTE_DATA_PATH": os.path.join(API_DIR, "../static/route_data.json"),
    # 10条航线映射（包含彩蛋页面的上海-宁波/宁波-上海）
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
    "VALID_USER": {"admin": "123456"},  # 主程序账号
    "DEFAULT_ROUTE": ("上海", "宁波")  # 彩蛋功能：admin登录默认加载上海-宁波
}

# 中文到英文地点映射表
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

# --------------------------- 工具函数（解决航线数据冲突） --------------------------- 
def read_route_data():
    file_path = CONFIG["ROUTE_DATA_PATH"]
    if not os.path.exists(file_path):
        logger.warning(f"⚠️ 默认航线文件不存在: {file_path}")
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f).get("points", [])
    except Exception as e:
        logger.error(f"❌ 读取默认航线失败: {str(e)}")
        return []

def get_preset_route(start_point: str, end_point: str) -> list:
    """统一航线匹配逻辑（支持彩蛋页面的上海-宁波航线）"""
    if not start_point or not end_point:
        return []
        
    start = start_point.strip().lower()
    end = end_point.strip().lower()
    
    # 匹配预设航线（包含上海-宁波）
    for (s, e), filename in CONFIG["PRESET_ROUTE_FILES"].items():
        s_en = LOCATION_TRANSLATIONS.get(s, "").lower()
        e_en = LOCATION_TRANSLATIONS.get(e, "").lower()
        if (start == s.lower() or start == s_en) and (end == e.lower() or end == e_en):
            return load_route_file(filename)
    
    logger.warning(f"⚠️ 未匹配到航线: {start_point}→{end_point}")
    return []

def load_route_file(filename: str) -> list:
    """加载航线文件（确保彩蛋的上海-宁波航线能被读取）"""
    file_path = os.path.join(API_DIR, f"../static/{filename}")
    # 若文件不存在，自动生成彩蛋页面的上海-宁波硬编码数据（兼容彩蛋功能）
    if not os.path.exists(file_path):
        logger.warning(f"⚠️ 航线文件缺失，自动生成: {filename}")
        # 彩蛋页面的上海-宁波精确坐标
        sh_nb_points = [
            [121.507812, 31.237057], [121.552376, 31.202274], [121.837651, 31.051066],
            [121.901726, 30.96938], [122.0377, 31.2511], [122.1017, 31.0694],
            [122.2018, 30.6292], [122.1130, 30.4422], [121.8909, 30.4252],
            [121.8193, 30.2694], [121.6996, 30.1643], [121.8544, 29.9572],
            [121.9528, 29.9771], [122.0262, 29.9258], [122.1683, 29.9293],
            [122.1509, 29.8670], [122.0214, 29.8229]
        ]
        # 生成反向航线（宁波-上海）
        nb_sh_points = sh_nb_points[::-1]
        # 写入文件
        if filename == "shanghai_ningbo.json":
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump({"points": sh_nb_points}, f, indent=2)
            return sh_nb_points
        elif filename == "ningbo_shanghai.json":
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump({"points": nb_sh_points}, f, indent=2)
            return nb_sh_points
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f).get("points", [])
    except Exception as e:
        logger.error(f"❌ 读取航线文件失败 {filename}: {str(e)}")
        return []

def calculate_route_distance(points: list) -> float:
    """统一航程计算逻辑（复用彩蛋页面的haversine算法）"""
    total_km = 0.0
    for i in range(len(points)-1):
        lng1, lat1 = points[i]
        lng2, lat2 = points[i+1]
        # 彩蛋页面的haversine算法（更精确）
        R = 6371
        dLat = math.radians(lat2 - lat1)
        dLon = math.radians(lng2 - lng1)
        a = math.sin(dLat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dLon/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        total_km += R * c
    return round(total_km / 1.852, 2)  # 公里转海里

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

# --------------------------- PDF生成核心函数 ---------------------------
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
        route_table = Table(table_data, colWidths=col_widths)
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

# --------------------------- Flask 应用初始化（统一工厂函数） --------------------------- 
def create_app():
    root_path = os.path.dirname(API_DIR)
    static_path = os.path.join(root_path, "static")
    template_path = os.path.join(root_path, "templates")

    # 自动创建目录（兼容彩蛋页面的目录结构）
    if not os.path.exists(static_path):
        os.makedirs(static_path)
        # 初始化默认航线文件
        with open(CONFIG["ROUTE_DATA_PATH"], "w", encoding="utf-8") as f:
            json.dump({"points": [[121.487899, 31.249162], [121.506302, 31.238938]]}, f, indent=2)

    if not os.path.exists(template_path):
        os.makedirs(template_path)
        # 创建基础模板
        with open(os.path.join(template_path, "base.html"), "w", encoding="utf-8") as f:
            f.write("""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>{% block title %}船舶系统{% endblock %}</title>{% block head_css %}{% endblock %}</head><body style="margin:0; padding:20px; background:#f5f7fa; font-family:Arial,sans-serif;">{% block content %}{% endblock %}</body></html>""")

    app = Flask(__name__, static_folder=static_path, template_folder=template_path)
    app.config.from_mapping(CONFIG)
    return app

app = create_app()

# --------------------------- 路由（整合彩蛋功能+统一参数） --------------------------- 
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
    """整合彩蛋页面登录逻辑：admin登录默认加载上海-宁波，judge显示彩蛋"""
    if request.method == "GET":
        return render_template("login.html")
    user = request.form.get("username", "").strip()
    pwd = request.form.get("password", "").strip()
    if not user or not pwd:
        return "用户名和密码不能为空", 400
    
    # 1. 彩蛋页面：admin登录→默认加载上海-宁波航线（保留彩蛋功能）
    if app.config["VALID_USER"].get(user) == pwd:
        default_start, default_end = app.config["DEFAULT_ROUTE"]
        return redirect(url_for(
            "route_map",
            start_point=default_start,  # 统一参数为start_point（主程序参数）
            end_point=default_end,      # 统一参数为end_point
            original_speed="15.5",      # 默认原航速（彩蛋页面隐含值）
            optimized_speed="12.3"      # 默认优化航速（彩蛋页面隐含值）
        ))
    
    # 2. 主程序彩蛋：judge账号显示团队信息
    if user == "judge" and pwd == "ship2025":
        return render_template("judge_easter_egg.html", team_info={
            "team_name": "海算云帆",
            "members": ["陈倚薇（队长/计算机组）", "刘迪瑶（计算机组）", "唐辉婷（计算机组）","吴珊（金融组）","周子煜（设计组）"],
            "project_intro": "船舶航线可视化与节油系统：支持航线展示、油耗计算和PDF报告导出功能，帮助优化船舶航行效率。",
            "tech_stack": ["Flask（后端框架）", "高德地图API（地图服务）", "ReportLab（PDF生成）", "HTML/CSS（前端界面）"],
            "development_time": "2025年8月12日-8月25日",
            "achievements": ["完成基础框架搭建", "实现航线可视化", "开发节油计算功能", "支持PDF报告导出", "适配移动端访问"]
        })
    
    return "用户名或密码错误（正确：admin/123456 | judge/ship2025）", 401

@app.route("/login_success")
def login_success():
    # 保留登录成功页，若需跳转航线可重定向到route_map
    default_start, default_end = app.config["DEFAULT_ROUTE"]
    return redirect(url_for(
        "route_map",
        start_point=default_start,
        end_point=default_end
    ))

@app.route("/route_map")
def route_map():
    """统一参数名：用start_point/end_point（主程序标准），兼容彩蛋页面功能"""
    start = request.args.get("start_point", "").strip()
    end = request.args.get("end_point", "").strip()
    original = request.args.get("original_speed", "")
    optimized = request.args.get("optimized_speed", "")
    user_dist = request.args.get("distance", "").strip()

    # 核心：获取航线（优先匹配预设，无则用默认）
    route_points = get_preset_route(start, end) if (start and end) else []
    # 计算航程（复用彩蛋页面的精确算法）
    default_dist = calculate_route_distance(route_points) if len(route_points) >=2 else ""
    final_dist = user_dist if user_dist else (str(default_dist) if default_dist != "" else "")

    # 传递JSON格式数据给前端（避免地图加载失败）
    return render_template(
        "route_map.html",
        route_points=json.dumps(route_points),  # 关键：转JSON字符串
        start_point=start,
        end_point=end,
        original_speed=original,
        optimized_speed=optimized,
        distance=final_dist,
        amap_key=app.config["AMAP_API_KEY"]  # 传递高德key给前端（彩蛋页面需求）
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
            route_points = load_route_file("shanghai_ningbo.json")  # 无航线时用上海-宁波（彩蛋功能）
            start = start or "上海"
            end = end or "宁波"

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
            download_name=f"船舶航线报告_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
        ))
        response.headers['Cache-Control'] = 'no-store, no-cache'
        return response

    except Exception as e:
        logger.error(f"❌ PDF导出失败: {str(e)}")
        return f"PDF导出失败：{str(e)}", 500

if __name__ == "__main__":
    # 统一启动配置（与彩蛋页面一致）
    app.run(
        debug=app.config["DEBUG"],
        port=app.config["PORT"],
        host=app.config["HOST"]
    )