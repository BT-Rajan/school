"""Bilingual email templates (FR-I9). Emails go out in the recipient's language."""

import re
from dataclasses import dataclass
from html import escape
from typing import Any


@dataclass
class Rendered:
    subject: str
    text: str
    html: str


# Each template: locale -> (subject, body). Bodies use str.format placeholders.
TEMPLATES: dict[str, dict[str, tuple[str, str]]] = {
    "login_code": {
        "en": (
            "Your sign-in code: {code}",
            "Your sign-in code is {code}. It expires in 10 minutes.\n\n"
            "If you did not try to sign in, change your password and tell your administrator.",
        ),
        "ar": (
            "رمز تسجيل الدخول: {code}",
            "رمز تسجيل الدخول الخاص بك هو {code}. تنتهي صلاحيته خلال 10 دقائق.\n\n"
            "إذا لم تحاول تسجيل الدخول، فغيّر كلمة المرور وأبلغ المسؤول.",
        ),
    },
    "password_reset_code": {
        "en": (
            "Your password reset code: {code}",
            "Your password reset code is {code}. It expires in 10 minutes.\n\n"
            "If you did not ask to reset your password, you can ignore this email.",
        ),
        "ar": (
            "رمز إعادة تعيين كلمة المرور: {code}",
            "رمز إعادة تعيين كلمة المرور هو {code}. تنتهي صلاحيته خلال 10 دقائق.\n\n"
            "إذا لم تطلب إعادة تعيين كلمة المرور، يمكنك تجاهل هذه الرسالة.",
        ),
    },
    "invitation": {
        "en": (
            "You are invited to {district}",
            "Hello {name},\n\nYou have been invited to the School Cluster Evaluation System for {district}.\n"
            "Open this link to set your password. It expires in 72 hours and works once:\n\n{link}",
        ),
        "ar": (
            "دعوة للانضمام إلى {district}",
            "مرحبًا {name}،\n\nتمت دعوتك إلى نظام تقييم المجمعات المدرسية في {district}.\n"
            "افتح هذا الرابط لتعيين كلمة المرور. تنتهي صلاحيته خلال 72 ساعة ويعمل مرة واحدة فقط:\n\n{link}",
        ),
    },
    "mfa_reset_notice": {
        "en": (
            "Your sign-in method was reset",
            "An administrator reset your sign-in method to emailed codes. "
            "If you did not ask for this, tell your administrator now.",
        ),
        "ar": (
            "تمت إعادة تعيين طريقة تسجيل الدخول",
            "أعاد أحد المسؤولين تعيين طريقة تسجيل الدخول إلى الرموز المرسلة بالبريد الإلكتروني. "
            "إذا لم تطلب ذلك، فأبلغ المسؤول فورًا.",
        ),
    },
    "break_glass_notice": {
        "en": (
            "Critical: emergency sign-in reset for {target}",
            "The server emergency command reset the second factor for {target}. Check the audit log entry {seq}.",
        ),
        "ar": (
            "تنبيه هام: إعادة تعيين طارئة لتسجيل الدخول للمستخدم {target}",
            "أعاد أمر الطوارئ على الخادم تعيين عامل التحقق الثاني للمستخدم {target}. راجع سجل التدقيق رقم {seq}.",
        ),
    },
    "audit_chain_broken": {
        "en": (
            "Critical: audit log integrity check failed",
            "The daily audit check found a break at entry {seq}: {detail}. Investigate immediately.",
        ),
        "ar": (
            "تنبيه هام: فشل التحقق من سلامة سجل التدقيق",
            "اكتشف الفحص اليومي خللًا عند السجل رقم {seq}: {detail}. يرجى التحقيق فورًا.",
        ),
    },
    "mail_quota_warning": {
        "en": (
            "Mail quota at {percent}% today",
            "The system has sent {sent} of {limit} messages today. "
            "Reminders and notices will wait until tomorrow if the limit is reached. Sign-in codes are reserved.",
        ),
        "ar": (
            "استهلاك حصة البريد اليوم {percent}%",
            "أرسل النظام {sent} من أصل {limit} رسالة اليوم. "
            "ستؤجل التذكيرات والإشعارات إلى الغد عند بلوغ الحد. رموز تسجيل الدخول محجوزة.",
        ),
    },
    "file_quarantined": {
        "en": (
            "A file you uploaded was blocked",
            "The file {name} failed the virus check and will not be shown to anyone. "
            "Scan the paper again and upload a new copy.",
        ),
        "ar": (
            "تم حظر ملف قمت برفعه",
            "لم يجتز الملف {name} فحص الفيروسات ولن يُعرض على أي شخص. امسح الورقة ضوئيًا مرة أخرى وارفع نسخة جديدة.",
        ),
    },
    "file_quarantined_admin": {
        "en": (
            "File {id} quarantined by the virus scanner",
            "The virus scanner flagged file {id} ({signature}). It is kept in quarantine and never served.",
        ),
        "ar": (
            "عزل الملف {id} بواسطة فاحص الفيروسات",
            "رصد فاحص الفيروسات الملف {id} ({signature}). تم عزله ولن يُقدَّم لأي مستخدم.",
        ),
    },
    "scanner_unavailable": {
        "en": (
            "Virus scanner unavailable",
            "Uploaded files are waiting because the virus scanner cannot be reached. Check the clamav service.",
        ),
        "ar": (
            "فاحص الفيروسات غير متاح",
            "الملفات المرفوعة في الانتظار لأنه يتعذر الوصول إلى فاحص الفيروسات. تحقق من خدمة clamav.",
        ),
    },
    "notice_wrapper": {
        "en": ("{line}", "{line}\n\nOpen the School Cluster Evaluation System for details."),
        "ar": ("{line}", "{line}\n\nافتح نظام تقييم المجمعات المدرسية للاطلاع على التفاصيل."),
    },
    "digest": {
        "en": ("Your daily summary", "Here is what happened today:\n\n{items}"),
        "ar": ("ملخصك اليومي", "إليك ما حدث اليوم:\n\n{items}"),
    },
}


# In-app notice types and their one-line text, used for emails and the daily digest.
NOTICES: dict[str, dict[str, str]] = {
    "assignment_started": {
        "en": "You are assigned to {school} ({school_code}) from {date}.",
        "ar": "تم إسنادك إلى {school} ({school_code}) اعتبارًا من {date}.",
    },
    "assignment_ended": {
        "en": "Your assignment to {school} ({school_code}) ends on {date}.",
        "ar": "ينتهي إسنادك إلى {school} ({school_code}) بتاريخ {date}.",
    },
    "form_submitted_for_review": {
        "en": "Form {report_code} version {version_code} is ready for your review.",
        "ar": "النموذج {report_code} الإصدار {version_code} جاهز لمراجعتك.",
    },
    "form_returned": {
        "en": "Form {report_code} version {version_code} was returned with comments.",
        "ar": "أُعيد النموذج {report_code} الإصدار {version_code} مع ملاحظات.",
    },
    "form_published": {
        "en": "Form {report_code} version {version_code} is open from {start} to {end}.",
        "ar": "النموذج {report_code} الإصدار {version_code} متاح من {start} إلى {end}.",
    },
    "form_window_changed": {
        "en": "Form {report_code} version {version_code} now closes on {end}.",
        "ar": "يُغلق النموذج {report_code} الإصدار {version_code} الآن بتاريخ {end}.",
    },
    "report_submitted": {
        "en": "New report {report_code} for {school} from {supervisor}.",
        "ar": "تقرير جديد {report_code} لمدرسة {school} من {supervisor}.",
    },
    "report_withdrawn": {
        "en": "Report {report_code} for {school} was withdrawn by {supervisor}.",
        "ar": "سحب {supervisor} التقرير {report_code} لمدرسة {school}.",
    },
    "report_acknowledged": {
        "en": "Your report {report_code} for {school} was acknowledged.",
        "ar": "تم اعتماد تقريرك {report_code} لمدرسة {school}.",
    },
    "report_returned": {
        "en": "Your report {report_code} for {school} was returned: {comment}",
        "ar": "أُعيد تقريرك {report_code} لمدرسة {school}: {comment}",
    },
    "report_forwarded": {
        "en": "Report {report_code} for {school} was shared with you.",
        "ar": "تمت مشاركة التقرير {report_code} لمدرسة {school} معك.",
    },
    "reports_overdue": {
        "en": "{count} submitted reports have waited more than {days} days for acknowledgement.",
        "ar": "{count} من التقارير المقدمة تنتظر الاعتماد منذ أكثر من {days} أيام.",
    },
    "evaluation_submitted": {
        "en": "Evaluation {report_code} for {school} was submitted by {supervisor}.",
        "ar": "قدّم {supervisor} التقييم {report_code} لمدرسة {school}.",
    },
    "evaluation_amended": {
        "en": "Evaluation {report_code} for {school} was amended by {supervisor}: {reason}",
        "ar": "عدّل {supervisor} التقييم {report_code} لمدرسة {school}: {reason}",
    },
    "evaluations_transferred": {
        "en": "{count} draft evaluations for {school} ({school_code}) were transferred to you.",
        "ar": "نُقلت إليك {count} من مسودات التقييم لمدرسة {school} ({school_code}).",
    },
}


class _Blank(dict):
    def __missing__(self, key: str) -> str:
        return ""


_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def district_date(value: Any) -> Any:
    """ISO dates are shown as D/MM/YYYY in both languages (FR-PB2, FR-I5)."""
    match = _ISO_DATE.match(value) if isinstance(value, str) else None
    return f"{int(match[3])}/{match[2]}/{match[1]}" if match else value


def notice_text(type_: str, locale: str, params: dict[str, Any]) -> str:
    texts = NOTICES[type_]
    shown = {k: district_date(v) for k, v in params.items()}
    return (texts.get(locale) or texts["en"]).format_map(_Blank(shown))


def render(template: str, locale: str, context: dict[str, Any]) -> Rendered:
    if template == "notice":
        line = notice_text(context["type"], locale, context.get("params") or {})
        return render("notice_wrapper", locale, {"line": line})
    variants = TEMPLATES[template]
    subject_tpl, body_tpl = variants.get(locale) or variants["en"]
    if template == "digest":
        context = {**context, "items": "\n".join(f"- {line}" for line in digest_lines(context["items"], locale))}
    subject = subject_tpl.format(**context)
    text = body_tpl.format(**context)
    direction = "rtl" if locale == "ar" else "ltr"
    paragraphs = "".join(f"<p>{escape(p).replace(chr(10), '<br>')}</p>" for p in text.split("\n\n"))
    html = (
        f'<!doctype html><html lang="{locale}" dir="{direction}"><body '
        f'style="font-family:Arial,Tahoma,sans-serif;direction:{direction};text-align:start">'
        f"{paragraphs}</body></html>"
    )
    return Rendered(subject, text, html)


def digest_lines(items: list[dict[str, Any]], locale: str) -> list[str]:
    return [render(item["template"], locale, item.get("context") or {}).subject for item in items]
