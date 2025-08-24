import os
import json
import requests
import logging
import math
from io import BytesIO
from datetime import datetime
from flask import Flask, request, render_template, redirect, url_for, make_response, send_file
from flask_cors import CORS

# PDF生成相关库
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import cm

# --------------------------- 1. 全航线统一配置（无特殊航线） --------------------------- 
API_DIR = os.path.abspath(os.path.dirname(__file__))

# 所有预设航线统一配置：key=（起点，终点），value=文件名+坐标点
ALL_PRESET_ROUTES = {
    ("上海", "宁波"): {
        "filename": "shanghai_ningbo.json",
        "points": [
            [121.582812, 31.372057], [121.642376, 31.372274], [121.719159, 31.329024],
            [121.808468, 31.277377], [121.862846, 31.266428], [122.037651, 31.251066],
            [122.101726, 31.06938],  [122.201797, 30.629212], [122.11298,  30.442215],
            [121.89094,  30.425198], [121.819322, 30.269414], [121.69957,  30.164341],
            [121.854434, 29.957196], [121.854434, 29.957196], [121.910951, 29.954561],
            [121.952784, 29.977126], [122.02619,  29.925834], [122.069602, 29.911468],
            [122.168266, 29.929254], [122.176948, 29.897783], [122.150901, 29.866987],
            [122.02136,  29.822932]
        ]
    },
    ("宁波", "上海"): {
        "filename": "ningbo_shanghai.json",
        "points": [
            [122.02136,  29.822932], [122.150901, 29.866987], [122.176948, 29.897783],
            [122.168266, 29.929254], [122.069602, 29.911468], [122.02619,  29.925834],
            [121.952784, 29.977126], [121.910951, 29.954561], [121.854434, 29.957196],
            [121.854434, 29.957196], [121.69957,  30.164341], [121.819322, 30.269414],
            [121.89094,  30.425198], [122.11298,  30.442215], [122.201797, 30.629212],
            [122.101726, 31.06938],  [122.037651, 31.251066], [121.862846, 31.266428],
            [121.808468, 31.277377], [121.719159, 31.329024], [121.642376, 31.372274],
            [121.582812, 31.372057]
        ]
    },
    ("广州", "深圳"): {
        "filename": "guangzhou_shenzhen.json",
        "points": [[113.264434, 23.129162], [113.548813, 22.906414], [114.057868, 22.543096]]
    },
    ("深圳", "广州"): {
        "filename": "shenzhen_guangzhou.json",
        "points": [[114.057868, 22.543096], [113.548813, 22.906414], [113.264434, 23.129162]]
    },
    ("青岛", "大连"): {
        "filename": "qingdao_dalian.json",
        "points": [[120.384447, 36.067121], [121.436711, 35.075372], [122.116368, 38.914052]]
    },
    ("大连", "青岛"): {
        "filename": "dalian_qingdao.json",
        "points": [[122.116368, 38.914052], [121.436711, 35.075372], [120.384447, 36.067121]]
    },
    ("天津", "青岛"): {
        "filename": "tianjin_qingdao.json",
        "points": [[117.200983, 39.084158], [118.66471, 38.042309], [120.384447, 36.067121]]
    },
    ("青岛", "天津"): {
        "filename": "qingdao_tianjin.json",
        "points": [[120.384447, 36.067121], [118.66471, 38.042309], [117.200983, 39.084158]]
    },
    ("厦门", "香港"): {
        "filename": "xiamen_hongkong.json",
        "points": [[118.081754, 24.479838], [118.941765, 24.518043], [114.15769, 22.284419]]
    },
    ("香港", "厦门"): {
        "filename": "hongkong_xiamen.json",
        "points": [[114.15769, 22.284419], [118.941765, 24.518043], [118.081754, 24.479838]]
    }
}

# 系统配置（从ALL_PRESET_ROUTES提取文件名映射，避免重复定义）
CONFIG = {
    "SECRET_KEY": "your_secret_key",
    "DEBUG": True,
    "PORT": int(os.environ.get("PORT", 5001)),
    "HOST": "127.0.0.1",
    "AMAP_API_KEY": "1389a7514ce65016496e0ee1349282b7",
    "ROUTE_DATA_PATH": os.path.join(API_DIR, "../static/route_data.json"),
    "PRESET_ROUTE_FILES": {k: v["filename"] for k, v in ALL_PRESET_ROUTES.items()},  # 自动提取文件名
    "VALID_USER": {"admin": "123456"}
}

# 中文到英文地点映射
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

# --------------------------- 2. 全航线通用工具函数（无特殊分支） --------------------------- 
def read_route_data():
    """读取空默认航线（通用）"""
    file_path = CONFIG["ROUTE_DATA_PATH"]
    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump({"points": []}, f, indent=2)
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f).get("points", [])
    except Exception as e:
        logger.error(f"❌ 读取默认航线失败: {str(e)}")
        return []

def load_route_file(filename: str) -> list:
    """加载航线文件（所有航线通用，无特殊判断）"""
    file_path = os.path.join(API_DIR, f"../static/{filename}")
    if not os.path.exists(file_path):
        logger.warning(f"⚠️ 航线文件不存在: {file_path}")
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f).get("points", [])
    except Exception as e:
        logger.error(f"❌ 读取航线文件失败 {filename}: {str(e)}")
        return []

def get_preset_route(start_point: str, end_point: str) -> list:
    """航线匹配（所有航线统一逻辑：精确匹配→部分匹配）"""
    if not start_point or not end_point:
        return []
        
    start = start_point.strip().lower()
    end = end_point.strip().lower()
    
    # 1. 精确匹配（中文/英文全匹配）
    for (s, e), filename in CONFIG["PRESET_ROUTE_FILES"].items():
        if (start == s.lower() or start == LOCATION_TRANSLATIONS.get(s, "").lower()) and \
           (end == e.lower() or end == LOCATION_TRANSLATIONS.get(e, "").lower()):
            return load_route_file(filename)
    
    # 2. 部分匹配（如输入"sh"→"Shanghai"）
    for (s, e), filename in CONFIG["PRESET_ROUTE_FILES"].items():
        if (start in s.lower() or start in LOCATION_TRANSLATIONS.get(s, "").lower()) and \
           (end in e.lower() or end in LOCATION_TRANSLATIONS.get(e, "").lower()):
            return load_route_file(filename)
    
    return []

def calculate_route_distance(points: list) -> float:
    """计算航程（海里，所有航线通用公式）"""
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
    """中文转英文（通用）"""
    if not chinese_name:
        return "Not Specified"
    translated = LOCATION_TRANSLATIONS.get(chinese_name.strip(), None)
    if translated:
        return translated
    for cn, en in LOCATION_TRANSLATIONS.items():
        if cn in chinese_name:
            return en
    return chinese_name

# --------------------------- 3. PDF生成（全航线通用模板） ---------------------------
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

    # 航线坐标表格（所有航线统一格式）
    elements.append(Paragraph("1. Route Coordinate Information", styles['Heading2_EN']))
    if route_points:
        table_data = [["No.", "Longitude", "Latitude"]]
        for idx, (lng, lat) in enumerate(route_points, 1):
            table_data.append([str(idx), f"{lng:.6f}", f"{lat:.6f}"])
        
        table_width = 21*cm - 1.6*cm
        col_widths = [table_width*0.15, table_width*0.425, table_width*0.425]
        row_height = (24*cm) / len(table_data)
        
        route_table = Table(table_data, colWidths=col_widths, rowHeights=row_height)
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

    # 节油量表格（所有航线统一格式）
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

# --------------------------- 4. Flask应用初始化（全航线统一文件生成） --------------------------- 
def create_app():
    root_path = os.path.dirname(API_DIR)
    static_path = os.path.join(root_path, "static")
    template_path = os.path.join(root_path, "templates")

    # 创建静态目录
    if not os.path.exists(static_path):
        os.makedirs(static_path)
        # 生成空默认航线
        with open(CONFIG["ROUTE_DATA_PATH"], "w", encoding="utf-8") as f:
            json.dump({"points": []}, f, indent=2)
        
        # 批量生成所有航线文件（10条航线统一循环，无特殊处理）
        for (start, end), route_info in ALL_PRESET_ROUTES.items():
            file_path = os.path.join(static_path, route_info["filename"])
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump({"points": route_info["points"]}, f, indent=2)

    # 创建模板目录
    if not os.path.exists(template_path):
        os.makedirs(template_path)
        # 创建基础模板
        with open(os.path.join(template_path, "base.html"), "w", encoding="utf-8") as f:
            f.write("""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>{% block title %}船舶系统{% endblock %}</title>{% block head_css %}{% endblock %}</head><body style="margin:0; padding:20px; background:#f5f7fa; font-family:Arial,sans-serif;">{% block content %}{% endblock %}</body></html>""")

        # 创建登录模板
        with open(os.path.join(template_path, "login.html"), "w", encoding="utf-8") as f:
            f.write("""{% extends "base.html" %}
{% block title %}船舶航线系统 - 登录{% endblock %}
{% block head_css %}
<style>
    .login-container { max-width: 400px; margin: 50px auto; padding: 20px; background: white; border-radius: 8px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }
    .login-title { text-align: center; color: #0033FF; margin-bottom: 30px; }
    .form-group { margin-bottom: 20px; }
    label { display: block; margin-bottom: 8px; color: #333; }
    input { width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box; }
    button { width: 100%; padding: 10px; background: #0033FF; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; }
    button:hover { background: #0021aa; }
    .hint { text-align: center; margin-top: 15px; color: #666; font-size: 14px; }
</style>
{% endblock %}
{% block content %}
<div class="login-container">
    <h2 class="login-title">船舶航线与节油计算系统</h2>
    <form action="{{ url_for('login') }}" method="post">
        <div class="form-group">
            <label for="username">用户名</label>
            <input type="text" id="username" name="username" required>
        </div>
        <div class="form-group">
            <label for="password">密码</label>
            <input type="password" id="password" name="password" required>
        </div>
        <button type="submit">登录</button>
        <p class="hint">默认账号: admin | 密码: 123456</p>
    </form>
</div>
{% endblock %}""")

        # 创建航线地图模板
        with open(os.path.join(template_path, "route_map.html"), "w", encoding="utf-8") as f:
            f.write("""{% extends "base.html" %}
{% block title %}船舶航线与节油计算系统{% endblock %}
{% block head_css %}
<style>
    .page-title { text-align: center; color: #0033FF; font-size: 26px; margin: 20px 0; font-weight: bold; }
    .param-container { width: 90%; max-width: 1200px; margin: 20px auto; padding: 20px; background: white; border: 1px solid #e5e9f2; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }
    .calc-form { display: flex; gap: 20px; flex-wrap: wrap; margin-top: 15px; }
    .form-group { flex: 1; min-width: 180px; }
    input { width: 100%; padding: 8px; margin-top: 5px; border: 1px solid #e5e9f2; border-radius: 4px; }
    button { padding: 8px 20px; background: #0033FF; color: white; border: none; border-radius: 4px; cursor: pointer; margin-top: 23px; transition: background 0.3s; }
    button:hover { background: #0021aa; }
    .map-wrapper { width: 90%; max-width: 1200px; margin: 0 auto; position: relative; }
    #map { width: 100%; height: 500px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
    .info-text { color: #666; font-size: 14px; margin-top: 5px; font-style: italic; }
    .map-tip { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); z-index: 10; padding: 20px 30px; background: white; border-radius: 8px; box-shadow: 0 2px 15px rgba(0,0,0,0.1); text-align: center; color: #666; font-size: 16px; }
    .route-info { text-align: center; margin: 10px 0; color: #0033FF; font-size: 14px; }
</style>
<script src="https://webapi.amap.com/maps?v=2.0&key=1389a7514ce65016496e0ee1349282b7"></script>
{% endblock %}
{% block content %}
<h1 class="page-title">船舶航线与节油计算系统</h1>

<!-- 参数输入区域 -->
<div class="param-container">
    <h3>航线参数设置</h3>
    <form action="{{ url_for('route_map') }}" method="get" class="calc-form">
        <div class="form-group">
            <label>起点</label>
            <input type="text" name="start_point" value="{{ start_point if start_point else '' }}" placeholder="例如：上海" required>
        </div>
        <div class="form-group">
            <label>终点</label>
            <input type="text" name="end_point" value="{{ end_point if end_point else '' }}" placeholder="例如：宁波" required>
        </div>
        <div class="form-group">
            <label>原航速（节）</label>
            <input type="number" name="original_speed" step="0.1" value="{{ original_speed if original_speed else '' }}" placeholder="例如：15.5">
        </div>
        <div class="form-group">
            <label>优化航速（节）</label>
            <input type="number" name="optimized_speed" step="0.1" value="{{ optimized_speed if optimized_speed else '' }}" placeholder="例如：12.3">
        </div>
        <div class="form-group">
            <label>航程（海里）</label>
            <input type="number" name="distance" step="0.1" value="{{ distance if distance else '' }}" placeholder="自动计算">
            <div class="info-text">所有预设航线（如上海-宁波）留空将自动计算航程</div>
        </div>
        <div>
            <button type="submit">加载航线</button>
        </div>
    </form>
</div>

<!-- 节油量计算表单 -->
<div class="param-container">
    <h3>节油量计算</h3>
    <form action="{{ url_for('fuel_saving') }}" method="get" class="calc-form">
        <input type="hidden" name="start_point" value="{{ start_point if start_point else '' }}">
        <input type="hidden" name="end_point" value="{{ end_point if end_point else '' }}">
        <div class="form-group">
            <label>原航速（节）</label>
            <input type="number" name="original_speed" step="0.1" required value="{{ original_speed if original_speed else '' }}" placeholder="例如：15.5">
        </div>
        <div class="form-group">
            <label>优化航速（节）</label>
            <input type="number" name="optimized_speed" step="0.1" required value="{{ optimized_speed if optimized_speed else '' }}" placeholder="例如：12.3">
        </div>
        <div class="form-group">
            <label>航程（海里）</label>
            <input type="number" name="distance" step="0.1" value="{{ distance if distance else '' }}" placeholder="自动计算">
            <div class="info-text">留空将自动计算</div>
        </div>
        <div>
            <button type="submit">计算节油量</button>
        </div>
    </form>
</div>

<!-- 地图容器 -->
<div class="map-wrapper">
    {% if not start_point or not end_point %}
        <div class="map-tip">请输入起点和终点，点击"加载航线"按钮或回车显示航线</div>
    {% elif not route_exists %}
        <div class="map-tip">未找到匹配的航线，请检查起点和终点是否正确</div>
    {% else %}
        <div class="route-info">当前航线：{{ start_point }} → {{ end_point }}（共{{ route_points|length }}个坐标点，航程：{{ distance }}海里）</div>
    {% endif %}
    <div id="map"></div>
</div>

<script>
    window.onload = function () {
        try {
            // 解析后端传递的航线数据
            let routePoints = [];
            const rawData = '{{ route_points|tojson|safe }}';
            if (rawData && rawData !== 'null' && rawData !== 'undefined') {
                routePoints = JSON.parse(rawData);
                if (!Array.isArray(routePoints)) routePoints = [];
            }

            // 初始化地图
            const map = new AMap.Map('map', {
                center: [121.487899, 31.249162], // 上海附近中心点，适配上海-宁波航线
                zoom: 9,
                resizeEnable: true
            });

            // 绘制航线
            if (routePoints.length >= 2) {
                const polyline = new AMap.Polyline({
                    path: routePoints,
                    strokeColor: '#0033FF',
                    strokeWeight: 5,
                    strokeOpacity: 0.8,
                    strokeDasharray: [10, 5]
                });
                polyline.setMap(map);
                map.setFitView([polyline]); // 自动适配航线视野

                // 起点标记（红色）
                new AMap.Marker({
                    position: routePoints[0],
                    title: '起点',
                    icon: new AMap.Icon({size: new AMap.Size(30, 30), image: 'https://webapi.amap.com/theme/v1.3/markers/n/mark_r.png'}),
                    anchor: 'bottom-center'
                }).setMap(map);

                // 终点标记（蓝色）
                new AMap.Marker({
                    position: routePoints[routePoints.length - 1],
                    title: '终点',
                    icon: new AMap.Icon({size: new AMap.Size(30, 30), image: 'https://webapi.amap.com/theme/v1.3/markers/n/mark_b.png'}),
                    anchor: 'bottom-center'
                }).setMap(map);
            }
        } catch (error) {
            console.error("地图加载失败:", error);
            document.querySelector('.map-tip').innerText = "地图加载失败，请刷新页面重试";
        }
    };
</script>
{% endblock %}""")

        # 创建节油量结果模板
        with open(os.path.join(template_path, "fuel_result.html"), "w", encoding="utf-8") as f:
            f.write("""{% extends "base.html" %}
{% block title %}节油量计算结果{% endblock %}
{% block head_css %}
<style>
    .result-container { width: 90%; max-width: 800px; margin: 30px auto; padding: 20px; background: white; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
    .result-title { text-align: center; color: #0033FF; margin-bottom: 20px; }
    .result-table { width: 100%; border-collapse: collapse; margin: 20px 0; }
    .result-table th, .result-table td { border: 1px solid #e5e9f2; padding: 12px; text-align: left; }
    .result-table th { background-color: #f5f7fa; color: #333; }
    .highlight { color: #0033FF; font-weight: bold; }
    .actions { text-align: center; margin-top: 30px; }
    .btn { display: inline-block; padding: 10px 20px; background: #0033FF; color: white; text-decoration: none; border-radius: 4px; margin: 0 10px; }
    .btn:hover { background: #0021aa; }
    .back-btn { background: #666; }
    .back-btn:hover { background: #444; }
</style>
{% endblock %}
{% block content %}
<div class="result-container">
    <h2 class="result-title">节油量计算结果</h2>
    
    <table class="result-table">
        <tr>
            <th>航线</th>
            <td>{{ start_point }} → {{ end_point }}</td>
        </tr>
        <tr>
            <th>原航速</th>
            <td>{{ original }} 节</td>
        </tr>
        <tr>
            <th>优化航速</th>
            <td>{{ optimized }} 节</td>
        </tr>
        <tr>
            <th>航程</th>
            <td>{{ distance }} 海里</td>
        </tr>
        <tr>
            <th>节油量</th>
            <td class="highlight">{{ saving }} 吨</td>
        </tr>
    </table>
    
    <div class="actions">
        <a href="{{ url_for('export_pdf', start_point=start_point, end_point=end_point, original_speed=original, optimized_speed=optimized, distance=distance, saving=saving) }}" class="btn">导出PDF报告</a>
        <a href="{{ url_for('route_map', start_point=start_point, end_point=end_point, original_speed=original, optimized_speed=optimized, distance=distance) }}" class="btn back-btn">返回修改参数</a>
    </div>
</div>
{% endblock %}""")

        # 创建评委页面模板
        with open(os.path.join(template_path, "judge_easter_egg.html"), "w", encoding="utf-8") as f:
            f.write("""{% extends "base.html" %}
{% block title %}评委专页{% endblock %}
{% block head_css %}
<style>
    .team-container { max-width: 800px; margin: 30px auto; padding: 20px; background: white; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
    .team-title { color: #0033FF; text-align: center; margin-bottom: 30px; }
    .info-section { margin-bottom: 25px; }
    .info-section h3 { color: #333; border-bottom: 1px solid #e5e9f2; padding-bottom: 8px; margin-bottom: 15px; }
    .member-list { list-style: none; padding: 0; }
    .member-list li { padding: 5px 0; border-bottom: 1px dashed #f0f0f0; }
    .tech-list { display: flex; flex-wrap: wrap; gap: 10px; }
    .tech-item { background: #f5f7fa; padding: 5px 10px; border-radius: 4px; font-size: 14px; }
    .back-link { display: block; text-align: center; margin-top: 30px; color: #0033FF; text-decoration: none; }
</style>
{% endblock %}
{% block content %}
<div class="team-container">
    <h2 class="team-title">{{ team_info.team_name }} 团队信息</h2>
    
    <div class="info-section">
        <h3>项目介绍</h3>
        <p>{{ team_info.project_intro }}</p>
    </div>
    
    <div class="info-section">
        <h3>团队成员</h3>
        <ul class="member-list">
            {% for member in team_info.members %}
            <li>{{ member }}</li>
            {% endfor %}
        </ul>
    </div>
    
    <div class="info-section">
        <h3>技术栈</h3>
        <div class="tech-list">
            {% for tech in team_info.tech_stack %}
            <span class="tech-item">{{ tech }}</span>
            {% endfor %}
        </div>
    </div>
    
    <div class="info-section">
        <h3>开发时间</h3>
        <p>{{ team_info.development_time }}</p>
    </div>
    
    <div class="info-section">
        <h3>项目成果</h3>
        <ul>
            {% for achievement in team_info.achievements %}
            <li>{{ achievement }}</li>
            {% endfor %}
        </ul>
    </div>
    
    <a href="{{ url_for('route_map') }}" class="back-link">返回系统首页</a>
</div>
{% endblock %}""")

    app = Flask(__name__, static_folder=static_path, template_folder=template_path)
    app.config.from_mapping(CONFIG)
    
    # 跨域支持（统一配置，所有航线嵌套通用）
    CORS(app, resources={r"/*": {"origins": "*"}})
    
    return app

app = create_app()

# --------------------------- 5. 路由（全航线统一逻辑，无特殊判断） --------------------------- 
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
    # 普通用户登录：默认跳转上海-宁波（仅跳转，无特殊航线逻辑）
    if app.config["VALID_USER"].get(user) == pwd:
        return redirect(url_for("route_map", start_point="上海", end_point="宁波"))
    # 评委账号
    if user == "judge" and pwd == "ship2025":
        return render_template("judge_easter_egg.html", team_info={
            "team_name": "海算云帆",
            "members": ["陈倚薇（队长/计算机组）", "刘迪瑶（计算机组）", "唐辉婷（计算机组）","吴珊（金融组）","周子煜（设计组）"],
            "project_intro": "船舶航线与节油计算系统：全航线统一管理，支持航线展示、油耗计算与PDF导出。",
            "tech_stack": ["Flask（后端框架）", "高德地图API（地图服务）", "HTML/CSS（前端界面）"],
            "development_time": "2025年8月12日-8月25日",
            "achievements": ["实现全航线统一管理", "完成航线可视化", "开发节油计算功能", "支持系统嵌套", "适配移动端访问"]
        })
    return "用户名或密码错误（正确：admin/123456）", 401

@app.route("/login_success")
def login_success():
    return redirect(url_for("route_map", start_point="上海", end_point="宁波"))

@app.route("/route_map")
def route_map():
    # 获取参数（所有航线通用参数）
    start = request.args.get("start_point", "").strip()
    end = request.args.get("end_point", "").strip()
    original = request.args.get("original_speed", "").strip()
    optimized = request.args.get("optimized_speed", "").strip()
    user_dist = request.args.get("distance", "").strip()

    # 1. 统一获取航线（无上海-宁波特殊处理）
    route_points = get_preset_route(start, end) if (start and end) else []
    
    # 2. 统一计算航程（用户输入优先，无特殊航线公式）
    default_dist = calculate_route_distance(route_points) if route_points else ""
    final_dist = user_dist if user_dist else str(default_dist) if default_dist else ""

    return render_template(
        "route_map.html",
        route_points=route_points,
        start_point=start,
        end_point=end,
        original_speed=original,
        optimized_speed=optimized,
        distance=final_dist,
        route_exists=len(route_points) > 0  # 新增：标记航线是否存在
    )

@app.route("/fuel_saving", methods=["GET"])
def fuel_saving():
    start = request.args.get("start_point", "").strip()
    end = request.args.get("end_point", "").strip()
    
    # 获取参数（所有航线通用）
    original_speed = request.args.get("original_speed", "").strip()
    optimized_speed = request.args.get("optimized_speed", "").strip()
    distance = request.args.get("distance", "").strip()
    
    # 统一逻辑：航程为空时自动计算（所有航线通用）
    if not distance and start and end:
        route_points = get_preset_route(start, end)
        if route_points:
            distance = str(calculate_route_distance(route_points))
    
    # 统一参数验证（无特殊航线例外）
    required = ["original_speed", "optimized_speed"]
    if not all(request.args.get(p) for p in required) or not distance:
        return "参数不完整，请确保填写了航速且航程已计算", 400
        
    try:
        original = float(original_speed)
        optimized = float(optimized_speed)
        dist = float(distance)
        
        if original <= 0 or optimized <= 0 or dist <= 0 or optimized >= original:
            return "参数错误（优化航速需小于原航速且均为正数）", 400
            
        # 统一节油量公式（所有航线通用）
        saving = round((original - optimized) * dist * 0.8, 2)
        
        # 统一获取航线数据（用于PDF）
        route_points = get_preset_route(start, end) if (start and end) else []
        
        return render_template(
            "fuel_result.html",
            start_point=start,
            end_point=end,
            original=original,
            optimized=optimized,
            distance=dist,
            saving=saving,
            route_points=route_points
        )
    except ValueError:
        return "参数格式错误，请输入有效的数字", 400

@app.route("/export_pdf")
def export_pdf():
    try:
        start = request.args.get("start_point", "").strip()
        end = request.args.get("end_point", "").strip()
        
        # 统一获取航线数据（所有航线通用）
        route_points = get_preset_route(start, end) if (start and end) else []
        
        # 统一组装PDF数据（无特殊航线格式）
        fuel_data = {
            "start": start or "未知起点",
            "end": end or "未知终点",
            "original": request.args.get("original_speed", "未填写"),
            "optimized": request.args.get("optimized_speed", "未填写"),
            "distance": request.args.get("distance", str(calculate_route_distance(route_points)) if route_points else "未计算"),
            "saving": request.args.get("saving", "未计算")
        }

        # 统一生成PDF（所有航线通用模板）
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
    