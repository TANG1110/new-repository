import os
import json
import requests
import logging
from datetime import datetime
from flask import Flask, request, render_template, redirect, url_for, make_response
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from io import BytesIO  # 关键导入

# --------------------------- 配置区 --------------------------- 
CONFIG = {
    "SECRET_KEY": "your_secret_key",
    "DEBUG": False,
    "PORT": int(os.environ.get("PORT", 5001)),
    "HOST": "0.0.0.0",
    "AMAP_API_KEY": "1389a7514ce65016496e0ee1349282b7",
    "ROUTE_DATA_PATH": os.path.join("static", "route_data.json"),
    "VALID_USER": {"admin": "123456"}
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# --------------------------- 工具函数区 --------------------------- 
def read_route_data():
    file_path = CONFIG["ROUTE_DATA_PATH"]
    if not os.path.exists(file_path):
        logger.warning(f"航线数据文件不存在: {file_path}")
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f).get("points", [])
    except Exception as e:
        logger.error(f"读取航线数据失败: {str(e)}")
        return []

# --------------------------- Flask 应用初始化 --------------------------- 
def create_app():
    app = Flask(__name__)
    app.config.from_mapping(CONFIG)
    return app

app = create_app()

# --------------------------- 路由定义区 --------------------------- 
@app.route("/")
def index():
    return redirect(url_for("login_page"))

@app.route("/get_location/<lng>/<lat>")
def get_location(lng, lat):
    api_url = f"https://restapi.amap.com/v3/geocode/regeo?location={lng},{lat}&key={app.config['AMAP_API_KEY']}"
    try:
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()
        result = response.json()
        return result if result.get("status") == "1" else {"error": "API调用失败", "message": result.get("info", "未知错误")}
    except requests.exceptions.Timeout:
        return {"error": "请求超时", "message": "连接高德地图API超时，请重试"}, 408
    except requests.exceptions.RequestException as e:
        return {"error": "请求处理失败", "message": str(e)}, 500

@app.route("/login_page")
def login_page():
    try:
        return render_template("login.html")
    except Exception as e:
        return "登录页面加载失败，请检查templates文件夹", 500

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")
    
    user = request.form.get("username", "").strip()
    pwd = request.form.get("password", "").strip()
    
    if not user or not pwd:
        return "用户名和密码不能为空", 400
    
    return redirect(url_for("route_map")) if app.config["VALID_USER"].get(user) == pwd else ("用户名或密码错误，请重试", 401)

@app.route("/route_map")
def route_map():
    try:
        return render_template("route_map.html")
    except Exception as e:
        return "航线地图页面加载失败，请检查templates文件夹", 500

@app.route("/fuel_saving", methods=["GET"])
def fuel_saving():
    params = ["original_speed", "optimized_speed", "distance"]
    if not all(request.args.get(param) for param in params):
        return "参数不完整，请填写所有字段", 400
    
    try:
        original, optimized, distance = map(float, (request.args["original_speed"], request.args["optimized_speed"], request.args["distance"]))
    except ValueError:
        return "参数格式错误，请输入有效的数字", 400
    
    if original <= 0 or optimized <= 0 or distance <= 0 or optimized >= original:
        return "参数必须为正数且优化航速小于原航速", 400
    
    saving = round((original - optimized) * distance * 0.8, 2)
    return render_template("fuel_result.html", original=original, optimized=optimized, distance=distance, saving=saving)

@app.route("/export_pdf")
def export_pdf():
    params = ["original_speed", "optimized_speed", "distance", "saving"]
    if not all(request.args.get(param, type=float) for param in params):
        return "请先完成节油量计算，再导出PDF报告", 400
    
    original, optimized, distance, saving = map(float, (request.args["original_speed"], request.args["optimized_speed"], request.args["distance"], request.args["saving"]))
    route_points = read_route_data()
    
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    styles = getSampleStyleSheet()
    
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(width/2, height - 50, "船舶节油报告")
    
    y = height - 100
    for label, value in [("原航速", f"{original} 节"), ("优化航速", f"{optimized} 节"), ("航程", f"{distance} 海里"), ("节油量", f"{saving} 吨")]:
        c.setFont("Helvetica", 12)
        c.drawString(100, y, f"{label}: {value}")
        y -= 25
    
    if route_points:
        c.setFont("Helvetica-Bold", 14)
        c.drawString(100, y, "航线坐标信息:")
        y -= 30
        
        table_data = [["序号", "经度", "纬度"]]
        for idx, (lng, lat) in enumerate(route_points, 1):
            table_data.append([str(idx), f"{lng:.6f}", f"{lat:.6f}"])
        
        table = Table(table_data, colWidths=[60, 150, 150])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightblue),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
            ("BACKGROUND", (0, 1), (-1, -1), colors.whitesmoke),
            ("GRID", (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        w, h = table.wrapOn(c, width, height)
        table.drawOn(c, 100, y - h)
        y -= h + 20
    
    c.setFont("Helvetica-Oblique", 10)
    c.drawString(width - 200, 50, f"报告生成时间: {datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}")
    
    c.save()
    buffer.seek(0)
    
    response = make_response(buffer.read())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = 'attachment; filename="船舶节油报告.pdf"'
    return response

# --------------------------- 启动入口 --------------------------- 
if __name__ == "__main__":
    for rule in app.url_map.iter_rules():
        logger.info(f"  {rule.rule} -> {rule.endpoint}")
    
    app.run(debug=app.config["DEBUG"], port=app.config["PORT"], host=app.config["HOST"])