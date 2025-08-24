import os
import json
import requests
import logging
import math
import re
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
    "DEBUG": True,  # 调试模式：显示详细错误信息
    "PORT": int(os.environ.get("PORT", 5001)),
    "HOST": "127.0.0.1",
    "AMAP_API_KEY": "1389a7514ce65016496e0ee1349282b7",  # 高德地图API密钥
    "ROUTE_DATA_PATH": os.path.join(API_DIR, "../static/route_data.json"),
    # 10条预设航线配置（城市对 -> 对应的JSON文件名）
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
    "VALID_USER": {"admin": "123456"}  # 登录账号密码
}

# 中文到英文地点映射（用于PDF导出）
LOCATION_TRANSLATIONS = {
    "上海": "Shanghai", "北京": "Beijing", "广州": "Guangzhou",
    "深圳": "Shenzhen", "宁波": "Ningbo", "天津": "Tianjin",
    "青岛": "Qingdao", "大连": "Dalian", "厦门": "Xiamen",
    "香港": "Hong Kong", "澳门": "Macau", "重庆": "Chongqing",
    "南京": "Nanjing", "杭州": "Hangzhou", "苏州": "Suzhou", "武汉": "Wuhan"
}

# 日志配置（便于排查错误）
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# --------------------------- 工具函数 --------------------------- 
def read_route_data():
    """读取默认航线（备用）"""
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
    """根据起点终点匹配预设航线（修复匹配逻辑）"""
    if not start_point or not end_point:
        return []
        
    # 标准化输入（支持中文/英文匹配）
    start = start_point.strip()
    end = end_point.strip()
    
    # 遍历预设航线，匹配中文或英文名称
    for (s_cn, e_cn), filename in CONFIG["PRESET_ROUTE_FILES"].items():
        s_en = LOCATION_TRANSLATIONS.get(s_cn, "")
        e_en = LOCATION_TRANSLATIONS.get(e_cn, "")
        
        if (start == s_cn or start.lower() == s_en.lower()) and \
           (end == e_cn or end.lower() == e_en.lower()):
            logger.debug(f"✅ 匹配航线: {s_cn}→{e_cn}，文件: {filename}")
            return load_route_file(filename)
    
    logger.warning(f"⚠️ 未匹配到航线: {start}→{end}")
    return []

def load_route_file(filename: str) -> list:
    """加载航线文件（修复路径错误，确保能找到文件）"""
    # 绝对路径拼接（解决相对路径混乱问题）
    file_path = os.path.join(os.path.dirname(API_DIR), "static", filename)
    if not os.path.exists(file_path):
        logger.error(f"❌ 航线文件不存在: {file_path}（请检查static文件夹）")
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            points = data.get("points", [])
            logger.debug(f"✅ 加载航线成功: {filename}，共{len(points)}个坐标")
            return points
    except json.JSONDecodeError:
        logger.error(f"❌ 航线文件格式错误: {filename}（请检查JSON格式）")
        return []
    except Exception as e:
        logger.error(f"❌ 读取航线文件失败: {str(e)}")
        return []

def calculate_route_distance(points: list) -> float:
    """计算航线距离（修复坐标格式错误导致的崩溃）"""
    if len(points) < 2:
        logger.warning(f"⚠️ 坐标点不足（仅{len(points)}个），无法计算距离")
        return 0.0
    total_km = 0.0
    for i in range(len(points)-1):
        # 校验坐标格式（防止无效数据导致崩溃）
        if not isinstance(points[i], list) or len(points[i]) != 2:
            logger.error(f"❌ 无效坐标: {points[i]}（应为[经度, 纬度]）")
            return 0.0
        if not isinstance(points[i+1], list) or len(points[i+1]) != 2:
            logger.error(f"❌ 无效坐标: {points[i+1]}（应为[经度, 纬度]）")
            return 0.0
            
        lng1, lat1 = points[i]
        lng2, lat2 = points[i+1]
        # 计算两点间距离（经纬度转公里）
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lng = math.radians(lng2 - lng1)
        a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad)*math.cos(lat2_rad)*math.sin(delta_lng/2)**2
        total_km += 6371 * (2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))
    # 公里转海里（1海里=1.852公里）
    return round(total_km / 1.852, 2)

def translate_location(chinese_name):
    """地名中英文转换（用于PDF报告）"""
    if not chinese_name:
        return "Not Specified"
    if re.search('[\u4e00-\u9fa5]', chinese_name):  # 包含中文
        translated = LOCATION_TRANSLATIONS.get(chinese_name.strip())
        if translated:
            return translated
        for cn, en in LOCATION_TRANSLATIONS.items():
            if cn in chinese_name:
                return en
        return chinese_name
    return chinese_name  # 英文直接返回

# --------------------------- PDF生成函数 ---------------------------
def generate_route_report(route_points, fuel_data):
    """生成航线报告PDF（修复字段缺失导致的崩溃）"""
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

    # 1. 航线坐标信息
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

    # 2. 节油量计算结果
    elements.append(Paragraph("2. Fuel Saving Calculation Results", styles['Heading2_EN']))
    if fuel_data:
        fuel_table_data = [
            ["Parameter", "Value"],
            ["Start Point", fuel_data.get("start", "N/A")],
            ["End Point", fuel_data.get("end", "N/A")],
            ["Original Speed", f"{fuel_data.get('original', 'N/A')} knots"],
            ["Optimized Speed", f"{fuel_data.get('optimized', 'N/A')} knots"],
            ["Route Distance", f"{fuel_data.get('distance', 'N/A')} nautical miles"],
            ["Fuel Saved", f"{fuel_data.get('saving', 'N/A')} tons"]
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

# --------------------------- Flask应用初始化 --------------------------- 
def create_app():
    """创建Flask应用（确保目录结构正确）"""
    root_path = os.path.dirname(API_DIR)
    static_path = os.path.join(root_path, "static")
    template_path = os.path.join(root_path, "templates")

    # 自动创建缺失的目录和文件
    if not os.path.exists(static_path):
        os.makedirs(static_path)
        logger.info(f"✅ 创建static目录: {static_path}")
        # 初始化默认航线文件（备用）
        with open(CONFIG["ROUTE_DATA_PATH"], "w", encoding="utf-8") as f:
            json.dump({"points": [[121.487899, 31.249162], [121.506302, 31.238938]]}, f, indent=2)

    if not os.path.exists(template_path):
        os.makedirs(template_path)
        logger.info(f"✅ 创建templates目录: {template_path}")
        # 创建基础模板
        with open(os.path.join(template_path, "base.html"), "w", encoding="utf-8") as f:
            f.write("""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>{% block title %}船舶系统{% endblock %}</title>{% block head_css %}{% endblock %}</head><body style="margin:0; padding:20px; background:#f5f7fa; font-family:Arial,sans-serif;">{% block content %}{% endblock %}</body></html>""")

    app = Flask(__name__, static_folder=static_path, template_folder=template_path)
    app.config.from_mapping(CONFIG)
    return app

app = create_app()

# --------------------------- 路由定义 --------------------------- 
@app.route("/")
def index():
    return redirect(url_for("login_page"))

@app.route("/get_location/<lng>/<lat>")
def get_location(lng, lat):
    """获取经纬度对应的地址（备用接口）"""
    try:
        res = requests.get(
            f"https://restapi.amap.com/v3/geocode/regeo?location={lng},{lat}&key={app.config['AMAP_API_KEY']}",
            timeout=10
        )
        return res.json()
    except Exception as e:
        logger.error(f"❌ 地址解析失败: {str(e)}")
        return {"error": "地址解析失败"}, 500

@app.route("/login_page")
def login_page():
    """登录页面"""
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
    # 验证普通用户
    if app.config["VALID_USER"].get(user) == pwd:
        return redirect(url_for("login_success", username=user))
    # 评委彩蛋账号
    if user == "judge" and pwd == "ship2025":
        return render_template("judge_easter_egg.html", team_info={
            "team_name": "海算云帆",
            "members": ["陈倚薇（队长/计算机组）", "刘迪瑶（计算机组）", "唐辉婷（计算机组）","吴珊（金融组）","周子煜（设计组）"],
            "project_intro": "船舶航线可视化与节油系统：支持航线展示、油耗计算和PDF报告导出功能。",
            "tech_stack": ["Flask（后端）", "高德地图API（地图）", "ReportLab（PDF）", "HTML/CSS（前端）"],
            "development_time": "2025年8月12日-8月25日",
            "achievements": ["基础框架搭建", "航线可视化", "节油计算", "PDF导出", "移动端适配"]
        })
    return "用户名或密码错误（正确：admin/123456）", 401

@app.route("/login_success")
def login_success():
    """登录成功页面"""
    return render_template("login_success.html", username=request.args.get("username", "用户"))

@app.route("/route_map")
def route_map():
    """航线可视化页面（核心修复：解决地图不显示和数据格式错误）"""
    try:
        start = request.args.get("start_point", "").strip()
        end = request.args.get("end_point", "").strip()
        original = request.args.get("original_speed", "")
        optimized = request.args.get("optimized_speed", "")
        user_dist = request.args.get("distance", "").strip()

        # 核心：未输入起点终点时返回空列表（无初始化航线）
        route_points = get_preset_route(start, end) if (start and end) else []
        # 计算航程（坐标点足够时才计算）
        default_dist = calculate_route_distance(route_points) if len(route_points)>=2 else 0.0
        final_dist = user_dist if user_dist else str(default_dist)

        # 关键修复：用json.dumps()转换为JSON字符串，确保前端能解析
        return render_template(
            "route_map.html",
            route_points=json.dumps(route_points),  # 修复：传递JSON格式数据
            start_point=start,
            end_point=end,
            original_speed=original,
            optimized_speed=optimized,
            distance=final_dist
        )
    except Exception as e:
        logger.error(f"❌ route_map路由错误: {str(e)}")
        return "服务器内部错误，请稍后再试", 500

@app.route("/fuel_saving", methods=["GET"])
def fuel_saving():
    """节油量计算结果页面"""
    try:
        start = request.args.get("start_point", "").strip()
        end = request.args.get("end_point", "").strip()
        required = ["original_speed", "optimized_speed", "distance"]
        if not all(request.args.get(p) for p in required):
            return "参数不完整（请填写原航速、优化航速和航程）", 400
        
        # 验证参数有效性
        try:
            original = float(request.args["original_speed"])
            optimized = float(request.args["optimized_speed"])
            dist = float(request.args["distance"])
        except ValueError:
            return "参数格式错误（航速和航程必须为数字）", 400
        
        if original <=0 or optimized <=0 or dist <=0 or optimized >= original:
            return "参数错误（优化航速必须大于0且小于原航速）", 400
        
        # 计算节油量（公式：(原航速-优化航速)×航程×0.8）
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
    except Exception as e:
        logger.error(f"❌ fuel_saving路由错误: {str(e)}")
        return "服务器内部错误，请稍后再试", 500

@app.route("/export_pdf")
def export_pdf():
    """导出PDF报告（修复字段缺失和文件加载失败）"""
    try:
        start = request.args.get("start_point", "").strip() or "未知起点"
        end = request.args.get("end_point", "").strip() or "未知终点"
        # 获取航线数据（无数据时用上海-宁波兜底）
        route_points = get_preset_route(start, end)
        if not route_points:
            route_points = load_route_file("shanghai_ningbo.json")
            logger.warning(f"⚠️ 无航线数据，使用上海-宁波兜底数据")

        # 准备PDF数据（确保字段完整）
        fuel_data = {
            "start": translate_location(start),
            "end": translate_location(end),
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
        logger.error(f"❌ PDF导出错误: {str(e)}")
        return "报告生成失败，请稍后再试", 500

if __name__ == "__main__":
    # 启动应用（确保端口未被占用）
    logger.info(f"✅ 应用启动: http://{CONFIG['HOST']}:{CONFIG['PORT']}")
    app.run(debug=CONFIG["DEBUG"], port=CONFIG["PORT"], host=CONFIG["HOST"])
