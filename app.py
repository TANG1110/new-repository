print("开始执行 app.py...")

# 测试 requests 导入
try:
    import requests
    print("requests 导入成功")
except ImportError as e:
    print("requests 导入失败：", str(e))
    exit()

# 测试 Flask 导入
try:
    from flask import Flask, request, render_template, redirect, url_for, make_response
    print("Flask 导入成功")
except ImportError as e:
    print("Flask 导入失败：", str(e))
    exit()

# 测试 reportlab 导入（新增）
try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib import colors
    print("reportlab 导入成功")
except ImportError as e:
    print("reportlab 导入失败：", str(e))
    print("请运行 'pip install reportlab' 安装依赖")
    exit()

# 导入JSON处理模块（新增）
import json
import os

# 初始化 Flask 应用
try:
    app = Flask(__name__)
    app.secret_key = "your_secret_key"  # 用于会话管理（生产环境需替换为安全密钥）
    print(f"模板文件夹路径: {app.template_folder}")
    print("Flask 应用初始化成功")
except Exception as e:
    print("Flask 初始化失败：", str(e))
    exit()

# 根路由 - 重定向到登录页面
@app.route('/')
def index():
    return redirect(url_for('login_page'))
print("根路由定义成功（重定向到登录页）")

# 高德 API 路由
@app.route('/get_location/<lng>/<lat>')
def get_location(lng, lat):
    key = "1389a7514ce65016496e0ee1349282b7"  # 你的高德API Key
    url = f"https://restapi.amap.com/v3/geocode/regeo?location={lng},{lat}&key={key}"
    print("拼接的API地址：", url)
    
    try:
        response = requests.get(url, timeout=10)  
        response.raise_for_status()  
        result = response.json()
        print("高德API返回数据：", result)
        
        if result.get("status") == "1":
            return result
        else:
            return {"error": "API调用失败", "message": result.get("info", "未知错误")}
    
    except requests.exceptions.Timeout:
        print("API请求超时")
        return {"error": "请求超时", "message": "连接高德地图API超时，请重试"}
    except Exception as e:
        print("API请求失败：", str(e))
        return {"error": "请求处理失败", "message": str(e)}
print("get_location 路由定义成功")

# 登录功能路由
valid_user = {"admin": "123456"}

@app.route('/login_page')
def login_page():
    try:
        return render_template('login.html')
    except Exception as e:
        print("模板加载失败：", str(e))
        return "登录页面加载失败，请检查templates文件夹是否存在login.html"

@app.route('/login', methods=['POST', 'GET'])
def login():
    user = request.form.get('username', '').strip()  
    pwd = request.form.get('password', '').strip()
    print(f"收到登录请求：用户名={user}, 密码={pwd}")
    
    if not user or not pwd:  
        return "用户名和密码不能为空"
    
    if valid_user.get(user) == pwd:
        # 登录成功后，直接跳转到可视化页面
        return redirect(url_for('route_map'))  
    else:
        return "用户名或密码错误，请重试"
print("登录路由定义成功")

# 航线地图页面的路由
@app.route('/route_map')
def route_map():
    try:
        return render_template('route_map.html')
    except Exception as e:
        print("航线地图模板加载失败：", str(e))
        return "航线地图页面加载失败，请检查templates文件夹是否存在route_map.html"
print("route_map 路由定义成功")

# 节油计算器路由 - 返回HTML页面
@app.route('/fuel_saving', methods=['GET'])
def fuel_saving():
    try:
        original_speed = request.args.get('original_speed')
        optimized_speed = request.args.get('optimized_speed')
        distance = request.args.get('distance')
        
        if not all([original_speed, optimized_speed, distance]):
            return "参数不完整，请填写所有字段", 400
        
        original_speed = float(original_speed)
        optimized_speed = float(optimized_speed)
        distance = float(distance)
        
        if original_speed <= 0 or optimized_speed <= 0 or distance <= 0:
            return "参数必须为正数", 400
            
        if optimized_speed >= original_speed:
            return "优化航速必须小于原航速才能节油", 400
        
        saving = (original_speed - optimized_speed) * distance * 0.8
        result = round(saving, 2)
        
        print(f"节油量计算：原航速={original_speed}, 优化航速={optimized_speed}, 航程={distance}, 结果={result}吨")
        
        return render_template('fuel_result.html', 
                             original=original_speed,
                             optimized=optimized_speed,
                             distance=distance,
                             saving=result)
    
    except ValueError:
        print("参数格式错误")
        return "参数格式错误，请输入有效的数字", 400
    except Exception as e:
        print("计算过程出错：", str(e))
        return f"服务器错误：{str(e)}", 500
print("fuel_saving 路由定义成功")

# 新增：PDF导出功能路由
@app.route('/export_pdf')
def export_pdf():
    try:
        # 获取节油量计算参数
        original_speed = request.args.get('original_speed', type=float)
        optimized_speed = request.args.get('optimized_speed', type=float)
        distance = request.args.get('distance', type=float)
        saving = request.args.get('saving', type=float)
        
        # 参数校验
        if None in [original_speed, optimized_speed, distance, saving]:
            return "请先完成节油量计算，再导出PDF报告", 400
        
        # 读取航线数据
        route_points = []
        route_file = os.path.join('static', 'route_data.json')
        if os.path.exists(route_file):
            try:
                with open(route_file, 'r', encoding='utf-8') as f:
                    route_data = json.load(f)
                    route_points = route_data.get('points', [])
            except Exception as e:
                print(f"读取航线数据出错: {str(e)}")
        
        # 创建PDF响应
        response = make_response()
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = 'attachment; filename="船舶节油报告.pdf"'
        
        # 创建PDF内容
        c = canvas.Canvas(response.stream, pagesize=A4)
        width, height = A4  # 获取A4纸尺寸
        
        # 标题
        c.setFont("Helvetica-Bold", 16)
        c.drawCentredString(width/2, height - 50, "船舶节油报告")
        
        # 基本信息
        c.setFont("Helvetica", 12)
        y_position = height - 100
        
        c.drawString(100, y_position, f"原航速: {original_speed} 节")
        y_position -= 25
        
        c.drawString(100, y_position, f"优化航速: {optimized_speed} 节")
        y_position -= 25
        
        c.drawString(100, y_position, f"航程: {distance} 海里")
        y_position -= 25
        
        c.drawString(100, y_position, f"节油量: {saving} 吨")
        y_position -= 40
        
        # 航线信息
        if route_points:
            c.setFont("Helvetica-Bold", 14)
            c.drawString(100, y_position, "航线信息:")
            y_position -= 30
            
            # 准备表格数据
            table_data = [["序号", "经度", "纬度"]]
            for idx, point in enumerate(route_points, 1):
                lng, lat = point
                table_data.append([str(idx), f"{lng:.6f}", f"{lat:.6f}"])
            
            # 创建表格
            table = Table(table_data, colWidths=[60, 150, 150])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            # 绘制表格
            table_height = len(table_data) * 25
            table.drawOn(c, 100, y_position - table_height)
            y_position -= table_height + 20
        
        # 添加报告生成时间
        from datetime import datetime
        current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")
        c.setFont("Helvetica-Oblique", 10)
        c.drawString(width - 200, 50, f"报告生成时间: {current_time}")
        
        # 保存PDF
        c.save()
        
        return response
        
    except Exception as e:
        print(f"PDF生成失败: {str(e)}")
        return f"生成PDF报告时出错: {str(e)}", 500
print("export_pdf 路由定义成功")

# 启动服务
if __name__ == '__main__':
    print("\n已注册的路由列表：")
    for rule in app.url_map.iter_rules():
        print(f"  {rule.rule} -> {rule.endpoint}")
    
    PORT = 5001
    print(f"\n准备启动 Flask 服务，端口: {PORT}...")
    app.run(debug=True, port=PORT, host='0.0.0.0')
