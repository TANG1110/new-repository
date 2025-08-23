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

# --------------------------- 配置区 --------------------------- 
API_DIR = os.path.abspath(os.path.dirname(__file__))
CONFIG = {
    "SECRET_KEY": "your_secret_key",
    "DEBUG": True,
    "PORT": int(os.environ.get("PORT", 5001)),
    "HOST": "127.0.0.1",
    "AMAP_API_KEY": "1389a7514ce65016496e0ee1349282b7",
    "ROUTE_DATA_PATH": os.path.join(API_DIR, "../static/route_data.json"),
    "PRESET_ROUTE_PATH": os.path.join(API_DIR, "../static/shanghai_ningbo_route.json"),
    "VALID_USER": {"admin": "123456"}
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
    """优先返回上海-宁波航线"""
    start = start_point.strip().lower()
    end = end_point.strip().lower()
    if start in ["上海", "shanghai"] and end in ["宁波", "ningbo"]:
        try:
            with open(CONFIG["PRESET_ROUTE_PATH"], "r", encoding="utf-8") as f:
                return json.load(f).get("points", [])
        except Exception as e:
            logger.error(f"❌ 读取上海-宁波航线失败: {str(e)}")
            return []
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

# --------------------------- PDF生成核心函数（单页A4优化） ---------------------------
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

    # 2. 强制注册中文字体
    try:
        pdfmetrics.registerFont(TTFont('SimHei', 'SimHei.ttf'))
        addMapping('SimHei', 0, 0, 'SimHei')
        addMapping('SimHei', 0, 1, 'SimHei')
        font_name = 'SimHei'
    except:
        logger.warning("⚠️ 未找到SimHei，使用默认字体")
        font_name = 'Helvetica'

    # 3. 紧凑样式配置（控制整体高度）
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name='Title_CN',
        parent=styles['Title'],
        fontName=font_name,
        fontSize=18,
        alignment=1,
        spaceAfter=8  # 标题后间距缩小
    ))
    styles.add(ParagraphStyle(
        name='Normal_CN',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=10,
        leading=12  # 行间距缩小
    ))
    styles.add(ParagraphStyle(
        name='Heading2_CN',
        parent=styles['Heading2'],
        fontName=font_name,
        fontSize=14,
        spaceBefore=6,
        spaceAfter=6  # 小标题间距缩小
    ))

    elements = []
    # 标题和时间（控制高度）
    elements.append(Paragraph("船舶航线可视化系统报告", styles['Title_CN']))
    elements.append(Paragraph(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal_CN']))
    elements.append(Spacer(1, 6))  # 缩小空白

    # 4. 航线坐标表格（核心：占满A4宽度，控制高度）
    elements.append(Paragraph("一、航线坐标信息", styles['Heading2_CN']))
    if route_points:
        # 计算表格可用高度（A4高度29.7cm - 边距 - 其他内容高度）
        table_data = [["序号", "经度", "纬度"]]  # 表头
        for idx, (lng, lat) in enumerate(route_points, 1):
            table_data.append([str(idx), f"{lng:.6f}", f"{lat:.6f}"])
        
        # 计算表格宽度（A4宽度21cm - 两边距1.6cm）
        table_width = 21*cm - 1.6*cm  # 约19.4cm
        col_widths = [table_width*0.15, table_width*0.425, table_width*0.425]  # 序号列窄，经纬度列宽
        
        # 计算行高（确保所有内容在一页内）
        max_rows_per_page = len(table_data)
        row_height = (24*cm) / max_rows_per_page  # 可用高度分配给所有行
        
        # 创建表格
        route_table = Table(table_data, colWidths=col_widths, rowHeights=row_height)
        route_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), font_name),
            ('FONTSIZE', (0, 0), (-1, -1), 9),  # 表格字体统一缩小
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('LEADING', (0, 0), (-1, -1), 8)  # 紧凑行间距
        ]))
        elements.append(route_table)
    else:
        elements.append(Paragraph("⚠️ 未获取到航线坐标数据", styles['Normal_CN']))
    elements.append(Spacer(1, 6))

    # 5. 节油量表格（紧凑设计）
    elements.append(Paragraph("二、节油量计算结果", styles['Heading2_CN']))
    if fuel_data:
        fuel_table_data = [
            ["参数", "数值"],
            ["起点", fuel_data.get('start', '未填写')],
            ["终点", fuel_data.get('end', '未填写')],
            ["原航速", f"{fuel_data.get('original')} 节"],
            ["优化航速", f"{fuel_data.get('optimized')} 节"],
            ["航程", f"{fuel_data.get('distance')} 海里"],
            ["节油量", f"{fuel_data.get('saving')} 吨"]
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
        elements.append(Paragraph("⚠️ 未获取到节油量计算数据", styles['Normal_CN']))

    # 构建PDF（确保单页）
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
        # 默认航线
        with open(CONFIG["ROUTE_DATA_PATH"], "w", encoding="utf-8") as f:
            json.dump({"points": [[121.487899, 31.249162], [121.506302, 31.238938]]}, f, indent=2)
        # 上海-宁波航线
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
        with open(CONFIG["PRESET_ROUTE_PATH"], "w", encoding="utf-8") as f:
            json.dump(sh_nb_route, f, indent=2)

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
        return redirect(url_for("login_success", username=user))
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
        # 获取上海-宁波航线坐标
        start = request.args.get("start_point", "").strip()
        end = request.args.get("end_point", "").strip()
        route_points = get_preset_route(start, end)
        if not route_points:
            with open(CONFIG["PRESET_ROUTE_PATH"], "r", encoding="utf-8") as f:
                route_points = json.load(f).get("points", [])

        # 节油量数据
        fuel_data = {
            "start": start or "上海",
            "end": end or "宁波",
            "original": request.args.get("original_speed", "未填写"),
            "optimized": request.args.get("optimized_speed", "未填写"),
            "distance": request.args.get("distance", str(calculate_route_distance(route_points))),
            "saving": request.args.get("saving", "未计算")
        }

        # 生成单页PDF
        pdf_buffer = generate_route_report(route_points, fuel_data)

        # 返回下载
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
    