"""Gabarits des emails transactionnels, en français et en anglais.

Les valeurs insérées dans la version HTML sont échappées : un nom de dossier ou de
personne ne peut pas injecter de balisage.
"""

from dataclasses import dataclass
from html import escape

from kora.email.sender import OutgoingEmail

Locale = str


@dataclass(frozen=True)
class _Template:
    subject: str
    intro: str
    action: str | None
    outro: str


_TEMPLATES: dict[str, dict[Locale, _Template]] = {
    "password_reset": {
        "fr": _Template(
            subject="Réinitialisation de votre mot de passe Kora Finance",
            intro=(
                "Bonjour {name},\n\nUne demande de réinitialisation du mot de passe de votre "
                "compte Kora Finance a été reçue. Ce lien est valable {ttl} minutes et ne "
                "peut servir qu'une fois."
            ),
            action="Choisir un nouveau mot de passe",
            outro=(
                "Si vous n'êtes pas à l'origine de cette demande, ignorez cet email : votre "
                "mot de passe actuel reste valable."
            ),
        ),
        "en": _Template(
            subject="Reset your Kora Finance password",
            intro=(
                "Hello {name},\n\nWe received a request to reset the password of your Kora "
                "Finance account. This link is valid for {ttl} minutes and can be used once."
            ),
            action="Choose a new password",
            outro=(
                "If you did not make this request, ignore this email: your current password "
                "remains valid."
            ),
        ),
    },
    "password_changed": {
        "fr": _Template(
            subject="Votre mot de passe Kora Finance a été modifié",
            intro=(
                "Bonjour {name},\n\nLe mot de passe de votre compte Kora Finance vient d'être "
                "modifié. Toutes vos autres sessions ont été fermées."
            ),
            action=None,
            outro=(
                "Si vous n'êtes pas à l'origine de ce changement, utilisez immédiatement "
                "« Mot de passe oublié » sur la page de connexion et prévenez le support."
            ),
        ),
        "en": _Template(
            subject="Your Kora Finance password was changed",
            intro=(
                "Hello {name},\n\nThe password of your Kora Finance account has just been "
                "changed. All your other sessions have been signed out."
            ),
            action=None,
            outro=(
                "If you did not make this change, immediately use “Forgot password” on the "
                "sign-in page and contact support."
            ),
        ),
    },
    "email_verification": {
        "fr": _Template(
            subject="Confirmez votre adresse email Kora Finance",
            intro=(
                "Bonjour {name},\n\nConfirmez que cette adresse vous appartient pour "
                "sécuriser votre compte Kora Finance. Ce lien est valable {ttl} heures."
            ),
            action="Confirmer mon adresse",
            outro="Si vous n'avez pas créé de compte Kora Finance, ignorez cet email.",
        ),
        "en": _Template(
            subject="Confirm your Kora Finance email address",
            intro=(
                "Hello {name},\n\nConfirm that this address belongs to you to secure your "
                "Kora Finance account. This link is valid for {ttl} hours."
            ),
            action="Confirm my address",
            outro="If you did not create a Kora Finance account, ignore this email.",
        ),
    },
    "invitation": {
        "fr": _Template(
            subject="{inviter} vous invite sur le dossier {company} — Kora Finance",
            intro=(
                "Bonjour,\n\n{inviter} vous invite à rejoindre le dossier « {company} » sur "
                "Kora Finance, avec le rôle {role}. Cette invitation est valable {ttl} jours."
            ),
            action="Accepter l'invitation",
            outro="Si vous ne connaissez pas cette personne, ignorez cet email.",
        ),
        "en": _Template(
            subject="{inviter} invited you to {company} — Kora Finance",
            intro=(
                "Hello,\n\n{inviter} invited you to join “{company}” on Kora Finance, with "
                "the role {role}. This invitation is valid for {ttl} days."
            ),
            action="Accept the invitation",
            outro="If you do not know this person, ignore this email.",
        ),
    },
}

ROLE_LABELS: dict[Locale, dict[str, str]] = {
    "fr": {
        "PME_DIRIGEANT": "Dirigeant",
        "PME_COMPTABLE": "Comptable",
        "PME_LECTEUR": "Lecture seule",
    },
    "en": {
        "PME_DIRIGEANT": "Director",
        "PME_COMPTABLE": "Accountant",
        "PME_LECTEUR": "Read only",
    },
}

_LINK_FALLBACK = {
    "fr": "Si le bouton ne fonctionne pas, copiez ce lien dans votre navigateur :",
    "en": "If the button does not work, copy this link into your browser:",
}


def _paragraphs_html(text: str) -> str:
    return "".join(
        f'<p style="margin:0 0 16px">{escape(p).replace(chr(10), "<br>")}</p>'
        for p in text.split("\n\n")
    )


def render(
    template_name: str, locale: Locale, /, *, to: str, url: str | None = None, **values: str | int
) -> OutgoingEmail:
    template = _TEMPLATES[template_name].get(locale) or _TEMPLATES[template_name]["fr"]
    lang = locale if locale in _LINK_FALLBACK else "fr"
    # Un en-tête ne doit contenir aucun saut de ligne (injection d'en-têtes).
    subject = " ".join(template.subject.format(**values).split())
    intro = template.intro.format(**values)
    outro = template.outro.format(**values)

    text_parts = [intro]
    html_parts = [_paragraphs_html(intro)]
    if template.action is not None:
        if url is None:
            raise ValueError(f"Le gabarit {template_name} exige un lien.")
        text_parts.append(f"{template.action} :\n{url}")
        html_parts.append(
            f'<p style="margin:24px 0"><a href="{escape(url)}" style="background:#0f766e;'
            "color:#ffffff;padding:12px 20px;border-radius:6px;text-decoration:none;"
            f'display:inline-block">{escape(template.action)}</a></p>'
            f'<p style="margin:0 0 16px;font-size:13px;color:#555">{_LINK_FALLBACK[lang]}<br>'
            f'<span style="word-break:break-all">{escape(url)}</span></p>'
        )
    text_parts.append(outro)
    html_parts.append(_paragraphs_html(outro))
    text_parts.append("— Kora Finance")

    html = (
        f'<!doctype html><html lang="{lang}"><body style="margin:0;padding:24px;'
        "background:#f4f4f5;font-family:Arial,Helvetica,sans-serif;font-size:15px;"
        'line-height:1.5;color:#18181b"><div style="max-width:560px;margin:0 auto;'
        'background:#ffffff;border-radius:8px;padding:32px">'
        '<p style="margin:0 0 24px;font-weight:bold;font-size:18px">Kora Finance</p>'
        + "".join(html_parts)
        + "</div></body></html>"
    )
    return OutgoingEmail(to=to, subject=subject, text="\n\n".join(text_parts), html=html)
