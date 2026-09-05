import html as _html
import os
from urllib.parse import quote

from paths import CODE_ROOT

ASSETS_SOCIAL_DIR = os.path.join(CODE_ROOT, "src", "assets", "social")
INSTAGRAM_LOGO_PATH = os.path.join(ASSETS_SOCIAL_DIR, "instagram.png")
FACEBOOK_LOGO_PATH = os.path.join(ASSETS_SOCIAL_DIR, "facebook.png")

INSTAGRAM_CID = "alj_instagram_logo"
FACEBOOK_CID = "alj_facebook_logo"

CLUB_NAME = "Amicale Laïque de Jonage"
CLUB_EMAIL = "amicalelaique.jonage@gmail.com"
CLUB_WEBSITE_LABEL = "alj-escalade.fr"
CLUB_WEBSITE_URL = "https://alj-escalade.fr"
INSTAGRAM_URL = "https://www.instagram.com/aljescalade/"
FACEBOOK_URL = "https://www.facebook.com/amicalelaiquedejonage/"


def get_inline_images() -> list:
    """Retourne les images à intégrer en pièces jointes inline (chemin, Content-ID)."""
    return [
        (INSTAGRAM_LOGO_PATH, INSTAGRAM_CID),
        (FACEBOOK_LOGO_PATH, FACEBOOK_CID),
    ]


def build_signature_plain() -> str:
    """Signature du club au format texte brut (clients de messagerie sans HTML)."""
    return (
        "---\n"
        f"{CLUB_NAME}\n"
        f"{CLUB_EMAIL}\n"
        f"{CLUB_WEBSITE_LABEL}\n"
        "Suivez nous sur les réseaux !\n"
        f"Instagram : {INSTAGRAM_URL}\n"
        f"Facebook : {FACEBOOK_URL}"
    )


def build_signature_html(image_src_mode: str = "cid") -> str:
    """Signature du club au format HTML avec logos Instagram et Facebook.

    image_src_mode : "cid" pour un envoi réel (images inline) ou "preview" (chemins fichier locaux).
    """
    if image_src_mode == "preview":
        def _src(path):
            return "file:///" + quote(os.path.abspath(path).replace("\\", "/"))
    else:
        cid_map = {INSTAGRAM_LOGO_PATH: INSTAGRAM_CID, FACEBOOK_LOGO_PATH: FACEBOOK_CID}
        def _src(path):
            return "cid:" + cid_map.get(path, "alj_logo")

    template = (
        '<div style="margin-top:24px;padding-top:12px;border-top:1px solid #D1D5DB;'
        'font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#374151;">'
        '<span style="font-weight:bold;color:#111827;">{club}</span><br>'
        '<a href="mailto:{email}" style="color:#2563EB;text-decoration:none;">{email}</a>'
        ' &nbsp;|&nbsp; '
        '<a href="{site_url}" style="color:#2563EB;text-decoration:none;">{site}</a><br>'
        'Suivez nous sur les réseaux !<br>'
        '<table cellpadding="0" cellspacing="0" style="margin-top:6px;"><tr>'
        '<td style="padding-right:12px;">'
        '<a href="{ig_url}"><img src="{ig_src}" width="26" height="26" '
        'alt="Instagram" style="vertical-align:middle;border:0;"></a></td>'
        '<td style="padding-right:12px;">'
        '<a href="{fb_url}"><img src="{fb_src}" width="26" height="26" '
        'alt="Facebook" style="vertical-align:middle;border:0;"></a></td>'
        '</tr></table>'
    )
    return template.format(
        club=CLUB_NAME,
        email=CLUB_EMAIL,
        site=CLUB_WEBSITE_LABEL,
        site_url=CLUB_WEBSITE_URL,
        ig_url=INSTAGRAM_URL,
        ig_src=_src(INSTAGRAM_LOGO_PATH),
        fb_url=FACEBOOK_URL,
        fb_src=_src(FACEBOOK_LOGO_PATH),
    )


def text_to_html(text: str) -> str:
    """Convertit le texte brut saisi par l'utilisateur en HTML sûr (échappement + sauts de ligne).

    Les balises simples volontairement saisies (<b>, <i>, <u>, <br>) sont conservées.
    """
    escaped = _html.escape(str(text), quote=False)
    for tag in ("b", "i", "u"):
        escaped = escaped.replace(f"&lt;{tag}&gt;", f"<{tag}>").replace(f"&lt;/{tag}&gt;", f"</{tag}>")
    escaped = escaped.replace("&lt;br&gt;", "<br>").replace("&lt;br /&gt;", "<br>")
    return escaped.replace("\r\n", "\n").replace("\n", "<br>")


def build_email_html(body_text: str, add_signature: bool = True, image_src_mode: str = "cid") -> str:
    """Construit le code HTML complet du courriel (corps + signature optionnelle)."""
    sig_html = build_signature_html(image_src_mode) if add_signature else ""
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#1F2937;line-height:1.5;">'
        f'{text_to_html(body_text)}{sig_html}</div>'
    )
