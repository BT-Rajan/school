"""Bilingual email templates (FR-I9). Emails go out in the recipient's language."""

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
    "digest": {
        "en": ("Your daily summary", "Here is what happened today:\n\n{items}"),
        "ar": ("ملخصك اليومي", "إليك ما حدث اليوم:\n\n{items}"),
    },
}


def render(template: str, locale: str, context: dict[str, Any]) -> Rendered:
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
