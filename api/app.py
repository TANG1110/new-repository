from reportlab.platypus import SimpleDocTemplate, Paragraph, Flowable  # 关键：导入 Flowable
from reportlab.lib.styles import getSampleStyleSheet
from io import BytesIO
import logging

def generate_route_report(route_points, fuel_data):
    # 构建PDF的 buffer
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize="A4")
    styles = getSampleStyleSheet()
    elements = []  # 后续填充内容

    try:
        # 【原有逻辑】这里写正常生成PDF的代码，比如添加表格、标题等
        # 示例：假设下面是你原本构造 elements 的逻辑
        elements.append(Paragraph("航线报告标题", styles["Heading1"]))
        
        doc.build(elements)
        buffer.seek(0)
        return buffer
    
    except Exception as e:
        logging.error(f"❌ PDF构建失败: {str(e)}")
        
        # 错误处理：构造简易错误PDF
        error_buffer = BytesIO()
        error_doc = SimpleDocTemplate(error_buffer, pagesize="A4")
        error_styles = getSampleStyleSheet()
        
        # 关键修复：显式标注为 Flowable 类型
        error_elements: list[Flowable] = [
            Paragraph(f"PDF生成失败: {str(e)}", error_styles["Normal"])
        ]
        
        error_doc.build(error_elements)
        error_buffer.seek(0)
        return error_buffer