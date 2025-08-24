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

# --------------------------- 配置区（整合多航线映射，替换单航线配置） --------------------------- 
API_DIR = os.path.abspath(os.path.dirname(__file__))
CONFIG = {
    "SECRET_KEY": "your_secret_key",
    "DEBUG": True,
    "PORT": int(os.environ.get("PORT", 5001)),
    "HOST": "127.0.0.1",
    "AMAP_API_KEY": "1389a7514ce65016496e0ee1349282b7",
    "ROUTE_DATA_PATH": os.path.join(API_DIR, "../static/route_data.json"),
    # 替换原单航线配置为10条航线映射（与上方多航线逻辑一致）
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

# 中文到英文地点名称映射表（保持下方代码完整）
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

# 日志配置（保持下方代码格式）
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# --------------------------- 工具函数（整合多航线匹配+加载逻辑） --------------------------- 
def read_route_data():
    # 保持下方代码原有逻辑，增加日志详情
    file_path = CONFIG["ROUTE_DATA_PATH"]
    if not os.path.exists(file_path):
        logger.warning(f"⚠️  默认航线文件不存在: {file_path}，将返回空列表")
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            route_data = json.load(f)
            points = route_data.get("points", [])
            logger.debug(f"✅ 读取默认航线成功，共{len(points)}个坐标点")
            return points
    except json.JSONDecodeError:
        logger.error(f"❌ 默认航线文件{file_path}格式错误（JSON解析失败）")
        return []
    except Exception as e:
        logger.error(f"❌ 读取默认航线失败: {str(e)}")
        return []

# 替换原单航线逻辑为多航线匹配（复用上方核心逻辑）
def get_preset_route(start_point: str, end_point: str) -> list:
    """根据起点终点匹配10条预设航线中的任意一条"""
    if not start_point or not end_point:
        logger.warning("⚠️ 起点或终点为空，无法匹配航线")
        return []
        
    # 标准化输入（去除空格、转小写，兼容中文/英文/拼音输入）
    start = start_point.strip().lower()
    end = end_point.strip().lower()
    
    # 1. 精确匹配（中文全称/英文全称）
    for (s_cn, e_cn), filename in CONFIG["PRESET_ROUTE_FILES"].items():
        s_en = LOCATION_TRANSLATIONS.get(s_cn, "").lower()
        e_en = LOCATION_TRANSLATIONS.get(e_cn, "").lower()
        if (start == s_cn.lower() or start == s_en) and \
           (end == e_cn.lower() or end == e_en):
            logger.debug(f"✅ 精确匹配航线：{s_cn}→{e_cn}，加载文件：{filename}")
            return load_route_file(filename)
    
    # 2. 模糊匹配（输入包含城市名，如"上海港"→"上海"、"shenzhen port"→"深圳"）
    for (s_cn, e_cn), filename in CONFIG["PRESET_ROUTE_FILES"].items():
        s_en = LOCATION_TRANSLATIONS.get(s_cn, "").lower()
        e_en = LOCATION_TRANSLATIONS.get(e_cn, "").lower()
        if (s_cn.lower() in start or s_en in start) and \
           (e_cn.lower() in end or e_en in end):
            logger.debug(f"✅ 模糊匹配航线：{s_cn}→{e_cn}，加载文件：{filename}")
            return load_route_file(filename)
    
    # 无匹配时返回空列表（后续逻辑会用默认航线兜底）
    logger.warning(f"⚠️ 未匹配到预设航线：{start_point}→{end_point}（支持航线：{[f'{k[0]}↔{k[1]}' for k in CONFIG['PRESET_ROUTE_FILES'].keys()]}）")
    return []

# 新增：通用航线文件加载函数（复用上方逻辑，适配多航线）
def load_route_file(filename: str) -> list:
    """加载指定名称的航线JSON文件，含格式校验与日志"""
    file_path = os.path.join(API_DIR, f"../static/{filename}")
    if not os.path.exists(file_path):
        logger.error(f"❌ 航线文件不存在: {file_path}（请检查static目录）")
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            route_data = json.load(f)
            points = route_data.get("points", [])
            # 校验坐标格式（确保是[[lng, lat], ...]结构）
            if not isinstance(points, list) or len(points) < 2:
                logger.warning(f"⚠️ 航线文件{filename}格式无效（坐标点不足2个或格式错误）")
                return []
            for idx, point in enumerate(points):
                if not isinstance(point, list) or len(point) != 2:
                    logger.error(f"⚠️ 航线文件{filename}第{idx+1}个坐标无效：{point}（需为[经度, 纬度]）")
                    return []
            logger.debug(f"✅ 加载航线文件成功：{filename}，共{len(points)}个有效坐标点")
            return points
    except json.JSONDecodeError:
        logger.error(f"❌ 航线文件{filename}格式错误（非标准JSON）")
        return []
    except Exception as e:
        logger.error(f"❌ 读取航线文件{filename}失败: {str(e)}")
        return []

# 保持下方代码的航程计算逻辑，增加参数校验
def calculate_route_distance(points: list) -> float:
    if not isinstance(points, list) or len(points) < 2:
        logger.warning("⚠️ 坐标点无效，无法计算航程")
        return 0.0
    total_km = 0.0
    for i in range(len(points)-1):
        # 二次校验坐标格式
        if not isinstance(points[i], list) or len(points[i]) != 2:
            logger.error(f"❌ 无效坐标：{points[i]}，中断航程计算")
            return 0.0
        lng1, lat1 = points[i]
        lng2, lat2 = points[i+1]
        try:
            # 转换为弧度（确保坐标是数字）
            lat1_rad = math.radians(float(lat1))
            lat2_rad = math.radians(float(lat2))
            delta_lat = math.radians(float(lat2) - float(lat1))
            delta_lng = math.radians(float(lng2) - float(lng1))
        except (ValueError, TypeError):
            logger.error(f"❌ 坐标{points[i]}或{points[i+1]}非数字，中断航程计算")
            return 0.0
        a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad)*math.cos(lat2_rad)*math.sin(delta_lng/2)**2
        total_km += 6371 * (2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))
    # 公里转海里（保留2位小数）
    return round(total_km / 1.852, 2)

# 保持下方代码的地点翻译逻辑
def translate_location(chinese_name):
    """将中文地点转换为英文（支持模糊匹配）"""
    if not chinese_name:
        return "Not Specified"
    
    # 先尝试直接从映射表中查找
    translated = LOCATION_TRANSLATIONS.get(chinese_name.strip(), None)
    if translated:
        return translated
    
    # 如果找不到精确匹配，尝试部分匹配（如"上海港"→"Shanghai"）
    for cn, en in LOCATION_TRANSLATIONS.items():
        if cn in chinese_name:
            return en
    
    # 如果完全找不到匹配，返回原名称（处理拼音或英文输入）
    return chinese_name

# --------------------------- PDF生成核心函数（保持下方代码的英文报告格式） ---------------------------
def generate_route_report(route_points, fuel_data):
    buffer = BytesIO()
    
    # 1. 严格控制A4纵向布局，边距最小化（保留下方代码配置）
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=0.8*cm,
        leftMargin=0.8*cm,
        topMargin=0.8*cm,
        bottomMargin=0.8*cm
    )

    # 2. PDF使用英文默认字体（保留下方代码配置）
    font_name = 'Helvetica'

    # 3. 紧凑样式配置（保留下方代码样式）
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
    # 标题和时间（英文，保留下方代码）
    elements.append(Paragraph("Ship Route Visualization System Report", styles['Title_EN']))
    elements.append(Paragraph(f"Generation Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal_EN']))
    elements.append(Spacer(1, 6))

    # 4. 航线坐标表格（适配多航线数据）
    elements.append(Paragraph("1. Route Coordinate Information", styles['Heading2_EN']))
    if route_points and len(route_points) >=2:
        table_data = [["No.", "Longitude", "Latitude"]]
        for idx, (lng, lat) in enumerate(route_points, 1):
            table_data.append([str(idx), f"{float(lng):.6f}", f"{float(lat):.6f}"])
        
        table_width = 21*cm - 1.6*cm
        col_widths = [table_width*0.15, table_width*0.425, table_width*0.425]
        max_rows_per_page = len(table_data)
        row_height = (24*cm) / max_rows_per_page if max_rows_per_page >0 else 15
        
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
        elements.append(Paragraph("⚠️ No valid route coordinate data obtained", styles['Normal_EN']))
    elements.append(Spacer(1, 6))

    # 5. 节油量表格（适配多航线的地点翻译）
    elements.append(Paragraph("2. Fuel Saving Calculation Results", styles['Heading2_EN']))
    if fuel_data:
        # 翻译起点和终点（支持多航线的中文地点）
        translated_start = translate_location(fuel_data.get('start', ''))
        translated_end = translate_location(fuel_data.get('end', ''))
        
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

    # 构建PDF（保留下方代码）
    doc.build(elements)
    buffer.seek(0)
    return buffer

# --------------------------- Flask 应用初始化（整合多航线文件自动生成） --------------------------- 
def create_app():
    root_path = os.path.dirname(API_DIR)
    static_path = os.path.join(root_path, "static")
    template_path = os.path.join(root_path, "templates")

    if not os.path.exists(static_path):
        os.makedirs(static_path)
        logger.info(f"✅ 创建static目录: {static_path}")
        
        # 1. 初始化默认航线文件（保留下方代码）
        with open(CONFIG["ROUTE_DATA_PATH"], "w", encoding="utf-8") as f:
            json.dump({"points": [[121.487899, 31.249162], [121.506302, 31.238938]]}, f, indent=2)
        logger.info(f"✅ 生成默认航线文件: {CONFIG['ROUTE_DATA_PATH']}")
        
        # 2. 自动生成10条航线的JSON文件（整合上方多航线坐标，替换原单航线生成）
        # 上海-宁波
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
        with open(os.path.join(static_path, "shanghai_ningbo.json"), "w", encoding="utf-8") as f:
            json.dump(sh_nb_route, f, indent=2)
        # 宁波-上海（反向）
        with open(os.path.join(static_path, "ningbo_shanghai.json"), "w", encoding="utf-8") as f:
            json.dump({"points": sh_nb_route["points"][::-1]}, f, indent=2)
        
        # 广州-深圳
        gz_sz_route = {
            "points": [
                [113.271429, 23.120049], [113.321429, 23.080049], [113.381429, 23.030049],
                [113.451429, 22.980049], [113.521429, 22.930049], [113.581429, 22.880049],
                [113.651429, 22.830049], [113.721429, 22.780049]
            ]
        }
        with open(os.path.join(static_path, "guangzhou_shenzhen.json"), "w", encoding="utf-8") as f:
            json.dump(gz_sz_route, f, indent=2)
        # 深圳-广州（反向）
        with open(os.path.join(static_path, "shenzhen_guangzhou.json"), "w", encoding="utf-8") as f:
            json.dump({"points": gz_sz_route["points"][::-1]}, f, indent=2)
        
        # 青岛-大连
        qd_dl_route = {
            "points": [
                [120.369293, 36.067072], [120.569293, 36.167072], [120.869293, 36.367072],
                [121.169293, 36.567072], [121.469293, 36.767072], [121.769293, 36.967072],
                [122.069293, 37.167072], [122.369293, 37.367072], [122.669293, 37.567072]
            ]
        }
        with open(os.path.join(static_path, "qingdao_dalian.json"), "w", encoding="utf-8") as f:
            json.dump(qd_dl_route, f, indent=2)
        # 大连-青岛（反向）
        with open(os.path.join(static_path, "dalian_qingdao.json"), "w", encoding="utf-8") as f:
            json.dump({"points": qd_dl_route["points"][::-1]}, f, indent=2)
        
        # 天津-青岛
        tj_qd_route = {
            "points": [[117.200983, 39.084158], [118.200983, 38.884158], [119.200983, 38.684158], [120.369293, 36.067072]]
        }
        with open(os.path.join(static_path, "tianjin_qingdao.json"), "w", encoding="utf-8") as f:
            json.dump(tj_qd_route, f, indent=2)
        # 青岛-天津（反向）
        with open(os.path.join(static_path, "qingdao_tianjin.json"), "w", encoding="utf-8") as f:
            json.dump({"points": tj_qd_route["points"][::-1]}, f, indent=2)
        
        # 厦门-香港
        xm_hk_route = {
            "points": [[118.062342, 24.478636], [118.562342, 24.278636], [119.062342, 24.078636], [114.157696, 22.284621]]
        }
        with open(os.path.join(static_path, "xiamen_hongkong.json"), "w", encoding="utf-8") as f:
            json.dump(xm_hk_route, f, indent=2)
        # 香港-厦门（反向）
        with open(os.path.join(static_path, "hongkong_xiamen.json"), "w", encoding="utf-8") as f:
            json.dump({"points": xm_hk_route["points"][::-1]}, f, indent=2)
        
        logger.info("✅ 10条预设航线文件已全部生成到static目录")

    if not os.path.exists(template_path):
        os.makedirs(template_path)
        logger.info(f"✅ 创建templates目录: {template_path}")
        # 生成基础模板（保留下方代码）
        with open(os.path.join(template_path, "base.html"), "w", encoding="utf-8") as f:
            f.write("""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>{% block title %}船舶系统{% endblock %}</title>{% block head_css %}{% endblock %}</head><body style="margin:0; padding:20px; background:#f5f7fa; font-family:Arial,sans-serif;">{% block content %}{% endblock %}</body></html>""")

    app = Flask(__name__, static_folder=static_path, template_folder=template_path)
    app.config.from_mapping(CONFIG)
    return app

# --------------------------- 路由定义（适配多航线数据传递） --------------------------- 
app = create_app()

@app.route("/")
def index():
    return redirect(url_for("login_page"))

@app.route("/get_location/<lng>/<lat>")
def get_location(lng, lat):
    # 保持下方代码的地理编码逻辑
    try:
        res = requests.get(f"https://restapi.amap.com/v3/geocode/regeo?location={lng},{lat}&key={app.config['AMAP_API_KEY']}", timeout=10)
        return res.json()
    except Exception as e:
        logger.error(f"❌ 调用高德地理编码API失败: {str(e)}")
        return {"error": str(e)}, 500

@app.route("/login_page")
def login_page():
    return render_template("login.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    # 保持下方代码的登录逻辑（含评委彩蛋）
    if request.method == "GET":
        return render_template("login.html")
    user = request.form.get("username", "").strip()
    pwd = request.form.get("password", "").strip()
    if not user or not pwd:
        return "用户名和密码不能为空", 400
    # 普通用户登录
    if app.config["VALID_USER"].get(user) == pwd:
        return redirect(url_for("login_success", username=user))
    # 评委彩蛋账号（保留下方代码的团队信息）
    if user == "judge" and pwd == "ship2025":
        return render_template("judge_easter_egg.html", team_info={
            "team_name": "海算云帆",
            "members": ["陈倚薇（队长/计算机组）", "刘迪瑶（计算机组）", "唐辉婷（计算机组）","吴珊（金融组）","周子煜（设计组）"],
            "project_intro": "船舶航线可视化与节油系统：支持航线展示、油耗计算和PDF报告导出功能，帮助优化船舶航行效率。",
            "tech_stack": ["Flask（后端框架）", "高德地图API（地图服务）", "ReportLab（PDF生成）", "HTML/CSS（前端界面）"],
            "development_time": "2025年8月12日-8月25日",
            "achievements": ["完成基础框架搭建", "实现航线可视化", "开发节油计算功能", "支持PDF报告导出", "适配移动端访问"]
        })
    # 密码错误提示
    return "用户名或密码错误（正确：admin/123456 | judge/ship2025）", 401

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

    # 核心：用多航线逻辑获取航线数据（替换原单航线逻辑）
    route_points = get_preset_route(start, end) if (start and end) else read_route_data()
    # 计算航程（适配多航线的坐标）
    default_dist = calculate_route_distance(route_points)
    final_dist = user_dist if user_dist and user_dist.replace('.','').isdigit() else str(default_dist)

    # 关键修复：传递JSON格式数据给前端（避免地图解析失败）
    return render_template(
        "route_map.html",
        route_points=json.dumps(route_points),  # 转为JSON字符串，兼容前端JS解析
        start_point=start,
        end_point=end,
        original_speed=original,
        optimized_speed=optimized,
        distance=final_dist,
        amap_key=app.config["AMAP_API_KEY"]  # 传递高德API key，确保地图加载
    )

@app.route("/fuel_saving", methods=["GET"])
def fuel_saving():
    # 保持下方代码的节油量计算逻辑（适配多航线的航程数据）
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
            return "参数错误（优化航速需小于原航速且均为正数）", 400
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
        return "参数格式错误（航速和航程需为数字）", 400

@app.route("/export_pdf")
def export_pdf():
    try:
        start = request.args.get("start_point", "").strip()
        end = request.args.get("end_point", "").strip()
        # 用多航线逻辑获取数据（替换原单航线读取）
        route_points = get_preset_route(start, end)
        # 无匹配航线时，用上海-宁波兜底（保留下方代码的兜底逻辑）
        if not route_points or len(route_points) <2:
            route_points = load_route_file("shanghai_ningbo.json")
            start = start or "上海"
            end = end or "宁波"

        # 节油量数据（适配多航线的起点终点）
        fuel_data = {
            "start": start or "未知起点",
            "end": end or "未知终点",
            "original": request.args.get("original_speed", "未填写"),
            "optimized": request.args.get("optimized_speed", "未填写"),
            "distance": request.args.get("distance", str(calculate_route_distance(route_points))),
            "saving": request.args.get("saving", "未计算")
        }

        # 生成PDF（保持下方代码的英文报告逻辑）
        pdf_buffer = generate_route_report(route_points, fuel_data)

        # 返回下载响应
        response = make_response(send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"Ship_Route_Report_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"  # 英文文件名适配
        ))
        response.headers['Cache-Control'] = 'no-store, no-cache'
        return response

    except Exception as e:
        logger.error(f"❌ PDF导出失败: {str(e)}")
        return f"PDF导出失败：{str(e)}", 500

if __name__ == "__main__":
    logger.info(f"✅ 船舶航线系统启动成功：http://{CONFIG['HOST']}:{CONFIG['PORT']}")
    app.run(debug=CONFIG["DEBUG"], port=CONFIG["PORT"], host=CONFIG["HOST"])