import logging
import os

from flask import Flask, jsonify, render_template, request, session
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from auth_routes import bp as auth_bp
from billing_routes import bp as billing_bp
from config import config
from dashboard_routes import bp as dashboard_bp
from extensions import csrf, limiter
from models import feature_is_enabled, get_db_connection, init_db
from routes.insight_routes import insight_bp


def create_app(testing: bool = False) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(config)
    if app.config["TRUST_PROXY_HEADERS"]:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.config["TESTING"] = testing
    app.config["WTF_CSRF_ENABLED"] = not testing
    app.logger.setLevel(getattr(logging, app.config["LOG_LEVEL"].upper(), logging.INFO))
    if not app.logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        app.logger.addHandler(handler)
    if testing:
        app.config.update(
            DATABASE_URL="",
            STRIPE_SECRET_KEY="",
            STRIPE_WEBHOOK_SECRET="",
            STRIPE_PREMIUM_PRICE_ID="",
            INSIGHT_API_KEY="",
            MAIL_SUPPRESS_SEND=True,
            REQUIRE_EMAIL_VERIFICATION=False,
        )
        os.environ.pop("DATABASE_URL", None)
    elif app.config["REQUIRE_POSTGRES"] and not app.config["DATABASE_URL"].startswith(("postgres://", "postgresql://")):
        raise RuntimeError("REQUIRE_POSTGRES is enabled but DATABASE_URL is not a PostgreSQL URL.")
    app.secret_key = app.config["SECRET_KEY"]
    if app.config["SENTRY_DSN"] and not testing:
        try:
            import sentry_sdk
            from sentry_sdk.integrations.flask import FlaskIntegration

            sentry_sdk.init(dsn=app.config["SENTRY_DSN"], integrations=[FlaskIntegration()], traces_sample_rate=0.1)
        except ImportError:
            app.logger.warning("SENTRY_DSN is configured but sentry-sdk is not installed.")
    csrf.init_app(app)
    limiter.init_app(app)
    init_db()
    app.register_blueprint(insight_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(dashboard_bp)

    @app.before_request
    def apply_maintenance_mode():
        """Keep an emergency maintenance switch available without blocking admins."""
        endpoint = request.endpoint or ""
        if endpoint.startswith("static") or endpoint in {"auth.login", "auth.logout", "auth.admin"}:
            return None
        if not feature_is_enabled("maintenance_mode", default=False):
            return None
        user_id = session.get("user_id")
        if user_id:
            with get_db_connection() as conn:
                user = conn.execute("SELECT email, role FROM users WHERE id = ?", (user_id,)).fetchone()
            if user and (user["role"] == "admin" or (app.config["ADMIN_EMAIL"] and user["email"].lower() == app.config["ADMIN_EMAIL"])):
                return None
        return render_template("maintenance.html"), 503

    @app.context_processor
    def inject_account_preferences():
        """Expose the saved account appearance settings to every template."""
        language = session.get("preferred_language", "en")
        theme = session.get("theme_preference", "light")
        return {
            "ui_language": language if language in {"en", "ar"} else "en",
            "ui_direction": "rtl" if language == "ar" else "ltr",
            "ui_theme": theme if theme in {"light", "dark"} else "light",
        }

    @app.after_request
    def translate_account_pages(response):
        """Apply the account UI language server-side; public pages always remain English."""
        if session.get("preferred_language") != "ar" or not response.content_type.startswith("text/html"):
            return response
        translations = {
            "Overview": "نظرة عامة", "Transactions": "المعاملات", "Analytics": "التحليلات", "Budgets": "الميزانيات", "Goals": "الأهداف", "Reports": "التقارير", "Settings": "الإعدادات", "Recurring": "المعاملات المتكررة", "Log out": "تسجيل الخروج", "Income": "الدخل", "Expenses": "المصروفات", "Save": "حفظ", "Delete": "حذف", "Filter": "تصفية", "Search transactions": "ابحث في المعاملات", "Current password": "كلمة المرور الحالية", "New password": "كلمة مرور جديدة", "Change password": "تغيير كلمة المرور", "Email address": "البريد الإلكتروني", "Security": "الأمان",
            "All types": "كل الأنواع", "Type": "النوع", "Expense": "مصروف", "Amount": "المبلغ", "Category": "الفئة", "Currency": "العملة", "Description": "الوصف", "Timeline": "الجدول الزمني", "Add movement": "إضافة حركة", "Record a transaction": "سجل معاملة", "Save transaction": "حفظ المعاملة", "No transactions yet.": "لا توجد معاملات حتى الآن.", "Your money activity": "حركة أموالك", "Based on your actual saved transactions.": "بناءً على معاملاتك المحفوظة فعليًا.", "Total income": "إجمالي الدخل", "Total expenses": "إجمالي المصروفات", "Net cashflow": "صافي التدفق النقدي", "Income vs expenses": "الدخل مقابل المصروفات", "Expense breakdown": "تفصيل المصروفات", "No expense data yet.": "لا توجد بيانات للمصروفات حتى الآن.", "Historical monthly data": "البيانات الشهرية السابقة", "Patterns worth noticing": "أنماط تستحق الملاحظة", "Detailed analytics": "تحليلات تفصيلية",
            "New budget": "ميزانية جديدة", "Monthly limit": "الحد الشهري", "Already spent": "المصروف بالفعل", "Save budget": "حفظ الميزانية", "Build a simple budget": "أنشئ ميزانية بسيطة", "Set a spending boundary": "حدد سقفًا للإنفاق", "Make room for what matters": "اترك مساحة لما يهمك", "A useful starting point": "بداية مفيدة", "Choose a number": "اختر رقمًا", "that feels doable.": "يمكن الالتزام به.", "Pick one category": "اختر فئة واحدة", "Check in weekly": "راجع أسبوعيًا", "Your budgets": "ميزانياتك", "Budget used": "الميزانية المستخدمة", "No budgets yet.": "لا توجد ميزانيات حتى الآن.",
            "Savings goals": "أهداف الادخار", "New goal": "هدف جديد", "Goal name": "اسم الهدف", "Target amount": "المبلغ المستهدف", "Already saved": "المدخر حاليًا", "Target date": "التاريخ المستهدف", "Create goal": "إنشاء الهدف", "Active goals": "الأهداف النشطة", "No deadline": "بلا موعد نهائي", "Your first goal starts with a name.": "هدفك الأول يبدأ باسم.", "Make progress visible": "اجعل التقدم واضحًا", "What are you building toward?": "ما الهدف الذي تسعى إليه؟",
            "Recurring payments": "المدفوعات المتكررة", "New schedule": "جدول جديد", "Frequency": "التكرار", "Monthly": "شهري", "Weekly": "أسبوعي", "Yearly": "سنوي", "Next date": "التاريخ القادم", "Scheduled activity": "النشاط المجدول", "Save recurring item": "حفظ المعاملة المتكررة", "No recurring items yet.": "لا توجد معاملات متكررة حتى الآن.", "Automatic clarity": "وضوح تلقائي", "Make it automatic": "اجعله تلقائيًا",
            "Financial report": "التقرير المالي", "Your month in one view": "شهرك في نظرة واحدة", "Download CSV": "تنزيل CSV", "Download PDF": "تنزيل PDF", "Ready to share or keep.": "جاهز للمشاركة أو الاحتفاظ به.", "Premium forecast": "توقعات بريميوم", "Next month": "الشهر القادم", "Explore Premium": "استكشف بريميوم", "Display currency": "عملة العرض", "Update": "تحديث", "New entries are converted at the live rate.": "يتم تحويل الإدخالات الجديدة بالسعر الحالي.",
            "AI Advisor": "المستشار الذكي", "Financial insight advisor": "مستشار التحليل المالي", "Ask a better question. Get a clearer next step.": "اطرح سؤالًا أفضل واحصل على خطوة تالية أوضح.", "Your money, your context": "أموالك وسياقك", "What would you like to understand?": "ما الذي تريد فهمه؟", "Your goal or question": "هدفك أو سؤالك", "Monthly income": "الدخل الشهري", "Top categories": "أهم الفئات", "Recent transactions": "المعاملات الحديثة", "Generate my insight": "أنشئ تحليلي", "Your clear next step": "خطوتك التالية الواضحة", "AI financial insight": "تحليل مالي بالذكاء الاصطناعي", "Reading your money story...": "نقرأ قصة أموالك...", "Add category": "إضافة فئة", "Add transaction": "إضافة معاملة", "Notifications": "الإشعارات", "Mark all read": "تحديد الكل كمقروء", "No new notifications.": "لا توجد إشعارات جديدة.", "Good morning,": "صباح الخير،"
            , "Account & preferences": "الحساب والتفضيلات", "Profile settings": "إعدادات الملف الشخصي", "Manage your account details and how ClearSpend looks.": "أدِر بيانات حسابك وطريقة ظهور ClearSpend.", "Your profile": "ملفك الشخصي", "Your details and preferences": "بياناتك وتفضيلاتك", "Display name": "الاسم الظاهر", "Language": "اللغة", "Arabic": "العربية", "Theme": "المظهر", "Light": "فاتح", "Dark": "داكن", "Save changes": "حفظ التغييرات", "Danger zone": "منطقة خطرة", "Delete account": "حذف الحساب", "This permanently removes your profile and financial data.": "سيؤدي ذلك إلى حذف ملفك الشخصي وبياناتك المالية نهائيًا.", "Delete my account": "حذف حسابي", "Update password": "تحديث كلمة المرور", "Two-factor authentication": "التحقق بخطوتين", "Require an email code when signing in": "اطلب كودًا عبر البريد عند تسجيل الدخول", "Save 2FA setting": "حفظ إعداد التحقق", "Change sign-in email": "تغيير بريد تسجيل الدخول", "New email": "بريد إلكتروني جديد", "Send confirmation": "إرسال التأكيد"
        }
        content = response.get_data(as_text=True)
        for source, target in sorted(translations.items(), key=lambda item: len(item[0]), reverse=True):
            content = content.replace(source, target)
        response.set_data(content)
        return response

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        if isinstance(error, HTTPException):
            return error
        app.logger.exception("Unhandled application error on %s", request.path)
        if request.path.startswith("/api/"):
            return jsonify({"error": "An unexpected server error occurred."}), 500
        return render_template("500.html"), 500

    @app.errorhandler(404)
    def handle_not_found(error):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Resource not found."}), 404
        return render_template("404.html"), 404

    return app

