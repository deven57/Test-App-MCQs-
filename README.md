# Quiz Store - Flask App

A simple Flask app to host and sell online quizzes from CSV files.

Features:
- Admin panel (password from ADMIN_PASS env var)
- Upload quizzes as CSV (question,option_a,option_b,option_c,option_d,answer)
- Set price per quiz (INR)
- Razorpay UPI payment support (RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET). If missing, demo mode bypasses payments.
- Student info form before test (name, mobile required)
- Scoring: +4 for correct, −1 for wrong
- Referral system: ?ref=REFCODE (REFCODE is a submission id). If a new user pays using the link, the referrer gets a 50% discount coupon.
- Persistent JSON storage in `data/` (tests.json, submissions.json, coupons.json)
- Admin view and one-click CSV download of submissions
- Mobile-friendly templates (Bootstrap)

Run locally:
1. Copy `.env.example` to `.env` and set ADMIN_PASS and optionally Razorpay keys.
2. Install dependencies:
   pip install -r requirements.txt
3. Start:
   python main.py

For Render:
- Make sure `PORT` environment variable is set by Render (Render sets it automatically).
- Set ADMIN_PASS and optionally Razorpay keys in Render dashboard.
- Deploy repository; Render will run the app.

Sample quiz provided: `sample_questions.csv`

Notes:
- The app will create `data/` and subfolders automatically if missing.
- Coupons and data are stored in JSON files for simple persistence across restarts.
