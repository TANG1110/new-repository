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
PROJECT_ROOT = os.path.abspath(os.path.join(API_DIR, ".."))

# 预设航线文件路径（严格遵循“城市拼音-城市拼音.json”）
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
    "SECRET_KEY": "1389a7514ce65016496e0ee1349282b6",
    "DEBUG": False,  # Vercel部署必须关闭DEBUG
    "PORT": int(os.environ.get("PORT", 5000)),
    "HOST": "0.0.0.0",
    "AMAP_API_KEY": "1389a7514ce65016496e0ee1349282b7",  # 已验证密钥格式正确
    "ROUTE_DATA_PATH": os.path.join(PROJECT_ROOT, "static/route_data.json"),
    "VALID_USER": {"admin": "123456"}
}

# 地点中英文映射
LOCATION_TRANSLATIONS = {
    "上海": "Shanghai", "宁波": "Ningbo", "广州": "Guangzhou", "深圳": "Shenzhen",
    "青岛": "Qingdao", "大连": "Dalian", "天津": "Tianjin", "厦门": "Xiamen", "香港": "Hong Kong"
}

# 日志配置（增加航线匹配详细日志，便于调试）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# --------------------------- 工具函数 ---------------------------
def read_route_data():
    """读取默认航线（上海→宁波）"""
    file_path = CONFIG["ROUTE_DATA_PATH"]
    if not os.path.exists(file_path):
        logger.warning(f"默认航线文件不存在: {file_path}，自动创建上海-宁波默认航线")
        sh_nb_default = {
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
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(sh_nb_default, f, indent=2)
        return sh_nb_default["points"]
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "points" not in data or not isinstance(data["points"], list):
                logger.error(f"默认航线文件格式错误：缺少'points'字段或字段类型错误")
                return []
            return data["points"]
    except Exception as e:
        logger.error(f"读取默认航线失败: {str(e)}，使用上海-宁波备用航线")
        sh_nb_backup = [
            [121.582812, 31.372057], [121.642376, 31.372274], [121.719159, 31.329024],
            [121.808468, 31.277377], [121.862846, 31.266428], [122.037651, 31.251066],
            [122.101726, 31.06938], [122.201797, 30.629212], [122.11298, 30.442215],
            [121.89094, 30.425198], [121.819322, 30.269414], [121.69957, 30.164341],
            [121.854434, 29.957196], [121.854434, 29.957196], [121.910951, 29.954561],
            [121.952784, 29.977126], [122.02619, 29.925834], [122.069602, 29.911468],
            [122.168266, 29.929254], [122.176948, 29.897783], [122.150901, 29.866987],
            [122.02136, 29.822932]
        ]
        return sh_nb_backup

def get_preset_route(start_point: str, end_point: str) -> list:
    """【优化】匹配预设航线（支持中文/拼音/简称/大小写模糊匹配）"""
    if not start_point or not end_point:
        logger.warning("起点或终点为空，返回默认航线")
        return read_route_data()
    
    # 统一转为小写，增强匹配容错
    start = start_point.strip().lower()
    end = end_point.strip().lower()
    
    # 扩展地点别名库，支持更多输入形式（如拼音缩写、中英文混合）
    location_aliases = {
        "上海": ["上海", "shanghai", "沪", "sh"],
        "宁波": ["宁波", "ningbo", "甬", "nb"],
        "广州": ["广州", "guangzhou", "穗", "gz", "guang zhou"],
        "深圳": ["深圳", "shenzhen", "sz", "shen zhen"],
        "青岛": ["青岛", "qingdao", "qd", "qing dao"],
        "大连": ["大连", "dalian", "dl", "da lian"],
        "天津": ["天津", "tianjin", "津", "tj", "tian jin"],
        "厦门": ["厦门", "xiamen", "鹭", "xm", "xia men"],
        "香港": ["香港", "hong kong", "港", "hk", "xiang gang"]
    }
    
    # 【优化】模糊匹配：只要输入包含别名的一部分，就视为匹配（如输入“广”也能匹配广州）
    matched_start = None
    matched_end = None
    for std_name, aliases in location_aliases.items():
        if not matched_start:
            for alias in aliases:
                if alias in start or start in alias:
                    matched_start = std_name
                    break
        if not matched_end:
            for alias in aliases:
                if alias in end or end in alias:
                    matched_end = std_name
                    break
    
    # 打印匹配日志，便于调试（开发阶段保留）
    logger.info(f"输入起点：{start_point} → 匹配结果：{matched_start}")
    logger.info(f"输入终点：{end_point} → 匹配结果：{matched_end}")
    
    # 未匹配到有效地点时，返回默认航线
    if not matched_start or not matched_end:
        logger.warning(f"未匹配到有效地点：{start_point}→{end_point}，使用默认上海-宁波航线")
        return read_route_data()
    
    # 构建航线键（如“广州-深圳”）
    route_key = f"{matched_start}-{matched_end}"
    if route_key not in PRESET_ROUTE_FILES:
        logger.warning(f"无预设航线：{route_key}，可用航线：{list(PRESET_ROUTE_FILES.keys())}")
        return read_route_data()
    
    # 检查航线文件是否存在
    file_path = PRESET_ROUTE_FILES[route_key]
    if not os.path.exists(file_path):
        logger.error(f"航线文件缺失：{file_path}，使用默认上海-宁波航线")
        return read_route_data()
    
    # 读取并验证航线文件
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "points" not in data or not isinstance(data["points"], list) or len(data["points"]) < 2:
                logger.error(f"航线文件{route_key}格式错误：'points'字段无效或坐标点不足")
                return read_route_data()
            route_points = data["points"]
            logger.info(f"✅ 成功加载航线：{route_key}（{len(route_points)}个坐标点）")
            return route_points
    except json.JSONDecodeError:
        logger.error(f"航线文件{route_key}JSON解析失败：格式错误")
        return read_route_data()
    except Exception as e:
        logger.error(f"读取航线{route_key}失败：{str(e)}，使用默认上海-宁波航线")
        return read_route_data()

def calculate_route_distance(points: list) -> float:
    """计算航线距离（单位：海里）"""
    if len(points) < 2:
        logger.warning("坐标点不足2个，无法计算航程")
        return 0.0
    total_km = 0.0
    for i in range(len(points)-1):
        try:
            lng1, lat1 = points[i]
            lng2, lat2 = points[i+1]
            # 验证经纬度格式（防止无效坐标）
            if not (-180 <= lng1 <= 180 and -90 <= lat1 <= 90 and -180 <= lng2 <= 180 and -90 <= lat2 <= 90):
                logger.warning(f"无效坐标点：({lng1},{lat1}) → ({lng2},{lat2})，跳过计算")
                continue
            # Haversine公式计算距离
            lat1_rad = math.radians(lat1)
            lat2_rad = math.radians(lat2)
            delta_lat = math.radians(lat2 - lat1)
            delta_lng = math.radians(lng2 - lng1)
            a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lng/2)**2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
            total_km += 6371 * c  # 地球半径≈6371km
        except Exception as e:
            logger.error(f"计算坐标点距离失败：{str(e)}，跳过该点")
            continue
    return round(total_km / 1.852, 2)  # 转换为海里（1海里=1.852km）

def translate_location(chinese_name):
    """中文地点转英文"""
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
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name='Title',
        parent=styles['Title'],
        fontSize=16,
        alignment=1,
        spaceAfter=12
    ))
    styles.add(ParagraphStyle(
        name='Normal',
        parent=styles['Normal'],
        fontSize=10,
        leading=14
    ))

    elements = []
    elements.append(Paragraph("船舶航线可视化系统报告", styles['Title']))
    elements.append(Paragraph(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
    elements.append(Spacer(1, 10))

    # 航线坐标表格
    elements.append(Paragraph("1. 航线坐标信息", styles['Heading2']))
    if route_points and len(route_points) >= 2:
        table_data = [["序号", "经度", "纬度"]]
        for idx, (lng, lat) in enumerate(route_points, 1):
            table_data.append([str(idx), f"{lng:.6f}", f"{lat:.6f}"])
        table = Table(table_data, colWidths=[50, 100, 100])
        table.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 1, colors.grey),
            ('BACKGROUND', (0,0), (-1,0), colors.lightblue),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('FONT SIZE', (0,0), (-1,-1), 9)
        ]))
        elements.append(table)
    else:
        elements.append(Paragraph("⚠️ 未获取到有效航线坐标数据", styles['Normal']))
    elements.append(Spacer(1, 10))

    # 节油量结果
    elements.append(Paragraph("2. 节油量计算结果", styles['Heading2']))
    if fuel_data:
        fuel_table_data = [
            ["参数", "数值"],
            ["起点", fuel_data.get('start', '未知')],
            ["终点", fuel_data.get('end', '未知')],
            ["原航速", f"{fuel_data.get('original', '未填写')} 节"],
            ["优化航速", f"{fuel_data.get('optimized', '未填写')} 节"],
            ["航程", f"{fuel_data.get('distance', '0.0')} 海里"],
            ["节油量", f"{fuel_data.get('saving', '0.0')} 吨"]
        ]
        fuel_table = Table(fuel_table_data, colWidths=[100, 200])
        fuel_table.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 1, colors.grey),
            ('BACKGROUND', (0,0), (-1,0), colors.lightgreen),
            ('ALIGN', (0,0), (0,-1), 'LEFT'),
            ('ALIGN', (1,0), (-1,-1), 'CENTER'),
            ('FONT SIZE', (0,0), (-1,-1), 9)
        ]))
        elements.append(fuel_table)
    else:
        elements.append(Paragraph("⚠️ 未获取到节油量计算数据", styles['Normal']))

    doc.build(elements)
    buffer.seek(0)
    return buffer

# --------------------------- Flask应用初始化 ---------------------------
def create_app():
    static_path = os.path.join(PROJECT_ROOT, "static")
    template_path = os.path.join(PROJECT_ROOT, "templates")

    # 自动创建文件夹（首次运行时）
    if not os.path.exists(static_path):
        os.makedirs(static_path)
        logger.info("首次运行，自动创建static文件夹（航线文件需手动上传）")

    if not os.path.exists(template_path):
        os.makedirs(template_path)
        # 生成基础模板（确保继承正常）
        with open(os.path.join(template_path, "base.html"), "w", encoding="utf-8") as f:
            f.write("""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{% block title %}船舶航线系统{% endblock %}</title>{% block head_css %}{% endblock %}</head><body style="margin:0; padding:20px; background:#f5f7fa; font-family:Arial,sans-serif;">{% block content %}{% endblock %}</body></html>""")

    # 初始化Flask应用
    app = Flask(
        __name__,
        static_folder=static_path,
        template_folder=template_path
    )
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
        logger.error(f"经纬度转地址失败：{str(e)}")
        return {"error": str(e)}, 500

@app.route("/login_page")
def login_page():
    return render_template("login.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form.get("username", "").strip()
        pwd = request.form.get("password", "").strip()
        if app.config["VALID_USER"].get(user) == pwd:
            logger.info(f"用户{user}登录成功")
            return redirect(url_for("login_success", username=user))
        logger.warning(f"用户{user}登录失败：密码错误")
        return "用户名或密码错误（默认：admin/123456）", 401
    return render_template("login.html")

@app.route("/login_success")
def login_success():
    username = request.args.get("username", "用户")
    logger.info(f"用户{username}进入登录成功页")
    return render_template("login_success.html", username=username)

@app.route("/route_map")
def route_map():
    start = request.args.get("start_point", "").strip()
    end = request.args.get("end_point", "").strip()
    original = request.args.get("original_speed", "").strip()
    optimized = request.args.get("optimized_speed", "").strip()
    user_dist = request.args.get("distance", "").strip()

    # 【优化】只调用一次get_preset_route，避免数据不一致
    route_points = get_preset_route(start, end) if (start and end) else read_route_data()
    # 计算航程（确保坐标点有效）
    default_dist = calculate_route_distance(route_points) if len(route_points) >= 2 else 0.0
    final_dist = user_dist if (user_dist and float(user_dist) > 0) else str(default_dist)

    # 【优化】精准判断是否使用默认航线（对比坐标点数量和前3个坐标）
    default_route_points = read_route_data()
    is_default_route = (
        len(route_points) == len(default_route_points) 
        and route_points[:3] == default_route_points[:3]  # 对比前3个坐标，避免误判
    )
    default_route_tip = "（使用默认上海-宁波航线）" if is_default_route else ""

    logger.info(f"航线加载完成：{start}→{end}，是否默认航线：{is_default_route}，航程：{final_dist}海里")
    return render_template(
        "route_map.html",
        route_points=json.dumps(route_points),  # 传递JSON格式坐标，前端可直接解析
        start_point=start,
        end_point=end,
        original_speed=original,
        optimized_speed=optimized,
        distance=final_dist,
        default_route_tip=default_route_tip
    )

@app.route("/fuel_saving")
def fuel_saving():
    start = request.args.get("start_point", "").strip() or "上海"
    end = request.args.get("end_point", "").strip() or "宁波"
    required = ["original_speed", "optimized_speed", "distance"]
    # 验证必填参数
    if not all(request.args.get(p) for p in required):
        logger.warning("节油量计算：参数不完整")
        return "参数不完整，请填写航速和航程", 400
    try:
        original = float(request.args["original_speed"])
        optimized = float(request.args["optimized_speed"])
        dist = float(request.args["distance"])
        # 验证参数合理性
        if original <= 0 or optimized <= 0 or dist <= 0:
            logger.warning(f"节油量计算：参数无效（原航速：{original}，优化航速：{optimized}，航程：{dist}）")
            return "参数错误（航速和航程必须为正数）", 400
        if optimized >= original:
            logger.warning(f"节油量计算：优化航速({optimized})不小于原航速({original})")
            return "参数错误（优化航速必须小于原航速）", 400
        # 计算节油量（公式合理，保留2位小数）
        saving = round((original - optimized) * dist * 0.8, 2)
        logger.info(f"节油量计算完成：{start}→{end}，节油量：{saving}吨")
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
        logger.warning("节油量计算：参数格式错误（非数字）")
        return "参数格式错误，请输入数字", 400

@app.route("/export_pdf")
def export_pdf():
    try:
        start = request.args.get("start_point", "").strip() or "上海"
        end = request.args.get("end_point", "").strip() or "宁波"
        route_points = get_preset_route(start, end) if (start and end) else read_route_data()
        # 准备PDF数据
        fuel_data = {
            "start": start,
            "end": end,
            "original": request.args.get("original_speed", "未填写"),
            "optimized": request.args.get("optimized_speed", "未填写"),
            "distance": request.args.get("distance", str(calculate_route_distance(route_points))),
            "saving": request.args.get("saving", "未计算")
        }
        # 生成PDF
        pdf_buffer = generate_route_report(route_points, fuel_data)
        logger.info(f"PDF导出成功：{start}→{end}")
        response = make_response(send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"航线报告_{start}-{end}_{datetime.now().strftime('%Y%m%d')}.pdf"
        ))
        response.headers['Cache-Control'] = 'no-store'
        return response
    except Exception as e:
        logger.error(f"PDF导出失败: {str(e)}")
        return f"PDF导出失败：{str(e)}", 500

if __name__ == "__main__":
    logger.info(f"应用启动：http://{app.config['HOST']}:{app.config['PORT']}")
    app.run(
        debug=app.config["DEBUG"],
        port=app.config["PORT"],
        host=app.config["HOST"]
    )
