from flask import Flask, send_from_directory
import os

app = Flask(__name__, static_folder="static")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


@app.route("/")
def index():
    """يعرض ملف الخريطة الرئيسي index.html"""
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/<path:filename>")
def serve_file(filename):
    """يعرض أي ملف آخر موجود في مجلد المشروع (صور، ملفات إضافية...)"""
    return send_from_directory(BASE_DIR, filename)


if __name__ == "__main__":
    # Render يمرر رقم المنفذ عبر متغير البيئة PORT
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
