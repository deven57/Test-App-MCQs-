import os
import csv
import json
import uuid
import hmac
import hashlib
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for, flash, session,
    send_file, jsonify, make_response
)
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Try import razorpay, but allow demo mode if not available
try:
    import razorpay
    HAS_RAZORPAY = True
except Exception:
    razorpay = None
    HAS_RAZORPAY = False

# Load env
load_dotenv()

ADMIN_PASS = os.environ.get("ADMIN_PASS", "changeme")
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "").strip()
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "").strip()
SECRET_KEY = os.environ.get("SECRET_KEY") or os.urandom(24).hex()

DEMO_MODE = not (RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET and HAS_RAZORPAY)

app = Flask(__name__)
app.secret_key = SECRET_KEY

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
QUIZ_DIR = os.path.join(DATA_DIR, "quizzes")
for d in (DATA_DIR, QUIZ_DIR):
    os.makedirs(d, exist_ok=True)

TESTS_FILE = os.path.join(DATA_DIR, "tests.json")
SUBMISSIONS_FILE = os.path.join(DATA_DIR, "submissions.json")
COUPONS_FILE = os.path.join(DATA_DIR, "coupons.json")

def _load_json(path, default):
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(default, f, indent=2)
        return default
    with open(path, "r") as f:
        try:
            return json.load(f)
        except Exception:
            return default


def _save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)

def load_tests():
    return _load_json(TESTS_FILE, [])

def save_tests(tests):
    _save_json(TESTS_FILE, tests)

def load_submissions():
    return _load_json(SUBMISSIONS_FILE, [])

def save_submissions(subs):
    _save_json(SUBMISSIONS_FILE, subs)

def load_coupons():
    return _load_json(COUPONS_FILE, [])

def save_coupons(coupons):
    _save_json(COUPONS_FILE, coupons)

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login", next=request.path))
        return f(*args, **kwargs)
    return decorated

# Razorpay client
razor_client = None
if not DEMO_MODE:
    try:
        razor_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
    except Exception:
        razor_client = None
        DEMO_MODE = True

@app.route("/")
def index():
    tests = load_tests()
    return render_template("index.html", tests=tests, demo=DEMO_MODE)

@app.route("/admin/login", methods=["GET", "POST"])\
    if request.method == "POST":
        pwd = request.form.get("password", "")
        if pwd == ADMIN_PASS:
            session["admin"] = True
            flash("Logged in as admin", "success")
            return redirect(url_for("admin_dashboard"))
        else:
            flash("Incorrect password", "danger")
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    flash("Logged out", "info")
    return redirect(url_for("admin_login"))

@app.route("/admin")
@admin_required
def admin_dashboard():
    tests = load_tests()
    submissions = load_submissions()
    coupons = load_coupons()
    return render_template("admin_dashboard.html", tests=tests, submissions=submissions, coupons=coupons)

@app.route("/admin/upload", methods=["GET", "POST"])
@admin_required
def admin_upload():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        price = request.form.get("price", "0").strip()
        file = request.files.get("file")
        if not title:
            flash("Title is required", "warning")
            return redirect(request.url)
        try:
            price = float(price)
            if price < 0:
                raise ValueError()
        except Exception:
            flash("Invalid price", "warning")
            return redirect(request.url)
        if not file:
            flash("CSV file is required", "warning")
            return redirect(request.url)
        filename = secure_filename(file.filename)
        # Validate CSV headers
        stream = file.stream.read().decode("utf-8").splitlines()
        reader = csv.DictReader(stream)
        required = {"question","option_a","option_b","option_c","option_d","answer"}
        if not required.issubset(set([h.strip() for h in reader.fieldnames or []])):
            flash("CSV must contain headers: question,option_a,option_b,option_c,option_d,answer", "danger")
            return redirect(request.url)
        # Save file
        test_id = str(uuid.uuid4())
        test_filename = f"{test_id}.csv"
        file.stream.seek(0)
        save_path = os.path.join(QUIZ_DIR, test_filename)
        file.save(save_path)
        tests = load_tests()
        tests.append({
            "id": test_id,
            "title": title,
            "price_inr": float(price),
            "filename": test_filename,
            "created_at": datetime.utcnow().isoformat()
        })
        save_tests(tests)
        flash("Test uploaded", "success")
        return redirect(url_for("admin_dashboard"))
    return render_template("upload_test.html")

@app.route("/admin/test/<test_id>/submissions")
@admin_required
def admin_view_submissions(test_id):
    submissions = [s for s in load_submissions() if s.get("test_id")==test_id]
    tests = load_tests()
    test = next((t for t in tests if t["id"]==test_id), None)
    return render_template("admin_view_submissions.html", submissions=submissions, test=test)

@app.route("/admin/test/<test_id>/download")
@admin_required
def admin_download_submissions(test_id):
    subs = [s for s in load_submissions() if s.get("test_id")==test_id]
    tests = load_tests()
    test = next((t for t in tests if t["id"]==test_id), None)
    csv_rows = []
    headers = ["submission_id","name","mobile","institute","address","paid","payment_id","score","created_at","ref_used","coupon_used"]
    for s in subs:
        csv_rows.append({
            "submission_id": s.get("id"),
            "name": s.get("name"),
            "mobile": s.get("mobile"),
            "institute": s.get("institute",""),
            "address": s.get("address",""),
            "paid": s.get("paid", False),
            "payment_id": s.get("payment_id",""),
            "score": s.get("score",""),
            "created_at": s.get("created_at",""),
            "ref_used": s.get("ref", ""),
            "coupon_used": s.get("coupon_used","")
        })
    # create CSV in-memory
    from io import StringIO, BytesIO
    si = StringIO()
    writer = csv.DictWriter(si, fieldnames=headers)
    writer.writeheader()
    for r in csv_rows:
        writer.writerow(r)
    mem = BytesIO()
    mem.write(si.getvalue().encode("utf-8"))
    mem.seek(0)
    filename = f"submissions_{test['title'] if test else test_id}.csv"
    return send_file(mem, as_attachment=True, download_name=filename, mimetype="text/csv")

@app.route("/student_form/<test_id>", methods=["GET", "POST"])
def student_form(test_id):
    tests = load_tests()
    test = next((t for t in tests if t["id"]==test_id), None)
    if not test:
        flash("Test not found", "danger")
        return redirect(url_for("index"))
    ref = request.args.get("ref") or request.form.get("ref") or ""
    if request.method == "POST":
        name = request.form.get("name","").strip()
        mobile = request.form.get("mobile","").strip()
        institute = request.form.get("institute","").strip()
        address = request.form.get("address","").strip()
        coupon_code = request.form.get("coupon","").strip()
        if not name or not mobile:
            flash("Full name and mobile are required", "warning")
            return redirect(request.url)
        submission_id = str(uuid.uuid4())
        submissions = load_submissions()
        new_sub = {
            "id": submission_id,
            "test_id": test_id,
            "name": name,
            "mobile": mobile,
            "institute": institute,
            "address": address,
            "paid": False,
            "payment_id": "",
            "score": None,
            "answers": {},
            "created_at": datetime.utcnow().isoformat(),
            "ref": ref,
            "coupon_used": coupon_code or ""
        }
        submissions.append(new_sub)
        save_submissions(submissions)
        # Process payment or demo
        apply_discount = 0.0
        coupons = load_coupons()
        if coupon_code:
            c = next((c for c in coupons if c["code"]==coupon_code and not c.get("used", False)), None)
            if c:
                apply_discount = float(c.get("discount_percent", 0.0))
        price = float(test.get("price_inr", 0.0))
        payable = max(0.0, price * (1 - apply_discount/100.0))
        # If demo mode or payable == 0 => skip payment
        if DEMO_MODE or payable <= 0:
            # Mark paid, possibly mark coupon used (if any)
            for s in submissions:
                if s["id"] == submission_id:
                    s["paid"] = True
                    s["payment_id"] = "DEMO" if DEMO_MODE else ""
                    break
            # If coupon used, mark as used
            if coupon_code:
                for c in coupons:
                    if c["code"] == coupon_code:
                        c["used"] = True
                save_coupons(coupons)
            save_submissions(submissions)
            # Award referral coupon to referrer if applicable
            maybe_award_referrer_coupon(submission_id)
            session["submission_id"] = submission_id
            return redirect(url_for("take_test", test_id=test_id, sid=submission_id))
        else:
            # Create razorpay order
            if not DEMO_MODE and razor_client:
                amount_paise = int(round(payable * 100))
                try:
                    order = razor_client.order.create({
                        "amount": amount_paise,
                        "currency": "INR",
                        "receipt": submission_id,
                        "payment_capture": 1
                    })
                    # Save order id in submission for later verification
                    for s in submissions:
                        if s["id"] == submission_id:
                            s["order_id"] = order.get("id")
                            s["payable"] = payable
                            s["price"] = price
                            save_submissions(submissions)
                            break
                    # Render payment page with details
                    return render_template("payment.html",
                                           razor_key=RAZORPAY_KEY_ID,
                                           order=order,
                                           name=name,
                                           mobile=mobile,
                                           test=test,
                                           submission_id=submission_id,
                                           payable=payable)
                except Exception as e:
                    flash(f"Payment initialization failed: {e}", "danger")
                    return redirect(request.url)
            else:
                flash("Payment not configured", "danger")
                return redirect(request.url)
    # GET
    return render_template("student_form.html", test=test, ref=ref)

@app.route("/payment/success", methods=["POST"])
def payment_success():
    # Razorpay will POST payment details via frontend JS; verify signature
    payload = request.form.to_dict()
    # Expected fields: razorpay_payment_id, razorpay_order_id, razorpay_signature, submission_id
    payment_id = payload.get("razorpay_payment_id")
    order_id = payload.get("razorpay_order_id")
    signature = payload.get("razorpay_signature")
    submission_id = payload.get("submission_id")
    if not (payment_id and order_id and signature and submission_id):
        return jsonify({"status":"error","message":"Missing payment data"}), 400
    # Verify signature using razorpay util if available
    verified = False
    if not DEMO_MODE and razor_client:
        try:
            params_dict = {
                "razorpay_order_id": order_id,
                "razorpay_payment_id": payment_id,
                "razorpay_signature": signature
            }
            razor_client.utility.verify_payment_signature(params_dict)
            verified = True
        except Exception as e:
            verified = False
    else:
        # Demo: accept
        verified = True
    if not verified:
        return jsonify({"status":"error","message":"Signature verification failed"}), 400
    # Mark submission paid
    submissions = load_submissions()
    for s in submissions:
        if s["id"] == submission_id:
            s["paid"] = True
            s["payment_id"] = payment_id
            s["order_id"] = order_id
            s.setdefault("payable", None)
            break
    save_submissions(submissions)
    # Mark coupon used if any
    coupon_code = next((s.get("coupon_used","") for s in submissions if s["id"]==submission_id), "")
    if coupon_code:
        coupons = load_coupons()
        for c in coupons:
            if c["code"] == coupon_code:
                c["used"] = True
        save_coupons(coupons)
    # Award referral coupon to referrer if applicable
    maybe_award_referrer_coupon(submission_id)
    # Return success (frontend will redirect to take_test)
    return jsonify({"status":"ok","redirect": url_for("take_test", test_id=s["test_id"], sid=submission_id)})

def maybe_award_referrer_coupon(new_submission_id):
    # If the new paid submission used ref and ref maps to an existing submission id,
    # award a 50% coupon to the referrer (stored in coupons.json)
    subs = load_submissions()
    new_sub = next((s for s in subs if s["id"]==new_submission_id), None)
    if not new_sub or not new_sub.get("paid"):
        return
    ref = new_sub.get("ref")
    if not ref:
        return
    # Ensure ref exists
    ref_sub = next((s for s in subs if s["id"]==ref), None)
    if not ref_sub:
        return
    # Do not award if referrer is the same person
    if ref_sub.get("mobile") == new_sub.get("mobile"):
        return
    coupons = load_coupons()
    # Award one coupon per successful referral (no duplicate coupon per (referrer, referred) pair)
    exists = any(c for c in coupons if c.get("owner_submission_id")==ref and c.get("referred_submission_id")==new_submission_id)
    if exists:
        return
    coupon_code = f"CPN-{uuid.uuid4().hex[:8].upper()}"
    coupon = {
        "code": coupon_code,
        "owner_submission_id": ref,
        "referred_submission_id": new_submission_id,
        "discount_percent": 50,
        "used": False,
        "created_at": datetime.utcnow().isoformat()
    }
    coupons.append(coupon)
    save_coupons(coupons)

@app.route("/take_test/<test_id>")
def take_test(test_id):
    sid = request.args.get("sid") or request.args.get("submission_id") or session.get("submission_id")
    tests = load_tests()
    test = next((t for t in tests if t["id"]==test_id), None)
    if not test:
        flash("Test not found", "danger")
        return redirect(url_for("index"))
    if not sid:
        flash("Submission/session missing. Start test flow from homepage.", "warning")
        return redirect(url_for("student_form", test_id=test_id))
    subs = load_submissions()
    submission = next((s for s in subs if s["id"]==sid and s["test_id"]==test_id), None)
    if not submission:
        flash("Submission record not found", "danger")
        return redirect(url_for("student_form", test_id=test_id))
    # Require payment unless demo
    if not DEMO_MODE and not submission.get("paid"):
        flash("Payment required before starting the test", "warning")
        return redirect(url_for("student_form", test_id=test_id))
    # Load quiz CSV
    quiz_path = os.path.join(QUIZ_DIR, test["filename"])
    questions = []
    with open(quiz_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader, start=1):
            questions.append({
                "qid": idx,
                "question": row.get("question",""),
                "options": {
                    "A": row.get("option_a",""),
                    "B": row.get("option_b",""),
                    "C": row.get("option_c",""),
                    "D": row.get("option_d","")
                }
            })
    return render_template("take_test.html", test=test, questions=questions, submission=submission)

@app.route("/submit_test/<test_id>", methods=["POST"])
def submit_test(test_id):
    sid = request.form.get("submission_id")
    if not sid:
        flash("Submission id missing", "danger")
        return redirect(url_for("index"))
    subs = load_submissions()
    submission = next((s for s in subs if s["id"]==sid and s["test_id"]==test_id), None)
    if not submission:
        flash("Submission not found", "danger")
        return redirect(url_for("index"))
    # Load correct answers
    tests = load_tests()
    test = next((t for t in tests if t["id"]==test_id), None)
    quiz_path = os.path.join(QUIZ_DIR, test["filename"])
    correct = {}
    with open(quiz_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader, start=1):
            correct[str(idx)] = row.get("answer","”).strip().upper()
    # Collect answers
    answers = {}
    score = 0
    for qid in correct.keys():
        ans = (request.form.get(f"q_{qid}") or "").strip().upper()
        answers[qid] = ans
        if not ans:
            continue
        if ans == correct[qid]:
            score += 4
        else:
            score -= 1
    # Save submission
    for s in subs:
        if s["id"] == sid:
            s["answers"] = answers
            s["score"] = score
            s["completed_at"] = datetime.utcnow().isoformat()
            break
    save_submissions(subs)
    # Provide shareable referral link (ref code = submission id)
    refcode = sid
    return render_template("result.html", score=score, submission=submission, test=test, refcode=refcode)

@app.route("/coupons")
def coupons_view():
    # Public endpoint to view coupons for demonstration (not required)
    coupons = load_coupons()
    return jsonify(coupons)

# Serve uploaded CSV sample or quiz files (admin only)
@app.route("/quizzes/<filename>")
@admin_required
def serve_quiz_file(filename):
    path = os.path.join(QUIZ_DIR, filename)
    if os.path.exists(path):
        return send_file(path)
    else:
        return "Not found", 404

# Static health-check
@app.route("/health")
def health():
    return "ok"

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
