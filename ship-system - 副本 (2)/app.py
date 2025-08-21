import os
import json
import requests
import logging
from datetime import datetime
from flask import Flask, request, render_template, redirect, url_for, make_response
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.platypus import Table
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

# --------------------------- 配置区 --------------------------- 
# 建议实际项目用 config.py 或环境变量管理
CONFIG = {
    "SECRET_KEY": "your_secret_key",  # 生产环境用安全随机值
    "DEBUG": True,
    "PORT": 5001,
    "HOST": "0.0.0.0",
    "AMAP_API_KEY": "1389a7514ce65016496e0ee1349282b7",  # 高德API Key
    "ROUTE_DATA_PATH": os.path.join("static", "route_data.json"),  # 航线数据路径
    "VALID_USER": {"admin": "123456"}  # 实际应存数据库/配置中心
}

# 日志配置（生产环境建议用 FileHandler 持久化）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),  # 终端输出
        # logging.FileHandler("app.log")  # 可选：输出到文件
    ]
)
logger = logging.getLogger(__name__)

# --------------------------- 工具函数区 --------------------------- 
def read_route_data():
    """读取航线数据（解耦文件操作）"""
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
    app.config.from_mapping(CONFIG)  # 加载配置
    return app

app = create_app()

# --------------------------- 路由定义区 --------------------------- 
@app.route("/")
def index():
    """根路由：重定向登录页"""
    logger.info("访问根路由，重定向到登录页")
    return redirect(url_for("login_page"))

@app.route("/get_location/<lng>/<lat>")
def get_location(lng, lat):
    """高德地图逆地理编码API"""
    api_url = f"https://restapi.amap.com/v3/geocode/regeo?location={lng},{lat}&key={app.config['AMAP_API_KEY']}"
    logger.info(f"发起高德API请求: {api_url}")
    
    try:
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()  # 触发HTTP错误
        result = response.json()
        
        if result.get("status") == "1":
            logger.info(f"高德API返回成功: {result.get('regeocode', {})}")
            return result
        else:
            error_msg = result.get("info", "未知错误")
            logger.warning(f"高德API调用失败: {error_msg}")
            return {"error": "API调用失败", "message": error_msg}
    
    except requests.exceptions.Timeout:
        logger.error("高德API请求超时")
        return {"error": "请求超时", "message": "连接高德地图API超时，请重试"}, 408
    except requests.exceptions.RequestException as e:
        logger.error(f"高德API请求异常: {str(e)}")
        return {"error": "请求处理失败", "message": str(e)}, 500

@app.route("/login_page")
def login_page():
    """登录页面渲染"""
    try:
        return render_template("login.html")
    except Exception as e:
        logger.error(f"登录模板加载失败: {str(e)}")
        return "登录页面加载失败，请检查templates文件夹是否存在login.html", 500

@app.route("/login", methods=["GET", "POST"])
def login():
    """登录校验逻辑"""
    if request.method == "GET":
        logger.info("访问登录页（GET）")
        return render_template("login.html")
    
    # POST 处理
    user = request.form.get("username", "").strip()
    pwd = request.form.get("password", "").strip()
    logger.info(f"收到登录请求: 用户名={user}, 密码=***")  # 密码脱敏
    
    if not user or not pwd:
        logger.warning("登录参数为空")
        return "用户名和密码不能为空", 400
    
    if app.config["VALID_USER"].get(user) == pwd:
        logger.info(f"用户 {user} 登录成功，跳转可视化页面")
        return redirect(url_for("route_map"))
    else:
        logger.warning(f"用户 {user} 登录失败（密码错误）")
        return "用户名或密码错误，请重试", 401

@app.route("/route_map")
def route_map():
    """航线地图页面"""
    try:
        return render_template("route_map.html")
    except Exception as e:
        logger.error(f"航线地图模板加载失败: {str(e)}")
        return "航线地图页面加载失败，请检查templates文件夹", 500

@app.route("/fuel_saving", methods=["GET"])
def fuel_saving():
    """节油计算器核心逻辑"""
    # 参数获取与校验
    params = ["original_speed", "optimized_speed", "distance"]
    if not all(request.args.get(param) for param in params):
        logger.warning("节油计算参数不完整")
        return "参数不完整，请填写所有字段", 400
    
    try:
        original = float(request.args["original_speed"])
        optimized = float(request.args["optimized_speed"])
        distance = float(request.args["distance"])
    except ValueError:
        logger.error("节油计算参数格式错误")
        return "参数格式错误，请输入有效的数字", 400
    
    # 业务校验
    if original <= 0 or optimized <= 0 or distance <= 0:
        logger.warning("节油计算参数为负数")
        return "参数必须为正数", 400
    if optimized >= original:
        logger.warning("优化航速未小于原航速")
        return "优化航速必须小于原航速才能节油", 400
    
    # 计算逻辑
    saving = (original - optimized) * distance * 0.8
    result = round(saving, 2)
    logger.info(f"节油计算完成: 原航速={original}, 优化航速={optimized}, 航程={distance}, 节油量={result}")
    
    return render_template(
        "fuel_result.html",
        original=original,
        optimized=optimized,
        distance=distance,
        saving=result
    )

@app.route("/export_pdf")
def export_pdf():
    """PDF导出功能（含航线数据整合）"""
    # 参数校验（从URL获取）
    params = ["original_speed", "optimized_speed", "distance", "saving"]
    if not all(request.args.get(param, type=float) for param in params):
        logger.warning("PDF导出参数不完整")
        return "请先完成节油量计算，再导出PDF报告", 400
    
    # 提取参数
    original = request.args["original_speed"]
    optimized = request.args["optimized_speed"]
    distance = request.args["distance"]
    saving = request.args["saving"]
    
    # 读取航线数据
    route_points = read_route_data()
    
    # 构建PDF响应
    response = make_response()
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = 'attachment; filename="船舶节油报告.pdf"'
    
    # PDF内容绘制
    try:
        c = canvas.Canvas(response.stream, pagesize=A4)
        width, height = A4
        styles = getSampleStyleSheet()
        
        # 标题
        c.setFont("Helvetica-Bold", 18)
        c.drawCentredString(width/2, height - 50, "船舶节油报告")
        
        # 基本信息
        y = height - 100
        for label, value in [
            ("原航速", f"{original} 节"),
            ("优化航速", f"{optimized} 节"),
            ("航程", f"{distance} 海里"),
            ("节油量", f"{saving} 吨")
        ]:
            c.setFont("Helvetica", 12)
            c.drawString(100, y, f"{label}: {value}")
            y -= 25
        
        # 航线信息
        if route_points:
            c.setFont("Helvetica-Bold", 14)
            c.drawString(100, y, "航线坐标信息:")
            y -= 30
            
            # 表格数据构造
            table_data = [["序号", "经度", "纬度"]]
            for idx, (lng, lat) in enumerate(route_points, 1):
                table_data.append([str(idx), f"{lng:.6f}", f"{lat:.6f}"])
            
            # 表格样式配置
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
            
            # 绘制表格（自动计算高度）
            table.wrapOn(c, width, height)
            table.drawOn(c, 100, y - table._height)
            y -= table._height + 20
        
        # 生成时间
        c.setFont("Helvetica-Oblique", 10)
        c.drawString(
            width - 200, 50, 
            f"报告生成时间: {datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}"
        )
        
        c.save()
        return response
    
    except Exception as e:
        logger.error(f"PDF生成失败: {str(e)}")
        return f"生成PDF报告时出错: {str(e)}", 500

# --------------------------- 启动入口 --------------------------- 
if __name__ == "__main__":
    # 打印路由映射（调试用）
    logger.info("已注册路由列表：")
    for rule in app.url_map.iter_rules():
        logger.info(f"  {rule.rule} -> {rule.endpoint}")
    
    # 启动服务
    logger.info(f"启动Flask服务: http://{app.config['HOST']}:{app.config['PORT']}")
    app.run(
        debug=app.config["DEBUG"],
        port=app.config["PORT"],
        host=app.config["HOST"]
    )