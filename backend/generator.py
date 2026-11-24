"""Motor de tarjetas independiente de la interfaz y de MySQL."""
import os
import shutil
import json
import re
import base64
import hashlib
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus
from html import escape
import qrcode
from PIL import Image, ImageDraw, ImageFont
APP_ROOT = Path(__file__).resolve().parent.parent
class CardGenerator:
    def __init__(self, base_dir="dist"):
        base_path = Path(base_dir)
        if not base_path.is_absolute():
            base_path = APP_ROOT / base_path
        self.base_dir = str(base_path)

    def _sanitize_username(self, username):
        cleaned = username.strip().lower()
        cleaned = cleaned.replace(" ", "-")
        cleaned = re.sub(r"[^a-z0-9._-]", "", cleaned)
        cleaned = re.sub(r"[-_.]{2,}", "-", cleaned)
        return cleaned.strip("-_.")

    def _get_client_dir(self, username):
        safe_username = self._sanitize_username(username)
        return Path(self.base_dir) / safe_username

    def generate(self, client_data, final_url):
        # Ensure links are parsed if they're JSON strings
        if isinstance(client_data.get('links'), str):
            try:
                client_data['links'] = json.loads(client_data['links'])
            except:
                client_data['links'] = []
        elif not client_data.get('links'):
            client_data['links'] = []

        username = self._sanitize_username(client_data['username'])
        client_dir = os.path.join(self.base_dir, username)
        assets_dir = os.path.join(client_dir, "assets")
        css_dir = os.path.join(client_dir, "css")
        design_profile = self._get_design_profile(client_data.get('category', 'abogados'), client_data)

        final_url = (final_url or "").strip()
        if not final_url:
            raise ValueError("Debes proporcionar el link final antes de generar la tarjeta.")

        # 1. Crear estructura de carpetas
        os.makedirs(assets_dir, exist_ok=True)
        os.makedirs(css_dir, exist_ok=True)

        # 2. Procesar Logo
        logo_dest = os.path.join(assets_dir, "logo.png")
        if client_data['logo_path'] and os.path.exists(client_data['logo_path']):
            shutil.copy(client_data['logo_path'], logo_dest)
        else:
            self._generate_fallback_logo(client_data.get('company_name', ''), design_profile, logo_dest)

        # 3. Generar QR premium para compartir (se envía por separado, no en la plantilla)
        full_url = final_url
        qr_path = os.path.join(assets_dir, "qr_share.png")
        self._generate_branded_qr(full_url, logo_dest, design_profile, qr_path)

        catalog_pdf_dest = os.path.join(assets_dir, "catalogo.pdf")
        has_catalog_pdf = False
        if client_data.get('catalog_pdf_path') and os.path.exists(client_data['catalog_pdf_path']):
            shutil.copy(client_data['catalog_pdf_path'], catalog_pdf_dest)
            has_catalog_pdf = True

        # 4. Generar CSS
        css_content = self._get_css_template(client_data['category'], design_profile)
        css_content += '\n' + (Path(__file__).parent / 'designs.css').read_text(encoding='utf-8')
        with open(os.path.join(css_dir, "style.css"), "w", encoding="utf-8") as f:
            f.write(css_content)

        # 5. Generar HTML
        html_content = self._get_html_template(client_data, design_profile, has_catalog_pdf=has_catalog_pdf)
        with open(os.path.join(client_dir, "index.html"), "w", encoding="utf-8") as f:
            f.write(html_content)

        # 6. Generar vCard para descarga y transferencia NFC
        vcard_content = self._build_vcard(client_data, full_url)
        with open(os.path.join(assets_dir, "contact.vcf"), "w", encoding="utf-8") as f:
            f.write(vcard_content)

        return qr_path

    def delete_generated_card(self, username):
        client_dir = self._get_client_dir(username)
        if client_dir.exists():
            shutil.rmtree(client_dir)
            return True
        return False

    def _extract_contact_details(self, client_data):
        email = (client_data.get('contact_email') or "").strip()
        phone = (client_data.get('contact_phone') or "").strip()
        website = (client_data.get('primary_website') or "").strip()
        maps = ""
        address = (client_data.get('physical_address') or "").strip()
        instagram = (client_data.get('primary_instagram') or "").strip()
        linkedin = (client_data.get('primary_linkedin') or "").strip()

        for link in client_data.get('links', []):
            if not link.get('active') or not link.get('url'):
                continue

            name = link.get('name', '')
            value = link.get('url', '').strip()

            if name == "Correo electrónico" and not email:
                email = value.replace("mailto:", "")
            elif name == "WhatsApp" and not phone:
                digits = re.sub(r"\D", "", value)
                phone = digits
            elif name == "Sitio Web" and not website:
                website = self._normalize_link_href(name, value)
            elif name == "Google Maps" and not maps:
                maps = self._normalize_link_href(name, value)

        return {
            "email": email,
            "phone": phone,
            "website": website,
            "maps": maps,
            "address": address,
            "instagram": instagram,
            "linkedin": linkedin,
        }

    def _build_vcard(self, client_data, website_url):
        contact = self._extract_contact_details(client_data)
        company_name = client_data.get('company_name', '').strip()
        full_name = (client_data.get('full_name') or "").strip() or company_name
        job_title = (client_data.get('job_title') or "").strip()
        username = self._sanitize_username(client_data.get('username', ''))

        name_parts = full_name.split()
        if len(name_parts) >= 2:
            family_name = name_parts[-1]
            given_names = " ".join(name_parts[:-1])
        else:
            family_name = full_name
            given_names = ""

        lines = [
            "BEGIN:VCARD",
            "VERSION:3.0",
            f"FN:{full_name}",
            f"N:{family_name};{given_names};;;",
            f"ORG:{company_name}",
            f"URL:{website_url}",
        ]

        if job_title:
            lines.append(f"TITLE:{job_title}")

        if contact["email"]:
            lines.append(f"EMAIL;TYPE=INTERNET:{contact['email']}")

        secondary_email = (client_data.get('secondary_email') or "").strip()
        if secondary_email:
            lines.append(f"EMAIL;TYPE=WORK:{secondary_email}")

        if contact["phone"]:
            phone_digits = re.sub(r"\D", "", contact['phone'])
            lines.append(f"TEL;TYPE=CELL:{phone_digits or contact['phone']}")

        secondary_phone = (client_data.get('secondary_phone') or "").strip()
        if secondary_phone:
            secondary_phone_digits = re.sub(r"\D", "", secondary_phone)
            lines.append(f"TEL;TYPE=WORK:{secondary_phone_digits or secondary_phone}")

        if contact["maps"]:
            lines.append(f"URL;TYPE=MAPS:{contact['maps']}")

        if contact["address"]:
            safe_address = contact["address"].replace(";", ",")
            lines.append(f"ADR;TYPE=WORK:;;{safe_address};;;;")

        if contact["instagram"]:
            lines.append(f"URL;TYPE=INSTAGRAM:{self._normalize_link_href('Instagram', contact['instagram'])}")

        if contact["linkedin"]:
            lines.append(f"URL;TYPE=LINKEDIN:{self._normalize_link_href('LinkedIn', contact['linkedin'])}")

        lines.extend([
            f"NOTE:Tarjeta digital generada para {username}",
            "END:VCARD",
            "",
        ])

        escaped_lines = []
        for line in lines:
            if ':' in line:
                key, value = line.split(':', 1)
                if key in {'FN', 'ORG', 'TITLE'}:
                    value = value.replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,')
                value = value.replace('\r\n', '\\n').replace('\n', '\\n').replace('\r', '\\n')
                line = key + ':' + value
            # Fold on UTF-8 boundaries at the vCard recommended line width.
            chunk = ''
            for char in line:
                if len((chunk + char).encode('utf-8')) > 75:
                    escaped_lines.append(chunk)
                    chunk = ' '
                chunk += char
            escaped_lines.append(chunk)
        return "\r\n".join(escaped_lines)

    def _normalize_link_href(self, name, value):
        value = (value or '').strip()
        if re.search(r'[\x00-\x20<>"\']', value) and ':' in value.split('/')[0]:
            return ''
        if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', value) and not re.match(r'^(https?://|mailto:|tel:)', value, re.I):
            return ''
        return escape(self._normalize_link_value(name, value), quote=True)

    def _normalize_link_value(self, name, value):
        name_key = (name or "").strip().lower()
        name_key = name_key.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
        value = value.strip()
        if not value:
            return ""

        if "correo" in name_key or name_key in {"email", "e-mail", "mail"}:
            if value.lower().startswith("mailto:"):
                return value
            return f"mailto:{value}"

        if name_key == "whatsapp":
            digits = re.sub(r"\D", "", value)
            if digits:
                return f"https://wa.me/{digits}"

        if name_key in {"telefono", "tel"}:
            digits = re.sub(r"\D", "", value)
            if digits:
                return f"tel:{digits}"

        if name_key == "telegram":
            if value.startswith("@"):
                value = value[1:]
            if value and "://" not in value:
                return f"https://t.me/{value}"

        if name_key == "google maps":
            if "://" not in value:
                return f"https://www.google.com/maps/search/{quote_plus(value)}"

        if name_key == "calendly":
            if value.startswith("@"):
                value = value[1:]
            if "://" not in value:
                return f"https://calendly.com/{value}"

        if name_key == "instagram":
            if value.startswith("@"):
                value = value[1:]
            if "://" not in value:
                return f"https://instagram.com/{value}"

        if name_key == "facebook":
            if value.startswith("@"):
                value = value[1:]
            if "://" not in value:
                return f"https://facebook.com/{value}"

        if name_key == "linkedin":
            if value.startswith("@"):
                value = value[1:]
            if "://" not in value:
                return f"https://www.linkedin.com/in/{value}"

        if name_key in {"x (twitter)", "x", "twitter"}:
            if value.startswith("@"):
                value = value[1:]
            if "://" not in value:
                return f"https://x.com/{value}"

        if name_key == "youtube":
            if value.startswith("@"):
                value = value[1:]
            if "://" not in value:
                return f"https://youtube.com/@{value}"

        if name_key == "tiktok":
            if value.startswith("@"):
                value = value[1:]
            if "://" not in value:
                return f"https://tiktok.com/@{value}"

        if name_key == "github":
            if value.startswith("@"):
                value = value[1:]
            if "://" not in value:
                return f"https://github.com/{value}"

        if name_key == "behance":
            if value.startswith("@"):
                value = value[1:]
            if "://" not in value:
                return f"https://www.behance.net/{value}"

        if name_key == "dribbble":
            if value.startswith("@"):
                value = value[1:]
            if "://" not in value:
                return f"https://dribbble.com/{value}"

        if name_key == "pinterest":
            if value.startswith("@"):
                value = value[1:]
            if "://" not in value:
                return f"https://www.pinterest.com/{value}"

        if name_key == "sitio web":
            if value.startswith("@"):
                value = value[1:]

        if "://" not in value and not value.startswith("mailto:"):
            if value.startswith("www.") or "." in value:
                return f"https://{value}"

        return value

    def _get_logo_initials(self, company_name):
        words = [chunk for chunk in re.split(r"\s+", (company_name or "").strip()) if chunk]
        if not words:
            return "DG"
        if len(words) == 1:
            token = words[0]
            return token[:2].upper() if len(token) > 1 else token[:1].upper()
        return f"{words[0][0]}{words[1][0]}".upper()

    def _hex_to_rgb(self, hex_color):
        cleaned = (hex_color or "#1f2937").strip().lstrip("#")
        if len(cleaned) != 6:
            cleaned = "1f2937"
        return tuple(int(cleaned[i:i+2], 16) for i in (0, 2, 4))

    def _generate_fallback_logo(self, company_name, design_profile, path):
        size = 720
        initials = self._get_logo_initials(company_name)
        start_color = self._hex_to_rgb(design_profile.get('accent', '#3B82F6'))
        end_color = self._hex_to_rgb(design_profile.get('accent_soft', '#06B6D4'))
        text_color = self._hex_to_rgb(design_profile.get('logo_text', '#FFFFFF'))

        img = Image.new("RGBA", (size, size), (8, 12, 22, 255))
        draw = ImageDraw.Draw(img)

        # Degradado vertical para un monograma premium y legible.
        for y in range(size):
            mix = y / max(size - 1, 1)
            r = int(start_color[0] * (1 - mix) + end_color[0] * mix)
            g = int(start_color[1] * (1 - mix) + end_color[1] * mix)
            b = int(start_color[2] * (1 - mix) + end_color[2] * mix)
            draw.line([(0, y), (size, y)], fill=(r, g, b, 255))

        ring_margin = int(size * 0.1)
        draw.ellipse(
            (ring_margin, ring_margin, size - ring_margin, size - ring_margin),
            outline=(255, 255, 255, 190),
            width=int(size * 0.03),
        )
        core_margin = int(size * 0.16)
        draw.ellipse(
            (core_margin, core_margin, size - core_margin, size - core_margin),
            fill=(12, 16, 28, 70),
        )

        font = self._load_fallback_font(size)
        bbox = draw.textbbox((0, 0), initials, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        text_x = (size - text_width) / 2 - bbox[0]
        text_y = (size - text_height) / 2 - bbox[1]

        shadow_offset = int(size * 0.008)
        draw.text((text_x + shadow_offset, text_y + shadow_offset), initials, fill=(0, 0, 0, 110), font=font)
        draw.text((text_x, text_y), initials, fill=(*text_color, 255), font=font)

        img.save(path)

    def _generate_branded_qr(self, full_url, logo_path, design_profile, output_path):
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=14,
            border=2,
        )
        qr.add_data(full_url)
        qr.make(fit=True)

        module_color = self._hex_to_rgb(design_profile.get('accent_soft', '#1f4b89'))
        qr_img = qr.make_image(fill_color=module_color, back_color='white').convert('RGBA')
        qr_size = qr_img.size[0]

        margin = 56
        canvas_size = qr_size + margin * 2
        canvas = Image.new('RGBA', (canvas_size, canvas_size), (255, 255, 255, 255))
        draw = ImageDraw.Draw(canvas)

        frame_color = self._hex_to_rgb(design_profile.get('accent', '#2b6cb0'))
        frame_soft = self._hex_to_rgb(design_profile.get('accent_soft', '#1a4f82'))

        draw.rounded_rectangle(
            (8, 8, canvas_size - 8, canvas_size - 8),
            radius=58,
            fill=(255, 255, 255, 255),
            outline=(*frame_soft, 220),
            width=10,
        )

        qr_pos = (margin, margin)
        canvas.alpha_composite(qr_img, qr_pos)

        if logo_path and os.path.exists(logo_path):
            resampling = getattr(Image, 'Resampling', Image)
            logo_size = int(qr_size * 0.23)
            logo = Image.open(logo_path).convert('RGBA').resize((logo_size, logo_size), resampling.LANCZOS)

            plate_size = logo_size + 34
            plate = Image.new('RGBA', (plate_size, plate_size), (255, 255, 255, 0))
            plate_draw = ImageDraw.Draw(plate)
            plate_draw.ellipse((0, 0, plate_size - 1, plate_size - 1), fill=(255, 255, 255, 245), outline=(*frame_color, 220), width=8)

            mask = Image.new('L', (logo_size, logo_size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, logo_size - 1, logo_size - 1), fill=255)

            logo_holder = Image.new('RGBA', (logo_size, logo_size), (255, 255, 255, 0))
            logo_holder.paste(logo, (0, 0), mask)
            logo_pos = ((plate_size - logo_size) // 2, (plate_size - logo_size) // 2)
            plate.alpha_composite(logo_holder, logo_pos)

            center_pos = ((canvas_size - plate_size) // 2, (canvas_size - plate_size) // 2)
            canvas.alpha_composite(plate, center_pos)

        final_img = Image.new('RGB', canvas.size, (255, 255, 255))
        final_img.paste(canvas, mask=canvas.split()[-1])
        final_img.save(output_path)

    def _load_fallback_font(self, size):
        candidates = [
            ("C:\\Windows\\Fonts\\georgiab.ttf", int(size * 0.30)),
            ("C:\\Windows\\Fonts\\segoeuib.ttf", int(size * 0.30)),
            ("C:\\Windows\\Fonts\\arialbd.ttf", int(size * 0.30)),
            ("C:\\Windows\\Fonts\\calibrib.ttf", int(size * 0.30)),
        ]

        for font_path, font_size in candidates:
            if os.path.exists(font_path):
                try:
                    return ImageFont.truetype(font_path, font_size)
                except Exception:
                    continue

        return ImageFont.load_default()

    def _get_design_profile(self, category, client_data):
        themes = {
            'abogados': [
                {
                    'style_name': 'Atelier Legal',
                    'layout': 'editorial',
                    'page_bg': '#0f1118',
                    'bg_gradient': 'radial-gradient(circle at 20% 15%, #2b1f17 0%, #0f1118 45%, #080a0f 100%)',
                    'surface': '#151b28',
                    'surface_alt': '#1c2434',
                    'text': '#f5f1e8',
                    'muted': '#c3b89f',
                    'accent': '#d7b67d',
                    'accent_soft': '#b98d52',
                    'ring': 'rgba(215, 182, 125, 0.45)',
                    'font_heading': "'Cormorant Garamond', serif",
                    'font_body': "'Manrope', sans-serif",
                    'logo_text': '#fff9ef',
                },
                {
                    'style_name': 'Firma Contemporanea',
                    'layout': 'neo',
                    'page_bg': '#0b101b',
                    'bg_gradient': 'radial-gradient(circle at 85% 10%, #3a2a14 0%, #121a2a 48%, #0b101b 100%)',
                    'surface': '#131d2f',
                    'surface_alt': '#19263c',
                    'text': '#edf2f8',
                    'muted': '#b6c5d7',
                    'accent': '#f3be6f',
                    'accent_soft': '#e28f37',
                    'ring': 'rgba(243, 190, 111, 0.38)',
                    'font_heading': "'Cormorant Garamond', serif",
                    'font_body': "'DM Sans', sans-serif",
                    'logo_text': '#ffffff',
                },
                {
                    'style_name': 'Lex Moderno',
                    'layout': 'luxe',
                    'page_bg': '#111318',
                    'bg_gradient': 'radial-gradient(circle at 12% 90%, #3a3027 0%, #171c26 45%, #111318 100%)',
                    'surface': '#1a1f2b',
                    'surface_alt': '#202738',
                    'text': '#f8f5ef',
                    'muted': '#bcb29f',
                    'accent': '#cfab73',
                    'accent_soft': '#8f6f43',
                    'ring': 'rgba(207, 171, 115, 0.36)',
                    'font_heading': "'Cormorant Garamond', serif",
                    'font_body': "'Manrope', sans-serif",
                    'logo_text': '#fff7ea',
                },
                {
                    'style_name': 'Greca Imperial Versage',
                    'layout': 'luxe',
                    'page_bg': '#171112',
                    'bg_gradient': 'radial-gradient(circle at 85% 8%, #6f4b1f 0%, #2a1c1d 42%, #171112 100%)',
                    'surface': '#24191b',
                    'surface_alt': '#2f2023',
                    'text': '#f8ede1',
                    'muted': '#dfb88c',
                    'accent': '#f4b860',
                    'accent_soft': '#b56d21',
                    'ring': 'rgba(244, 184, 96, 0.40)',
                    'font_heading': "'Cormorant Garamond', serif",
                    'font_body': "'DM Sans', sans-serif",
                    'logo_text': '#fff4dd',
                },
                {
                    'style_name': 'Rolex Signature',
                    'layout': 'editorial',
                    'page_bg': '#0d1614',
                    'bg_gradient': 'radial-gradient(circle at 22% 14%, #173028 0%, #10201d 45%, #0d1614 100%)',
                    'surface': '#11201d',
                    'surface_alt': '#19302a',
                    'text': '#eff6f2',
                    'muted': '#bdcdbf',
                    'accent': '#d8b55b',
                    'accent_soft': '#9a7b31',
                    'ring': 'rgba(216, 181, 91, 0.35)',
                    'font_heading': "'Cormorant Garamond', serif",
                    'font_body': "'Manrope', sans-serif",
                    'logo_text': '#fff6dd',
                },
                {
                    'style_name': 'Heritage Noir',
                    'layout': 'editorial',
                    'page_bg': '#0f1116',
                    'bg_gradient': 'radial-gradient(circle at 82% 12%, #3c2a1a 0%, #1c202b 46%, #0f1116 100%)',
                    'surface': '#151a24',
                    'surface_alt': '#1d2532',
                    'text': '#f2f4f8',
                    'muted': '#b9bfcb',
                    'accent': '#b89a6a',
                    'accent_soft': '#7d6744',
                    'ring': 'rgba(184, 154, 106, 0.34)',
                    'font_heading': "'Cormorant Garamond', serif",
                    'font_body': "'DM Sans', sans-serif",
                    'logo_text': '#fff7e8',
                },
                {
                    'style_name': 'Juris Royale',
                    'layout': 'luxe',
                    'page_bg': '#10131a',
                    'bg_gradient': 'radial-gradient(circle at 84% 10%, #4c3924 0%, #1d2532 45%, #10131a 100%)',
                    'surface': '#171f2d',
                    'surface_alt': '#232d3f',
                    'text': '#f3f4f7',
                    'muted': '#c0c5cf',
                    'accent': '#cba76f',
                    'accent_soft': '#896a3e',
                    'ring': 'rgba(203, 167, 111, 0.33)',
                    'font_heading': "'Cormorant Garamond', serif",
                    'font_body': "'Manrope', sans-serif",
                    'logo_text': '#fff7ea',
                },
            ],
            'ingenieria': [
                {
                    'style_name': 'Hyper Grid',
                    'layout': 'neo',
                    'page_bg': '#080f19',
                    'bg_gradient': 'radial-gradient(circle at 15% 20%, #05293d 0%, #0a1320 46%, #060a12 100%)',
                    'surface': '#0f1b2d',
                    'surface_alt': '#15263d',
                    'text': '#e8f4ff',
                    'muted': '#98b3c9',
                    'accent': '#4be4ff',
                    'accent_soft': '#2f9bd8',
                    'ring': 'rgba(75, 228, 255, 0.35)',
                    'font_heading': "'Space Grotesk', sans-serif",
                    'font_body': "'IBM Plex Sans', sans-serif",
                    'logo_text': '#f2fdff',
                },
                {
                    'style_name': 'Precise Systems',
                    'layout': 'editorial',
                    'page_bg': '#0b0e17',
                    'bg_gradient': 'radial-gradient(circle at 80% 8%, #0f2f35 0%, #111a2a 52%, #0b0e17 100%)',
                    'surface': '#131b2a',
                    'surface_alt': '#1a2438',
                    'text': '#ecf5fb',
                    'muted': '#9fb2bf',
                    'accent': '#59ffb4',
                    'accent_soft': '#2bbf82',
                    'ring': 'rgba(89, 255, 180, 0.34)',
                    'font_heading': "'Space Grotesk', sans-serif",
                    'font_body': "'Manrope', sans-serif",
                    'logo_text': '#f3fffb',
                },
                {
                    'style_name': 'Blueprint Vision',
                    'layout': 'luxe',
                    'page_bg': '#0a0f17',
                    'bg_gradient': 'radial-gradient(circle at 35% 90%, #11335a 0%, #11192a 48%, #0a0f17 100%)',
                    'surface': '#121f36',
                    'surface_alt': '#1a2e4a',
                    'text': '#e9f0ff',
                    'muted': '#9fb0d2',
                    'accent': '#7cc7ff',
                    'accent_soft': '#3d84cb',
                    'ring': 'rgba(124, 199, 255, 0.34)',
                    'font_heading': "'Space Grotesk', sans-serif",
                    'font_body': "'IBM Plex Sans', sans-serif",
                    'logo_text': '#f6fbff',
                },
                {
                    'style_name': 'Titanium Formal',
                    'layout': 'editorial',
                    'page_bg': '#101317',
                    'bg_gradient': 'radial-gradient(circle at 12% 88%, #2c3138 0%, #171d26 46%, #101317 100%)',
                    'surface': '#1a2028',
                    'surface_alt': '#242c37',
                    'text': '#edf1f6',
                    'muted': '#aeb8c6',
                    'accent': '#8ea2bc',
                    'accent_soft': '#5d6e84',
                    'ring': 'rgba(142, 162, 188, 0.33)',
                    'font_heading': "'Space Grotesk', sans-serif",
                    'font_body': "'Manrope', sans-serif",
                    'logo_text': '#f6f9ff',
                },
                {
                    'style_name': 'Neon Torque',
                    'layout': 'neo',
                    'page_bg': '#090c12',
                    'bg_gradient': 'radial-gradient(circle at 85% 12%, #4426aa 0%, #1a2242 44%, #090c12 100%)',
                    'surface': '#131b2f',
                    'surface_alt': '#1c2742',
                    'text': '#eef0ff',
                    'muted': '#b2b7e0',
                    'accent': '#b57dff',
                    'accent_soft': '#6b44cf',
                    'ring': 'rgba(181, 125, 255, 0.36)',
                    'font_heading': "'Space Grotesk', sans-serif",
                    'font_body': "'IBM Plex Sans', sans-serif",
                    'logo_text': '#f6f0ff',
                },
                {
                    'style_name': 'Vector Pulse',
                    'layout': 'luxe',
                    'page_bg': '#0a1019',
                    'bg_gradient': 'radial-gradient(circle at 86% 14%, #0d4b5e 0%, #13243a 46%, #0a1019 100%)',
                    'surface': '#111f33',
                    'surface_alt': '#1a2f49',
                    'text': '#eaf5ff',
                    'muted': '#a2bdd1',
                    'accent': '#39d5ff',
                    'accent_soft': '#1d8fb1',
                    'ring': 'rgba(57, 213, 255, 0.33)',
                    'font_heading': "'Space Grotesk', sans-serif",
                    'font_body': "'IBM Plex Sans', sans-serif",
                    'logo_text': '#f4fcff',
                },
                {
                    'style_name': 'Aero Matrix',
                    'layout': 'neo',
                    'page_bg': '#08111b',
                    'bg_gradient': 'radial-gradient(circle at 18% 85%, #1a4f6f 0%, #13263a 44%, #08111b 100%)',
                    'surface': '#102135',
                    'surface_alt': '#1a3048',
                    'text': '#e9f4ff',
                    'muted': '#a9c0d7',
                    'accent': '#58c3ff',
                    'accent_soft': '#2d7ab3',
                    'ring': 'rgba(88, 195, 255, 0.32)',
                    'font_heading': "'Space Grotesk', sans-serif",
                    'font_body': "'IBM Plex Sans', sans-serif",
                    'logo_text': '#f3faff',
                },
            ],
            'belleza': [
                {
                    'style_name': 'Rose Atelier',
                    'layout': 'luxe',
                    'page_bg': '#fff3f4',
                    'bg_gradient': 'radial-gradient(circle at 15% 12%, #ffdbe6 0%, #fff2f4 42%, #ffeef2 100%)',
                    'surface': '#fffafb',
                    'surface_alt': '#fff4f6',
                    'text': '#452f3f',
                    'muted': '#7f6172',
                    'accent': '#ff5fa8',
                    'accent_soft': '#e63c87',
                    'ring': 'rgba(255, 95, 168, 0.36)',
                    'font_heading': "'Fraunces', serif",
                    'font_body': "'Plus Jakarta Sans', sans-serif",
                    'logo_text': '#fff9ff',
                },
                {
                    'style_name': 'Soft Studio',
                    'layout': 'editorial',
                    'page_bg': '#fff5ef',
                    'bg_gradient': 'radial-gradient(circle at 85% 14%, #ffe0c9 0%, #fff7f1 45%, #fff2eb 100%)',
                    'surface': '#fffdfb',
                    'surface_alt': '#fff4ec',
                    'text': '#4a342e',
                    'muted': '#8f6f63',
                    'accent': '#ff7f66',
                    'accent_soft': '#d75d45',
                    'ring': 'rgba(255, 127, 102, 0.32)',
                    'font_heading': "'Fraunces', serif",
                    'font_body': "'Manrope', sans-serif",
                    'logo_text': '#fff9f5',
                },
                {
                    'style_name': 'Velvet Glow',
                    'layout': 'neo',
                    'page_bg': '#fff8fc',
                    'bg_gradient': 'radial-gradient(circle at 25% 90%, #ffcce3 0%, #fff3f9 42%, #fff9fc 100%)',
                    'surface': '#ffffff',
                    'surface_alt': '#fff2f8',
                    'text': '#4c2740',
                    'muted': '#8f6e82',
                    'accent': '#ff3e98',
                    'accent_soft': '#ca1f70',
                    'ring': 'rgba(255, 62, 152, 0.28)',
                    'font_heading': "'Fraunces', serif",
                    'font_body': "'Plus Jakarta Sans', sans-serif",
                    'logo_text': '#fff8ff',
                },
                {
                    'style_name': 'Runway Black',
                    'layout': 'luxe',
                    'page_bg': '#131217',
                    'bg_gradient': 'radial-gradient(circle at 18% 85%, #35213a 0%, #1e1a28 42%, #131217 100%)',
                    'surface': '#1a1720',
                    'surface_alt': '#251f31',
                    'text': '#f7f1ff',
                    'muted': '#c6b4d9',
                    'accent': '#ff8bd1',
                    'accent_soft': '#d35aa3',
                    'ring': 'rgba(255, 139, 209, 0.33)',
                    'font_heading': "'Fraunces', serif",
                    'font_body': "'Plus Jakarta Sans', sans-serif",
                    'logo_text': '#fff5ff',
                },
                {
                    'style_name': 'Luxe Champagne',
                    'layout': 'editorial',
                    'page_bg': '#fff8f0',
                    'bg_gradient': 'radial-gradient(circle at 84% 12%, #ffe4bf 0%, #fff6ea 44%, #fff8f0 100%)',
                    'surface': '#fffdf9',
                    'surface_alt': '#fff4e4',
                    'text': '#4d392d',
                    'muted': '#8b6f5d',
                    'accent': '#d89b4e',
                    'accent_soft': '#aa6f2d',
                    'ring': 'rgba(216, 155, 78, 0.30)',
                    'font_heading': "'Fraunces', serif",
                    'font_body': "'Manrope', sans-serif",
                    'logo_text': '#fffaf2',
                },
                {
                    'style_name': 'Pearl Bloom',
                    'layout': 'neo',
                    'page_bg': '#fff7fb',
                    'bg_gradient': 'radial-gradient(circle at 84% 12%, #ffd4f1 0%, #fff3fb 44%, #fff9fd 100%)',
                    'surface': '#ffffff',
                    'surface_alt': '#fff0f8',
                    'text': '#4a2e43',
                    'muted': '#896b82',
                    'accent': '#ff5fa8',
                    'accent_soft': '#c43d79',
                    'ring': 'rgba(255, 95, 168, 0.28)',
                    'font_heading': "'Fraunces', serif",
                    'font_body': "'Plus Jakarta Sans', sans-serif",
                    'logo_text': '#fff9ff',
                },
                {
                    'style_name': 'Opal Radiance',
                    'layout': 'editorial',
                    'page_bg': '#fff6fa',
                    'bg_gradient': 'radial-gradient(circle at 82% 12%, #ffd9ef 0%, #fff4fb 44%, #fff8fc 100%)',
                    'surface': '#ffffff',
                    'surface_alt': '#fff1f8',
                    'text': '#4b3042',
                    'muted': '#8c6f82',
                    'accent': '#ff6eb7',
                    'accent_soft': '#cd4d8f',
                    'ring': 'rgba(255, 110, 183, 0.29)',
                    'font_heading': "'Fraunces', serif",
                    'font_body': "'Plus Jakarta Sans', sans-serif",
                    'logo_text': '#fff9ff',
                },
            ],
            'nutricion': [
                {
                    'style_name': 'Organic Balance',
                    'layout': 'editorial',
                    'page_bg': '#f1f8ef',
                    'bg_gradient': 'radial-gradient(circle at 80% 8%, #d6f0cf 0%, #edf9e9 46%, #f5fbf2 100%)',
                    'surface': '#ffffff',
                    'surface_alt': '#f1f9ee',
                    'text': '#254034',
                    'muted': '#5f816f',
                    'accent': '#35b56a',
                    'accent_soft': '#1f8650',
                    'ring': 'rgba(53, 181, 106, 0.30)',
                    'font_heading': "'Sora', sans-serif",
                    'font_body': "'Manrope', sans-serif",
                    'logo_text': '#f7fff9',
                },
                {
                    'style_name': 'Fresh Clinical',
                    'layout': 'neo',
                    'page_bg': '#eefdf6',
                    'bg_gradient': 'radial-gradient(circle at 14% 18%, #cdf8e6 0%, #eefdF7 46%, #f4fff9 100%)',
                    'surface': '#ffffff',
                    'surface_alt': '#ebfaf3',
                    'text': '#1c3f3d',
                    'muted': '#5d7e7b',
                    'accent': '#16b7b1',
                    'accent_soft': '#0d8d89',
                    'ring': 'rgba(22, 183, 177, 0.30)',
                    'font_heading': "'Sora', sans-serif",
                    'font_body': "'IBM Plex Sans', sans-serif",
                    'logo_text': '#f0fffe',
                },
                {
                    'style_name': 'Wellness Prime',
                    'layout': 'luxe',
                    'page_bg': '#f3f9f0',
                    'bg_gradient': 'radial-gradient(circle at 25% 90%, #cfe9b8 0%, #edf7e6 42%, #f4faf2 100%)',
                    'surface': '#ffffff',
                    'surface_alt': '#f3f8ef',
                    'text': '#28452f',
                    'muted': '#5f7f63',
                    'accent': '#75b83f',
                    'accent_soft': '#4d8426',
                    'ring': 'rgba(117, 184, 63, 0.30)',
                    'font_heading': "'Sora', sans-serif",
                    'font_body': "'Manrope', sans-serif",
                    'logo_text': '#f9fff5',
                },
                {
                    'style_name': 'Bio Minimal',
                    'layout': 'editorial',
                    'page_bg': '#f6fbf6',
                    'bg_gradient': 'radial-gradient(circle at 16% 14%, #dcf3de 0%, #f5fbf4 44%, #f6fbf6 100%)',
                    'surface': '#ffffff',
                    'surface_alt': '#eef8ee',
                    'text': '#2e4632',
                    'muted': '#67826b',
                    'accent': '#5da55f',
                    'accent_soft': '#39783b',
                    'ring': 'rgba(93, 165, 95, 0.28)',
                    'font_heading': "'Sora', sans-serif",
                    'font_body': "'IBM Plex Sans', sans-serif",
                    'logo_text': '#f8fff8',
                },
                {
                    'style_name': 'Emerald Elite',
                    'layout': 'neo',
                    'page_bg': '#0f1d16',
                    'bg_gradient': 'radial-gradient(circle at 82% 10%, #1f4f3b 0%, #173126 42%, #0f1d16 100%)',
                    'surface': '#14261d',
                    'surface_alt': '#1d3428',
                    'text': '#e9f7ee',
                    'muted': '#b5d1bf',
                    'accent': '#74d69c',
                    'accent_soft': '#3e9b64',
                    'ring': 'rgba(116, 214, 156, 0.32)',
                    'font_heading': "'Sora', sans-serif",
                    'font_body': "'Manrope', sans-serif",
                    'logo_text': '#f2fff6',
                },
                {
                    'style_name': 'Citrus Zen',
                    'layout': 'editorial',
                    'page_bg': '#f9fbef',
                    'bg_gradient': 'radial-gradient(circle at 18% 14%, #e8f7bf 0%, #f6fbeb 44%, #fbfdf4 100%)',
                    'surface': '#ffffff',
                    'surface_alt': '#f4f9e7',
                    'text': '#314425',
                    'muted': '#71805f',
                    'accent': '#95c83d',
                    'accent_soft': '#678e24',
                    'ring': 'rgba(149, 200, 61, 0.30)',
                    'font_heading': "'Sora', sans-serif",
                    'font_body': "'IBM Plex Sans', sans-serif",
                    'logo_text': '#faffef',
                },
                {
                    'style_name': 'Pure Balance',
                    'layout': 'neo',
                    'page_bg': '#eef9f2',
                    'bg_gradient': 'radial-gradient(circle at 16% 14%, #d0f1dc 0%, #ecf8f1 45%, #eef9f2 100%)',
                    'surface': '#ffffff',
                    'surface_alt': '#eaf7ef',
                    'text': '#264235',
                    'muted': '#628175',
                    'accent': '#42ba84',
                    'accent_soft': '#2e8e64',
                    'ring': 'rgba(66, 186, 132, 0.29)',
                    'font_heading': "'Sora', sans-serif",
                    'font_body': "'IBM Plex Sans', sans-serif",
                    'logo_text': '#f7fff9',
                },
            ],
            'arquitectura': [
                {
                    'style_name': 'Concrete Studio',
                    'layout': 'neo',
                    'page_bg': '#f0f1f3',
                    'bg_gradient': 'radial-gradient(circle at 18% 20%, #d8dde5 0%, #f1f2f5 48%, #ebedf2 100%)',
                    'surface': '#ffffff',
                    'surface_alt': '#f4f5f7',
                    'text': '#1f2429',
                    'muted': '#5a626d',
                    'accent': '#3f566c',
                    'accent_soft': '#243848',
                    'ring': 'rgba(63, 86, 108, 0.30)',
                    'font_heading': "'Archivo', sans-serif",
                    'font_body': "'Manrope', sans-serif",
                    'logo_text': '#f9fcff',
                },
                {
                    'style_name': 'Spatial Minimal',
                    'layout': 'editorial',
                    'page_bg': '#f7f7f4',
                    'bg_gradient': 'radial-gradient(circle at 82% 10%, #e8e6de 0%, #f7f7f4 48%, #efeee9 100%)',
                    'surface': '#ffffff',
                    'surface_alt': '#f6f5f2',
                    'text': '#24231f',
                    'muted': '#666157',
                    'accent': '#806c53',
                    'accent_soft': '#564531',
                    'ring': 'rgba(128, 108, 83, 0.30)',
                    'font_heading': "'Archivo', sans-serif",
                    'font_body': "'IBM Plex Sans', sans-serif",
                    'logo_text': '#fbf8f2',
                },
                {
                    'style_name': 'Monolith Noir',
                    'layout': 'luxe',
                    'page_bg': '#111417',
                    'bg_gradient': 'radial-gradient(circle at 30% 85%, #2a323b 0%, #191f26 46%, #111417 100%)',
                    'surface': '#1a222b',
                    'surface_alt': '#212b35',
                    'text': '#edf0f3',
                    'muted': '#b3bec9',
                    'accent': '#9bb2c8',
                    'accent_soft': '#67839d',
                    'ring': 'rgba(155, 178, 200, 0.30)',
                    'font_heading': "'Archivo', sans-serif",
                    'font_body': "'Manrope', sans-serif",
                    'logo_text': '#f8fbff',
                },
                {
                    'style_name': 'Bauhaus Grid',
                    'layout': 'editorial',
                    'page_bg': '#f4f2ec',
                    'bg_gradient': 'radial-gradient(circle at 14% 82%, #ddd8cc 0%, #f4f2ec 45%, #efece3 100%)',
                    'surface': '#fcfaf5',
                    'surface_alt': '#ece8de',
                    'text': '#2b2a25',
                    'muted': '#6b675e',
                    'accent': '#9e7a4e',
                    'accent_soft': '#6d5234',
                    'ring': 'rgba(158, 122, 78, 0.30)',
                    'font_heading': "'Archivo', sans-serif",
                    'font_body': "'IBM Plex Sans', sans-serif",
                    'logo_text': '#fff8ed',
                },
                {
                    'style_name': 'Urban Prestige',
                    'layout': 'neo',
                    'page_bg': '#151619',
                    'bg_gradient': 'radial-gradient(circle at 80% 14%, #4e4f5d 0%, #232630 42%, #151619 100%)',
                    'surface': '#1d2028',
                    'surface_alt': '#292d39',
                    'text': '#f0f2f7',
                    'muted': '#bcc1cb',
                    'accent': '#c1a06f',
                    'accent_soft': '#8d7048',
                    'ring': 'rgba(193, 160, 111, 0.31)',
                    'font_heading': "'Archivo', sans-serif",
                    'font_body': "'Manrope', sans-serif",
                    'logo_text': '#fff8ef',
                },
                {
                    'style_name': 'Parametric Bronze',
                    'layout': 'luxe',
                    'page_bg': '#16151a',
                    'bg_gradient': 'radial-gradient(circle at 84% 10%, #5f4b38 0%, #26242c 44%, #16151a 100%)',
                    'surface': '#211f27',
                    'surface_alt': '#2f2c37',
                    'text': '#f2eef0',
                    'muted': '#c0b5ac',
                    'accent': '#c69a68',
                    'accent_soft': '#8d6945',
                    'ring': 'rgba(198, 154, 104, 0.31)',
                    'font_heading': "'Archivo', sans-serif",
                    'font_body': "'IBM Plex Sans', sans-serif",
                    'logo_text': '#fff6ec',
                },
                {
                    'style_name': 'Studio Slate',
                    'layout': 'editorial',
                    'page_bg': '#12171d',
                    'bg_gradient': 'radial-gradient(circle at 84% 10%, #3f5568 0%, #212d38 44%, #12171d 100%)',
                    'surface': '#1a2430',
                    'surface_alt': '#253240',
                    'text': '#eef2f5',
                    'muted': '#b5c1ca',
                    'accent': '#8caec8',
                    'accent_soft': '#627f97',
                    'ring': 'rgba(140, 174, 200, 0.30)',
                    'font_heading': "'Archivo', sans-serif",
                    'font_body': "'IBM Plex Sans', sans-serif",
                    'logo_text': '#f7fbff',
                },
            ],
        }

        variants = themes.get(category, themes['abogados'])
        line_choice = (client_data.get('design_line') or 'Auto').strip().lower()

        line_index_map = {
            'abogados': {
                'formal': [0, 4, 5, 6],
                'moderna': [1, 2, 6],
                'buchona': [3],
                'lujo': [3, 4, 5, 6],
                'minimalista': [0, 5, 6],
            },
            'ingenieria': {
                'formal': [3, 1, 5, 6],
                'moderna': [0, 2, 5, 6],
                'buchona': [4],
                'lujo': [2, 5, 6],
                'minimalista': [1, 5, 6],
            },
            'belleza': {
                'formal': [4, 5, 6],
                'moderna': [2, 0, 5, 6],
                'buchona': [3],
                'lujo': [0, 4, 5, 6],
                'minimalista': [1, 5, 6],
            },
            'nutricion': {
                'formal': [2, 3, 5, 6],
                'moderna': [1, 5, 6],
                'buchona': [4],
                'lujo': [4, 2, 5, 6],
                'minimalista': [3, 5, 6],
            },
            'arquitectura': {
                'formal': [1, 3, 5, 6],
                'moderna': [0, 4, 5, 6],
                'buchona': [2],
                'lujo': [4, 2, 5, 6],
                'minimalista': [3, 5, 6],
            },
        }

        candidate_variants = variants
        if line_choice != 'auto':
            idx_map = line_index_map.get(category, line_index_map['abogados'])
            selected_indices = idx_map.get(line_choice, [])
            filtered = [variants[idx] for idx in selected_indices if 0 <= idx < len(variants)]
            if filtered:
                candidate_variants = filtered

        variant_choice = (client_data.get('theme_variant') or 'Auto').strip().lower()
        if variant_choice.startswith('estilo'):
            variant_match = re.search(r"(\d+)", variant_choice)
            if variant_match:
                requested_index = int(variant_match.group(1)) - 1
                candidate_variants = variants
                variant_index = requested_index % len(variants)
            else:
                variant_index = 0
        else:
            seed = f"{category}:{client_data.get('username', '')}:{client_data.get('company_name', '')}".encode("utf-8")
            variant_index = int(hashlib.sha256(seed).hexdigest(), 16) % len(candidate_variants)
        profile = dict(candidate_variants[variant_index])
        profile['variant_index'] = variants.index(candidate_variants[variant_index])
        profile['category'] = category
        profile['design_line'] = line_choice
        if line_choice == 'buchona':
            profile = self._apply_buchona_palette(profile, category)
        return profile

    def _fix_encoding(self, text):
        """Fix corrupted characters from encoding issues."""
        if not text:
            return text
        # Map of common encoding corruption patterns
        replacements = {
            "asesor?a": "asesoría",
            "?": "í",
            "á": "á",
            "é": "é",
            "ó": "ó",
            "ú": "ú",
            "ñ": "ñ",
        }
        result = text
        for broken, fixed in replacements.items():
            result = result.replace(broken, fixed)
        return result

    def _style_slug(self, style_name):
        slug = re.sub(r"[^a-z0-9]+", "-", (style_name or "").lower())
        return slug.strip("-") or "default-style"

    def _apply_buchona_palette(self, profile, category):
        dark_gold = {
            'abogados': {
                'page_bg': '#120f12',
                'bg_gradient': 'radial-gradient(circle at 78% 8%, #6f4a1e 0%, #2a1d1f 42%, #120f12 100%)',
                'surface': '#1f1719',
                'surface_alt': '#2a1f22',
                'text': '#f6eee4',
                'muted': '#d9bd96',
                'accent': '#f2be71',
                'accent_soft': '#b7742d',
                'ring': 'rgba(242, 190, 113, 0.38)',
                'logo_text': '#fff7ea',
            },
            'ingenieria': {
                'page_bg': '#12131a',
                'bg_gradient': 'radial-gradient(circle at 15% 85%, #664321 0%, #212531 44%, #12131a 100%)',
                'surface': '#1c1f2a',
                'surface_alt': '#272d3b',
                'text': '#f2edf1',
                'muted': '#ceb897',
                'accent': '#edb86f',
                'accent_soft': '#9c7140',
                'ring': 'rgba(237, 184, 111, 0.34)',
                'logo_text': '#fff8ee',
            },
            'belleza': {
                'page_bg': '#1a1217',
                'bg_gradient': 'radial-gradient(circle at 84% 10%, #7b4a27 0%, #2c1d2a 40%, #1a1217 100%)',
                'surface': '#241925',
                'surface_alt': '#322333',
                'text': '#f8eef2',
                'muted': '#e0c19b',
                'accent': '#f4c27d',
                'accent_soft': '#b17842',
                'ring': 'rgba(244, 194, 125, 0.35)',
                'logo_text': '#fff8ee',
            },
            'nutricion': {
                'page_bg': '#121912',
                'bg_gradient': 'radial-gradient(circle at 22% 12%, #79512a 0%, #212b21 43%, #121912 100%)',
                'surface': '#1b251b',
                'surface_alt': '#283428',
                'text': '#edf5ea',
                'muted': '#dbc299',
                'accent': '#f0c27b',
                'accent_soft': '#a77b45',
                'ring': 'rgba(240, 194, 123, 0.33)',
                'logo_text': '#fbfff6',
            },
            'arquitectura': {
                'page_bg': '#181618',
                'bg_gradient': 'radial-gradient(circle at 82% 12%, #72502d 0%, #2a272e 41%, #181618 100%)',
                'surface': '#232026',
                'surface_alt': '#302c36',
                'text': '#f1eef2',
                'muted': '#d8c09b',
                'accent': '#eebf79',
                'accent_soft': '#9d7446',
                'ring': 'rgba(238, 191, 121, 0.33)',
                'logo_text': '#fff9f0',
            },
        }
        selected = dark_gold.get(category, dark_gold['abogados'])
        profile.update(selected)
        return profile

    def _get_css_template(self, category, design_profile):
        p = design_profile
        is_light_surface = p.get('page_bg', '#000000').startswith('#f')
        page_text = '#152232' if is_light_surface else '#e7eef7'

        return f"""
/* --- ESTILO PREMIUM: {category.upper()} / {p['style_name']} --- */
:root {{
    --page-bg: {p['page_bg']};
    --page-gradient: {p['bg_gradient']};
    --surface: {p['surface']};
    --surface-alt: {p['surface_alt']};
    --text-color: {p['text']};
    --muted-color: {p['muted']};
    --accent-color: {p['accent']};
    --accent-soft: {p['accent_soft']};
    --ring-color: {p['ring']};
    --body-copy: {p['font_body']};
    --display-copy: {p['font_heading']};
}}

* {{
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}}

body {{
    background: var(--page-bg);
    background-image: var(--page-gradient);
    color: {page_text};
    font-family: var(--body-copy);
    min-height: 100vh;
    display: flex;
    justify-content: center;
    align-items: center;
    padding: 24px 14px;
    overflow-x: hidden;
}}

body::before,
body::after {{
    content: "";
    position: fixed;
    border-radius: 999px;
    pointer-events: none;
    z-index: 0;
    filter: blur(48px);
}}

body::before {{
    width: min(48vw, 420px);
    height: min(48vw, 420px);
    top: -120px;
    left: -80px;
    background: color-mix(in srgb, var(--accent-color) 45%, transparent);
    opacity: 0.32;
}}

body::after {{
    width: min(56vw, 560px);
    height: min(56vw, 560px);
    bottom: -220px;
    right: -170px;
    background: color-mix(in srgb, var(--accent-soft) 55%, transparent);
    opacity: 0.25;
}}

.card-container {{
    width: min(100%, 478px);
    background: linear-gradient(180deg, var(--surface) 0%, color-mix(in srgb, var(--surface) 82%, var(--surface-alt)) 100%);
    border: 1px solid color-mix(in srgb, var(--accent-color) 22%, transparent);
    border-radius: 32px;
    box-shadow: 0 32px 70px rgba(9, 13, 22, 0.34);
    position: relative;
    z-index: 1;
    padding: 32px 22px 26px;
    overflow: hidden;
    color: var(--text-color);
}}

body.buchona-global .card-container {{
    border-top: 7px solid color-mix(in srgb, var(--accent-color) 88%, #f2c885);
    border-bottom: 7px solid color-mix(in srgb, var(--accent-color) 88%, #f2c885);
}}

body.buchona-global .card-container::after {{
    content: "";
    position: absolute;
    inset: 10px;
    border-radius: 26px;
    pointer-events: none;
    border: 2px solid color-mix(in srgb, var(--accent-color) 86%, #d28a2d);
    background-image:
        repeating-linear-gradient(90deg, color-mix(in srgb, var(--accent-color) 66%, transparent) 0 10px, transparent 10px 18px),
        repeating-linear-gradient(90deg, color-mix(in srgb, var(--accent-color) 66%, transparent) 0 10px, transparent 10px 18px);
    background-position: top center, bottom center;
    background-size: 100% 7px, 100% 7px;
    background-repeat: no-repeat;
    opacity: 0.48;
}}

.card-container::before {{
    display: none;
}}

body.buchona-global .card-container::before {{
    content: "";
    position: absolute;
    inset: 0;
    border-radius: 32px;
    pointer-events: none;
    background-image:
        repeating-linear-gradient(90deg, color-mix(in srgb, var(--accent-color) 66%, transparent) 0 10px, transparent 10px 18px),
        repeating-linear-gradient(90deg, color-mix(in srgb, var(--accent-color) 66%, transparent) 0 10px, transparent 10px 18px);
    background-position: top center, bottom center;
    background-size: 100% 7px, 100% 7px;
    background-repeat: no-repeat;
    opacity: 0.55;
}}

.card-container > * {{
    position: relative;
    z-index: 2;
}}

.chip-row {{
    width: 100%;
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    margin: 0 auto 16px;
}}

.design-chip {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 7px 12px;
    border-radius: 999px;
    border: 1px solid color-mix(in srgb, var(--accent-color) 45%, transparent);
    background: color-mix(in srgb, var(--surface-alt) 85%, transparent);
    color: var(--muted-color);
    font-size: 0.74rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin: 0;
}}

.category-chip {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    border-radius: 999px;
    border: 1px solid color-mix(in srgb, var(--accent-color) 45%, transparent);
    background: color-mix(in srgb, var(--accent-color) 14%, transparent);
    color: var(--text-color);
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin: 0;
}}

.logo-container {{
    display: flex;
    justify-content: center;
    margin: 0 auto 18px;
    width: fit-content;
    position: relative;
    padding: 10px;
    border-radius: 34px;
}}

.logo-container img {{
    width: 124px;
    height: 124px;
    border-radius: 30px;
    object-fit: cover;
    object-position: center var(--logo-position, 50%);
    border: 3px solid color-mix(in srgb, var(--accent-color) 70%, white 10%);
    box-shadow: 0 12px 28px color-mix(in srgb, var(--accent-soft) 28%, transparent);
}}

body.buchona-global .logo-container {{
    padding: 16px;
}}

body.buchona-global .logo-container::before {{
    display: none;
}}

body.buchona-global .logo-container::after {{
    display: none;
}}

.info {{
    text-align: center;
    margin-bottom: 22px;
}}

h1 {{
    font-family: var(--display-copy);
    font-size: clamp(2.0rem, 6vw, 2.65rem);
    line-height: 1.03;
    letter-spacing: 0.01em;
    color: var(--text-color);
    margin-bottom: 10px;
    text-wrap: balance;
}}

.bio {{
    color: var(--muted-color);
    font-size: 0.98rem;
    line-height: 1.6;
    max-width: 36ch;
    margin: 0 auto;
    text-wrap: pretty;
}}

.meta-grid {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    justify-content: center;
    margin-top: 18px;
}}

.meta-chip {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    min-height: 38px;
    padding: 8px 13px;
    border-radius: 14px;
    border: 1px solid color-mix(in srgb, var(--accent-color) 20%, transparent);
    background: color-mix(in srgb, var(--surface-alt) 82%, transparent);
    color: var(--text-color);
    font-size: 0.83rem;
}}

.meta-chip--wide {{
    width: min(100%, 100%);
    justify-content: center;
}}

.section-title {{
    margin: 24px 0 12px;
    color: var(--muted-color);
    font-size: 0.74rem;
    font-weight: 700;
    letter-spacing: 0.18em;
    text-transform: uppercase;
}}

.action-group,
.links {{
    display: flex;
    flex-direction: column;
    gap: 11px;
}}

.link-btn {{
    --link-brand: var(--accent-color);
    --link-brand-soft: color-mix(in srgb, var(--link-brand) 24%, transparent);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    min-height: 50px;
    padding: 12px 16px;
    border-radius: 14px;
    position: relative;
    isolation: isolate;
    overflow: hidden;
    border: 1px solid color-mix(in srgb, var(--link-brand) 34%, transparent);
    background: linear-gradient(160deg, color-mix(in srgb, var(--surface-alt) 84%, var(--link-brand-soft)), color-mix(in srgb, var(--surface) 88%, transparent));
    color: var(--text-color);
    font-weight: 700;
    letter-spacing: 0.01em;
    text-decoration: none;
    box-shadow: 0 8px 22px color-mix(in srgb, var(--link-brand) 16%, transparent);
    transition: transform 0.22s ease, background-color 0.25s ease, border-color 0.25s ease, box-shadow 0.25s ease, color 0.25s ease;
}}

.link-btn::before {{
    content: "";
    position: absolute;
    inset: 0;
    z-index: -1;
    opacity: 0;
    background: linear-gradient(135deg, color-mix(in srgb, var(--link-brand) 88%, white 8%) 0%, color-mix(in srgb, var(--link-brand) 56%, #09111f) 100%);
    transition: opacity 0.24s ease;
}}

.link-btn > * {{
    position: relative;
    z-index: 1;
}}

.link-btn:hover {{
    transform: translateY(-2px);
    color: white;
    border-color: color-mix(in srgb, var(--link-brand) 84%, white 8%);
    box-shadow: 0 14px 28px color-mix(in srgb, var(--link-brand) 42%, transparent);
}}

.link-btn:hover::before {{
    opacity: 1;
}}

.link-btn i {{
    color: var(--link-brand);
    transition: color 0.25s ease;
}}

.link-btn:hover i {{
    color: white;
}}

.link-btn.link-whatsapp {{ --link-brand: #25d366; }}
.link-btn.link-facebook {{ --link-brand: #1877f2; }}
.link-btn.link-youtube {{ --link-brand: #ff0000; }}
.link-btn.link-linkedin {{ --link-brand: #0a66c2; }}
.link-btn.link-tiktok {{ --link-brand: #fe2c55; }}
.link-btn.link-github {{ --link-brand: #8b949e; }}
.link-btn.link-x {{ --link-brand: #111111; }}
.link-btn.link-telegram {{ --link-brand: #229ed9; }}
.link-btn.link-email {{ --link-brand: #ea4335; }}
.link-btn.link-web {{ --link-brand: #22b8cf; }}
.link-btn.link-maps {{ --link-brand: #34a853; }}
.link-btn.link-phone {{ --link-brand: #7f8c9a; }}
.link-btn.link-calendly {{ --link-brand: #006bff; }}
.link-btn.link-behance {{ --link-brand: #1769ff; }}
.link-btn.link-dribbble {{ --link-brand: #ea4c89; }}
.link-btn.link-pinterest {{ --link-brand: #bd081c; }}
.link-btn.link-pdf {{ --link-brand: #d93025; }}

.link-btn.link-instagram {{
    --link-brand: #dd2a7b;
    background: linear-gradient(160deg, color-mix(in srgb, var(--surface-alt) 78%, rgba(245,133,41,0.18)), color-mix(in srgb, var(--surface) 88%, rgba(129,52,175,0.18)));
}}

.link-btn.link-instagram::before {{
    background: linear-gradient(135deg, #f58529 0%, #feda77 18%, #dd2a7b 52%, #8134af 78%, #515bd4 100%);
}}

.link-btn.link-whatsapp i {{ color: #25d366; }}
.link-btn.link-facebook i {{ color: #1877f2; }}
.link-btn.link-youtube i {{ color: #ff0000; }}
.link-btn.link-linkedin i {{ color: #0a66c2; }}
.link-btn.link-tiktok i {{ color: #fe2c55; }}
.link-btn.link-github i {{ color: #8b949e; }}
.link-btn.link-x i {{ color: #e8eaed; }}
.link-btn.link-telegram i {{ color: #229ed9; }}
.link-btn.link-email i {{ color: #ea4335; }}
.link-btn.link-web i {{ color: #22b8cf; }}
.link-btn.link-maps i {{ color: #34a853; }}
.link-btn.link-phone i {{ color: #7f8c9a; }}
.link-btn.link-calendly i {{ color: #006bff; }}
.link-btn.link-behance i {{ color: #1769ff; }}
.link-btn.link-dribbble i {{ color: #ea4c89; }}
.link-btn.link-pinterest i {{ color: #bd081c; }}
.link-btn.link-pdf i {{ color: #d93025; }}

.link-btn.link-instagram i {{
    background: linear-gradient(45deg, #f58529, #feda77, #dd2a7b, #8134af, #515bd4);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    color: transparent;
}}

body.layout-editorial .card-container {{
    border-radius: 20px;
    border-top: 6px solid var(--accent-color);
}}

body.layout-editorial .logo-container img {{
    border-radius: 22px;
}}

body.layout-neo .card-container {{
    backdrop-filter: blur(18px);
}}

body.layout-neo .link-btn {{
    border-radius: 16px;
}}

body.layout-luxe .card-container {{
    border-radius: 34px;
    box-shadow: 0 30px 85px rgba(8, 11, 19, 0.42);
}}

body.layout-luxe .section-title {{
    letter-spacing: 0.2em;
}}

body.category-abogados .card-container {{
    border-top: 6px solid color-mix(in srgb, var(--accent-color) 88%, #f2d3a0);
}}

body.style-greca-imperial-versage .card-container {{
    border-top: 8px solid color-mix(in srgb, var(--accent-color) 88%, #f6ca82);
    border-bottom: 8px solid color-mix(in srgb, var(--accent-color) 88%, #f6ca82);
}}

body.buchona-global.style-greca-imperial-versage .card-container::after {{
    content: "";
    position: absolute;
    inset: 10px;
    border-radius: 26px;
    pointer-events: none;
    border: 2px solid color-mix(in srgb, var(--accent-color) 85%, #d88a24);
    background-image:
        repeating-linear-gradient(90deg, color-mix(in srgb, var(--accent-color) 65%, transparent) 0 10px, transparent 10px 18px),
        repeating-linear-gradient(90deg, color-mix(in srgb, var(--accent-color) 65%, transparent) 0 10px, transparent 10px 18px);
    background-position: top center, bottom center;
    background-size: 100% 7px, 100% 7px;
    background-repeat: no-repeat;
    opacity: 0.5;
}}

body.category-abogados .chip-row {{
    gap: 10px;
    margin-bottom: 18px;
}}

body.category-abogados .design-chip {{
    letter-spacing: 0.16em;
    border-color: color-mix(in srgb, var(--accent-color) 70%, transparent);
    background: color-mix(in srgb, var(--surface-alt) 78%, #0f1728);
}}

body.category-abogados .category-chip {{
    border-color: color-mix(in srgb, var(--accent-color) 76%, transparent);
    background: linear-gradient(145deg, color-mix(in srgb, var(--accent-color) 20%, transparent), color-mix(in srgb, var(--surface-alt) 90%, transparent));
}}

body.category-abogados .logo-container img {{
    width: 132px;
    height: 132px;
    border-radius: 50%;
    border-width: 4px;
}}

body.category-abogados h1 {{
    font-size: clamp(2.18rem, 6vw, 2.9rem);
    letter-spacing: 0.02em;
}}

body.category-abogados .section-title {{
    display: flex;
    align-items: center;
    gap: 10px;
}}

body.category-abogados .section-title::after {{
    content: "";
    flex: 1;
    height: 1px;
    background: linear-gradient(90deg, color-mix(in srgb, var(--accent-color) 56%, transparent), transparent);
}}

body.category-abogados .link-btn {{
    border-color: color-mix(in srgb, var(--link-brand) 52%, transparent);
    background: linear-gradient(160deg, color-mix(in srgb, var(--surface-alt) 82%, var(--link-brand-soft)), color-mix(in srgb, var(--surface) 88%, #121a2c));
}}

body.category-abogados .link-btn:hover {{
    box-shadow: 0 12px 26px color-mix(in srgb, var(--link-brand) 42%, transparent);
}}

body.category-ingenieria .design-chip {{
    letter-spacing: 0.16em;
}}

body.category-belleza .category-chip {{
    border-color: color-mix(in srgb, var(--accent-color) 60%, transparent);
}}

body.category-arquitectura .card-container {{
    border-radius: 16px;
}}

@media (max-width: 560px) {{
    body {{
        padding: 10px 8px;
    }}

    .card-container {{
        width: 100%;
        border-radius: 24px;
        padding: 26px 16px 20px;
    }}

    .logo-container img {{
        width: 108px;
        height: 108px;
    }}

    .section-title {{
        margin-top: 20px;
    }}
}}
"""

    def _get_category_customization(self, category):
        custom = {
            'abogados': {
                'chip': 'Legal Premium',
                'chip_icon': 'fas fa-scale-balanced',
                'bio_fallback': 'Estrategia legal con enfoque de resultados y reputacion empresarial.',
                'profiles_title': 'Perfiles Profesionales',
                'links_title': 'Canales de Atencion',
                'actions_title': 'Recursos Legales',
                'contact_label': 'Guardar contacto legal',
                'catalog_label': 'Brochure de servicios',
                'qr_text': 'Escanea para tu asesoria',
                'footer': 'Confianza, precision y prestigio en cada caso.',
                'instagram_label': 'Instagram del despacho',
                'linkedin_label': 'LinkedIn del despacho',
                'priority_links': ['WhatsApp', 'Teléfono', 'Correo electrónico', 'Sitio Web', 'LinkedIn'],
            },
            'ingenieria': {
                'chip': 'Engineering Lab',
                'chip_icon': 'fas fa-microchip',
                'bio_fallback': 'Soluciones tecnicas y ejecucion precisa para proyectos de alto impacto.',
                'profiles_title': 'Perfiles Tecnicos',
                'links_title': 'Canales Tecnicos',
                'actions_title': 'Material Tecnico',
                'contact_label': 'Guardar contacto tecnico',
                'catalog_label': 'Ficha tecnica PDF',
                'qr_text': 'Escanea para especificaciones',
                'footer': 'Ingenieria aplicada, resultados medibles.',
                'instagram_label': 'Instagram del proyecto',
                'linkedin_label': 'LinkedIn profesional',
                'priority_links': ['Sitio Web', 'GitHub', 'LinkedIn', 'YouTube', 'WhatsApp'],
            },
            'belleza': {
                'chip': 'Beauty Signature',
                'chip_icon': 'fas fa-spa',
                'bio_fallback': 'Experiencias de belleza con identidad visual impecable y trato premium.',
                'profiles_title': 'Perfiles de Marca',
                'links_title': 'Agenda y Redes',
                'actions_title': 'Experiencia de Marca',
                'contact_label': 'Guardar contacto del estudio',
                'catalog_label': 'Lookbook PDF',
                'qr_text': 'Escanea y agenda tu cita',
                'footer': 'Estetica, detalle y estilo en cada servicio.',
                'instagram_label': 'Instagram principal',
                'linkedin_label': 'LinkedIn de marca',
                'priority_links': ['Instagram', 'TikTok', 'WhatsApp', 'Facebook', 'Sitio Web'],
            },
            'nutricion': {
                'chip': 'Wellness Studio',
                'chip_icon': 'fas fa-leaf',
                'bio_fallback': 'Planes de bienestar y nutricion con enfoque humano y acompanamiento real.',
                'profiles_title': 'Perfiles de Especialista',
                'links_title': 'Canales de Bienestar',
                'actions_title': 'Recursos de Consulta',
                'contact_label': 'Guardar contacto nutricional',
                'catalog_label': 'Guia de planes PDF',
                'qr_text': 'Escanea para tu plan personalizado',
                'footer': 'Salud sostenible, resultados consistentes.',
                'instagram_label': 'Instagram saludable',
                'linkedin_label': 'LinkedIn profesional',
                'priority_links': ['WhatsApp', 'Calendly', 'Instagram', 'Sitio Web', 'Google Maps'],
            },
            'arquitectura': {
                'chip': 'Architecture Studio',
                'chip_icon': 'fas fa-drafting-compass',
                'bio_fallback': 'Diseno arquitectonico con vision espacial, tecnica y materialidad contemporanea.',
                'profiles_title': 'Perfiles del Estudio',
                'links_title': 'Portafolio y Contacto',
                'actions_title': 'Recursos del Estudio',
                'contact_label': 'Guardar contacto del estudio',
                'catalog_label': 'Portafolio PDF',
                'qr_text': 'Escanea para ver el portafolio',
                'footer': 'Espacios pensados para durar y destacar.',
                'instagram_label': 'Instagram del estudio',
                'linkedin_label': 'LinkedIn del estudio',
                'priority_links': ['Sitio Web', 'Behance', 'Dribbble', 'Pinterest', 'WhatsApp'],
            },
        }
        return custom.get(category, custom['abogados'])

    def _order_links_by_category(self, links, customization):
        priorities = customization.get('priority_links', [])
        priority_index = {name: idx for idx, name in enumerate(priorities)}

        def sort_key(link):
            name = link.get('name', '')
            return (priority_index.get(name, len(priorities) + 99), name.lower())

        return sorted(links, key=sort_key)

    def _get_html_template(self, data, design_profile, has_catalog_pdf=False):
        category = (data.get('category') or 'abogados').strip().lower()
        customization = self._get_category_customization(category)
        safe_company = escape(data['company_name'])
        raw_bio = (data.get('bio') or '').strip() or customization['bio_fallback']
        safe_bio = escape(raw_bio)
        safe_bio = self._fix_encoding(safe_bio)
        safe_full_name = escape((data.get('full_name') or "").strip())
        safe_job_title = escape((data.get('job_title') or "").strip())
        safe_address = escape((data.get('physical_address') or "").strip())
        primary_instagram_href = self._normalize_link_href("Instagram", data.get('primary_instagram') or "")
        primary_linkedin_href = self._normalize_link_href("LinkedIn", data.get('primary_linkedin') or "")

        meta_items = []
        if safe_full_name:
            meta_items.append(f'<span class="meta-chip"><i class="fas fa-user"></i> {safe_full_name}</span>')
        if safe_job_title:
            meta_items.append(f'<span class="meta-chip"><i class="fas fa-briefcase"></i> {safe_job_title}</span>')
        if safe_address:
            meta_items.append(f'<span class="meta-chip meta-chip--wide"><i class="fas fa-location-dot"></i> {safe_address}</span>')

        meta_html = ""
        if meta_items:
            meta_html = f"""
        <div class="meta-grid">
            {' '.join(meta_items)}
        </div>
"""

        active_links = [link for link in data['links'] if link.get('active') and link.get('url')]
        phone_link = next((link for link in active_links if link.get('name') == 'WhatsApp'), None)
        if phone_link is None:
            phone_link = next((link for link in active_links if link.get('name') == 'Teléfono'), None)

        contact_phone_raw = (data.get('contact_phone') or '').strip()
        profile_phone_href = ""
        profile_phone_label = ""
        profile_phone_icon = ""
        if phone_link:
            profile_phone_href = self._normalize_link_href(phone_link.get('name', 'WhatsApp'), phone_link.get('url', ''))
            profile_phone_label = "WhatsApp directo" if phone_link.get('name') == 'WhatsApp' else "Llamada directa"
            profile_phone_icon = "fab fa-whatsapp" if phone_link.get('name') == 'WhatsApp' else "fas fa-phone"
        elif contact_phone_raw:
            profile_phone_href = self._normalize_link_href("Teléfono", contact_phone_raw)
            profile_phone_label = "Llamada directa"
            profile_phone_icon = "fas fa-phone"

        primary_profile_html = ""
        if profile_phone_href:
            profile_phone_name = phone_link.get('name', 'Teléfono') if phone_link else 'Teléfono'
            profile_phone_class = self._get_link_style_class(profile_phone_name)
            primary_profile_html += f"""
        <a href="{profile_phone_href}" class="link-btn{profile_phone_class}" target="_blank" rel="noopener noreferrer">
            <i class="{profile_phone_icon}"></i> {profile_phone_label}
        </a>
"""

        hidden_link_names = set()
        if profile_phone_href:
            hidden_link_names.update({"WhatsApp", "Teléfono"})

        if primary_instagram_href:
            hidden_link_names.add("Instagram")
            instagram_class = self._get_link_style_class("Instagram")
            primary_profile_html += f"""
        <a href="{primary_instagram_href}" class="link-btn{instagram_class}" target="_blank" rel="noopener noreferrer">
            <i class="fab fa-instagram"></i> {escape(customization['instagram_label'])}
        </a>
"""
        if primary_linkedin_href:
            hidden_link_names.add("LinkedIn")
            linkedin_class = self._get_link_style_class("LinkedIn")
            primary_profile_html += f"""
        <a href="{primary_linkedin_href}" class="link-btn{linkedin_class}" target="_blank" rel="noopener noreferrer">
            <i class="fab fa-linkedin-in"></i> {escape(customization['linkedin_label'])}
        </a>
"""

        primary_profiles_section = f"""
        <section class="profiles-section">
            <p class="section-title">{escape(customization['profiles_title'])}</p>
            <nav class="links action-group">
            {primary_profile_html}
            </nav>
        </section>
""" if primary_profile_html else ""

        links_html = ""
        ordered_links = self._order_links_by_category(active_links, customization)
        for link in ordered_links:
            if link.get('name') in hidden_link_names:
                continue
            icon = self._get_icon(link['name'])
            href = self._normalize_link_href(link['name'], link['url'])
            safe_name = escape(link['name'])
            link_class = self._get_link_style_class(link['name'])
            links_html += f"""
        <!-- AI: Link {safe_name} -->
        <a href="{href}" class="link-btn{link_class}" target="_blank" rel="noopener noreferrer">
            <i class="{icon}"></i> {safe_name}
        </a>
"""

        if has_catalog_pdf:
            pdf_class = self._get_link_style_class("catalogo")
            links_html += f"""
        <a href="./assets/catalogo.pdf" class="link-btn{pdf_class}" download>
            <i class="fas fa-file-pdf"></i> {escape(customization['catalog_label'])}
        </a>
"""

        links_section = f"""
        <section class="channels-section">
            <p class="section-title">{escape(customization['links_title'])}</p>
            <nav class="links action-group">
            {links_html}
            </nav>
        </section>
""" if links_html else ""

        safe_design_name = escape(design_profile.get('style_name', 'Signature'))
        layout_class = escape(design_profile.get('layout', 'neo'))
        safe_chip = escape(customization.get('chip', 'Premium Profile'))
        safe_chip_icon = escape(customization.get('chip_icon', 'fas fa-award'))
        safe_category_class = escape(category)
        safe_style_class = escape(self._style_slug(design_profile.get('style_name', 'default-style')))

        return f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{safe_company} - Tarjeta Digital</title>
    <!-- AI: Fonts -->
    <link href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;700;800&family=Cormorant+Garamond:wght@600;700&family=DM+Sans:wght@400;500;700&family=Fraunces:opsz,wght@9..144,600;9..144,700&family=IBM+Plex+Sans:wght@400;500;700&family=Manrope:wght@400;500;700;800&family=Plus+Jakarta+Sans:wght@400;500;700;800&family=Sora:wght@400;600;700&family=Space+Grotesk:wght@500;700&display=swap" rel="stylesheet">
    <!-- AI: Icons -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link rel="stylesheet" href="./css/style.css">
</head>
<body class="composition-{int(design_profile.get('variant_index',0))+1} layout-{layout_class} category-{safe_category_class} style-{safe_style_class}{' buchona-global' if design_profile.get('design_line') == 'buchona' else ''}">

    <main class="card-container">

        <!-- AI: Logo -->
        <div class="logo-container">
            <img src="./assets/logo.png" alt="Logo {safe_company}" style="--logo-position: {int(data.get('logo_position') or 50)}%">
        </div>

        <!-- AI: Hero -->
        <section class="info">
            <h1>{safe_company}</h1>
            <p class="bio">{safe_bio}</p>
            {meta_html}
        </section>

        <!-- AI: Profiles -->
        {primary_profiles_section}

        <!-- AI: Links -->
        {links_section}

        <footer class="card-signature"><span>{safe_company}</span><span>Conectemos.</span></footer>
    </main>

</body>
</html>
"""

    def _get_icon(self, name):
        key = (name or "").strip().lower()
        key = key.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
        icons = {
            "instagram": "fab fa-instagram",
            "facebook": "fab fa-facebook",
            "tiktok": "fab fa-tiktok",
            "whatsapp": "fab fa-whatsapp",
            "github": "fab fa-github",
            "sitio web": "fas fa-globe",
            "linkedin": "fab fa-linkedin-in",
            "x (twitter)": "fab fa-x-twitter",
            "twitter": "fab fa-x-twitter",
            "x": "fab fa-x-twitter",
            "youtube": "fab fa-youtube",
            "telegram": "fab fa-telegram",
            "correo electronico": "fas fa-envelope",
            "correo": "fas fa-envelope",
            "google maps": "fas fa-location-dot",
            "calendly": "fas fa-calendar-check",
            "telefono": "fas fa-phone",
            "tel": "fas fa-phone",
            "behance": "fab fa-behance",
            "dribbble": "fab fa-dribbble",
            "pinterest": "fab fa-pinterest"
        }
        if "correo" in key or "mail" in key:
            return "fas fa-envelope"
        return icons.get(key, "fas fa-link")

    def _get_link_style_class(self, name):
        key = (name or "").strip().lower()
        key = key.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")

        class_map = {
            "instagram": " link-instagram",
            "facebook": " link-facebook",
            "tiktok": " link-tiktok",
            "whatsapp": " link-whatsapp",
            "github": " link-github",
            "sitio web": " link-web",
            "linkedin": " link-linkedin",
            "x (twitter)": " link-x",
            "twitter": " link-x",
            "x": " link-x",
            "youtube": " link-youtube",
            "telegram": " link-telegram",
            "correo electronico": " link-email",
            "correo": " link-email",
            "google maps": " link-maps",
            "calendly": " link-calendly",
            "telefono": " link-phone",
            "tel": " link-phone",
            "behance": " link-behance",
            "dribbble": " link-dribbble",
            "pinterest": " link-pinterest",
            "catalogo": " link-pdf",
            "pdf": " link-pdf",
        }

        if "correo" in key or "mail" in key:
            return " link-email"
        return class_map.get(key, "")
