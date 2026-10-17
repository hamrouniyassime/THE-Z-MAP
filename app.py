"""
THE Z MAPS — سيرفر خفيف (Flask) يعرض الخريطة ويوفّر تحليلاً ذكياً للمسارات
عبر نفس محرّك الذكاء الاصطناعي المستخدم في THE Z AI/AGENT (Agnes 3.0 Flash).

- المفتاح الحقيقي يبقى هنا فقط على السيرفر (لا يظهر أبداً في المتصفح).
- الواجهة (index.html) تحسب المسارات البديلة عبر OSRM المجاني، ثم ترسلها
  لهذا السيرفر عبر /api/ai-directions، والذكاء الاصطناعي يختار الأفضل
  ويكتب شرحاً طبيعياً بالعربية لكل خطوة، يُقرأ لاحقاً بصوت عربي في المتصفح.
"""

from flask import Flask, send_from_directory, request, jsonify
import os
import json
import httpx

app = Flask(__name__, static_folder="static")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── إعدادات محرّك الذكاء الاصطناعي (Agnes 3.0 Flash) ──────────────────────
# المفتاح يُقرأ أولاً من متغير بيئة AGNES_API_KEY (الأفضل أمنياً على Render:
# Settings → Environment)، وإن لم يوجد يُستخدم نفس المفتاح الافتراضي
# المستخدم في THE Z AI/AGENT كقيمة احتياطية.
AGNES_API_KEY = os.getenv(
    "AGNES_API_KEY",
    "sk-HWG2Z3tu0mS1hM7wSJjVohPdyBoaHmQ6VYKF5MaeOvInUXqY",
).strip()
AGNES_CHAT_URL = "https://apihub.agnes-ai.com/v1/chat/completions"
AGNES_TEXT_MODEL = "agnes-3.0-flash"


@app.route("/")
def index():
    """يعرض ملف الخريطة الرئيسي index.html"""
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/<path:filename>")
def serve_file(filename):
    """يعرض أي ملف آخر موجود في مجلد المشروع (صور، ملفات إضافية...)"""
    return send_from_directory(BASE_DIR, filename)


# ── نظام الذكاء الاصطناعي لتحليل المسارات ─────────────────────────────────
_ROUTE_AI_SYSTEM_PROMPT = """أنت مساعد ملاحة ذكي داخل تطبيق خرائط اسمه "THE Z MAPS".
ستستلم عدة مسارات بديلة (من محرك توجيه حقيقي) بين نقطة بداية ووجهة، كل مسار
فيه: المسافة بالمتر، الزمن المقدّر بالثواني، وقائمة الخطوات (مناورات القيادة).

مهمتك:
1. قيّم المسارات المُعطاة واختر الأفضل عملياً (وليس بالضرورة الأقصر زمنياً
   فقط — خذ بعين الاعتبار: عدد المناورات/الانعطافات الحادة، الوضوح، وهل
   المسار منطقي عملياً لوسيلة التنقل المحددة).
2. اكتب وصفاً طبيعياً وواضحاً بالعربية الفصحى السهلة لكل خطوة من خطوات
   المسار الذي اخترته، كأنك مرشد صوتي في سيارة: جمل قصيرة، مباشرة، تبدأ
   بالفعل (مثل: "انعطف يميناً نحو شارع كذا" أو "تابع السير مسافة كذا").
3. أعد **فقط** كائن JSON صالح بالشكل التالي، بدون أي نص قبله أو بعده:

{
  "chosen_route_index": 0,
  "reason_ar": "سبب مختصر (جملة واحدة) لاختيار هذا المسار تحديداً",
  "steps_ar": ["وصف الخطوة الأولى بالعربية", "وصف الخطوة الثانية", "..."],
  "summary_ar": "ملخص عام قصير وودود عن الرحلة (جملة أو جملتين)"
}

مهم جداً: لا تكتب أي شرح أو markdown خارج كائن الـJSON. أعد الـJSON فقط.
"""


def _build_routes_summary(routes_payload, travel_mode):
    """يبني نصاً مختصراً يصف كل مسار بديل للنموذج (مسافة/زمن/أهم المناورات)."""
    mode_ar = {"driving": "سيارة", "foot": "مشي", "bike": "دراجة"}.get(
        travel_mode, "سيارة"
    )
    lines = [f"وسيلة التنقل: {mode_ar}", ""]
    for i, r in enumerate(routes_payload):
        dist_km = round((r.get("distance") or 0) / 1000, 2)
        dur_min = round((r.get("duration") or 0) / 60, 1)
        steps = r.get("steps") or []
        lines.append(f"المسار رقم {i}: المسافة {dist_km} كم، الزمن التقديري {dur_min} دقيقة، عدد الخطوات {len(steps)}")
        for j, s in enumerate(steps[:40]):  # سقف معقول لتفادي نص ضخم جداً
            name = (s.get("name") or "").strip() or "طريق غير مسمى"
            maneuver = s.get("maneuver") or {}
            mtype = maneuver.get("type") or ""
            mmod = maneuver.get("modifier") or ""
            dist_m = round(s.get("distance") or 0)
            lines.append(f"  - خطوة {j}: نوع={mtype} اتجاه={mmod} شارع={name} مسافة={dist_m}م")
        lines.append("")
    return "\n".join(lines)


@app.route("/api/ai-directions", methods=["POST"])
def ai_directions():
    """
    يستقبل عدة مسارات بديلة من OSRM (محسوبة في الواجهة)، ويرسلها للذكاء
    الاصطناعي ليختار الأفضل ويكتب شرحاً طبيعياً بالعربية لكل خطوة.

    body متوقع:
    {
      "routes": [ { "distance": ..., "duration": ..., "steps": [...] }, ... ],
      "mode": "driving" | "foot" | "bike"
    }
    """
    try:
        data = request.get_json(force=True, silent=True) or {}
        routes_payload = data.get("routes") or []
        travel_mode = data.get("mode") or "driving"

        if not routes_payload:
            return jsonify({"ok": False, "error": "لا توجد مسارات لتحليلها"}), 400

        routes_summary = _build_routes_summary(routes_payload, travel_mode)

        body = {
            "model": AGNES_TEXT_MODEL,
            "messages": [
                {"role": "system", "content": _ROUTE_AI_SYSTEM_PROMPT},
                {"role": "user", "content": routes_summary},
            ],
            "max_tokens": 4000,
            "temperature": 0.4,
            "stream": False,
        }

        with httpx.Client(timeout=45) as client:
            resp = client.post(
                AGNES_CHAT_URL,
                headers={
                    "Authorization": f"Bearer {AGNES_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=body,
            )

        if resp.status_code >= 400:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": f"خطأ من خدمة الذكاء الاصطناعي ({resp.status_code})",
                    }
                ),
                502,
            )

        raw = resp.json()
        content = (
            ((raw.get("choices") or [{}])[0].get("message") or {}).get("content")
            or ""
        ).strip()

        # النموذج مطالب بإرجاع JSON خام، لكن نتعامل باحتياط مع أي نص إضافي
        # محتمل (مثل أسوار ```json ... ```) قبل أو بعد الكائن الفعلي.
        parsed = _extract_json_object(content)
        if parsed is None:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "تعذّر فهم رد الذكاء الاصطناعي",
                        "raw": content[:500],
                    }
                ),
                502,
            )

        return jsonify({"ok": True, "result": parsed})

    except httpx.TimeoutException:
        return jsonify({"ok": False, "error": "انتهت مهلة الاتصال بخدمة الذكاء الاصطناعي"}), 504
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"خطأ غير متوقع: {e}"}), 500


def _extract_json_object(text: str):
    """يحاول استخراج أول كائن JSON صالح من نص قد يحتوي على زوائد حوله."""
    text = (text or "").strip()
    # إزالة أسوار ```json ... ``` إن وُجدت
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    # محاولة أخيرة: التقاط أول { ... } متوازن يدوياً
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                try:
                    return json.loads(candidate)
                except Exception:
                    return None
    return None


if __name__ == "__main__":
    # Render يمرر رقم المنفذ عبر متغير البيئة PORT
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
