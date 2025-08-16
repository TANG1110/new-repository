print("开始执行 test.py...")
try:
    from flask import Flask
    print("Flask 导入成功")
    app = Flask(__name__)
    print("准备启动服务...")
    app.run(debug=True, port=5001)
except Exception as e:
    print("出错了：", e)