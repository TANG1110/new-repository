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
    from flask import Flask, request, render_template, redirect
    print("Flask 导入成功")
except ImportError as e:
    print("Flask 导入失败：", str(e))
    exit()

# 初始化 Flask 应用
try:
    app = Flask(__name__)
    # 确保模板文件夹正确配置（默认是当前目录下的templates）
    print(f"模板文件夹路径: {app.template_folder}")
    print("Flask 应用初始化成功")
except Exception as e:
    print("Flask 初始化失败：", str(e))
    exit()

# 根路由
@app.route('/')
def hello():
    return "Flask后端框架启动成功！"
print("根路由定义成功")

# 高德 API 路由
@app.route('/get_location/<lng>/<lat>')
def get_location(lng, lat):
    key = "1389a7514ce65016496e0ee1349282b7"  # 你的Key
    url = f"https://restapi.amap.com/v3/geocode/regeo?location={lng},{lat}&key={key}"
    print("拼接的API地址：", url)
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        result = response.json()
        print("高德API返回数据：", result)
        
        if result.get("status") == "1":
            return result
        else:
            return {"error": "API调用失败", "message": result.get("info", "未知错误")}
    
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
        return "登录页面加载失败"

@app.route('/login', methods=['POST'])
def login():
    user = request.form.get('username')
    pwd = request.form.get('password')
    print(f"收到登录请求：用户名={user}, 密码={pwd}")
    if valid_user.get(user) == pwd:
        return "登录成功！"
    else:
        return "用户名或密码错误"
print("登录路由定义成功")

# 添加航线地图页面的路由
@app.route('/route_map')
def route_map():
    try:
        return render_template('route_map.html')
    except Exception as e:
        print("航线地图模板加载失败：", str(e))
        return "航线地图页面加载失败"
print("route_map 路由定义成功")

# 启动服务
if __name__ == '__main__':
    print("\n已注册的路由列表：")
    for rule in app.url_map.iter_rules():
        print(f"  {rule.rule} -> {rule.endpoint}")
    
    PORT = 5001
    print(f"\n准备启动 Flask 服务，端口: {PORT}...")
    app.run(debug=True, port=PORT, host='0.0.0.0', use_reloader=False)
