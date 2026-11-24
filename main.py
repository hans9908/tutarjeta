import os
import shutil
import json
import re
import base64
import hashlib
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus
from html import escape
import qrcode
import mysql.connector
from mysql.connector import Error
import customtkinter as ctk
from tkinter import filedialog, messagebox, simpledialog
from PIL import Image, ImageDraw, ImageFont
import requests

# --- CONFIGURACIÓN DE APARIENCIA ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

APP_ROOT = Path(__file__).resolve().parent
ADMIN_PANEL_PASSWORD_CONFIG = {
    "username": "admin",
    "salt_hex": "b41d3ce3f7d8f0f35c1ab9c26888ad3e",
    "iterations": 210000,
    "hash_b64": "22Hg8mHz9N6WNgYET70lyqiONAl1oBc/ZavKUB9SQm0=",
}
ADMIN_GITHUB_CONFIG = {
    "owner": "hans9908",
    "repo": "tutarjeta",
    "pages_branch": "gh-pages",
    "content_branch": "master",
    "content_prefix": "dist",
}

class DatabaseManager:
    def __init__(self):
        self.config = {
            'host': 'localhost',
            'user': 'root',
            'password': '',
            'port': '3306'
        }
        self.db_name = 'tarjetas_db'
        self._initialize_db()

    def _get_connection(self, include_db=True):
        config = self.config.copy()
        if include_db:
            config['database'] = self.db_name
        config['charset'] = 'utf8mb4'
        config['collation'] = 'utf8mb4_unicode_ci'
        return mysql.connector.connect(**config)

    def _initialize_db(self):
        try:
            conn = self._get_connection(include_db=False)
            cursor = conn.cursor()
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {self.db_name}")
            cursor.execute(f"USE {self.db_name}")

            create_table_query = """
            CREATE TABLE IF NOT EXISTS clientes (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                company_name VARCHAR(100) NOT NULL,
                bio TEXT,
                category ENUM('abogados', 'ingenieria', 'belleza', 'nutricion', 'arquitectura') NOT NULL,
                final_url VARCHAR(255),
                logo_path VARCHAR(255),
                links JSON,
                profile JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
            cursor.execute(create_table_query)
            self._ensure_column(cursor, "clientes", "final_url", "VARCHAR(255)")
            self._ensure_column(cursor, "clientes", "profile", "JSON")
            conn.commit()
            cursor.close()
            conn.close()
        except Error as e:
            print(f"Error initializing DB: {e}")
            messagebox.showerror("Error de Base de Datos", f"No se pudo conectar a MySQL (Laragon).\n{e}")

    def _ensure_column(self, cursor, table_name, column_name, definition):
        cursor.execute(f"SHOW COLUMNS FROM {table_name} LIKE %s", (column_name,))
        if cursor.fetchone() is None:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

    def _build_profile_payload(self, data):
        profile = {
            'catalog_pdf_path': data.get('catalog_pdf_path', ''),
            'contact_email': data.get('contact_email', ''),
            'contact_phone': data.get('contact_phone', ''),
            'primary_website': data.get('primary_website', ''),
            'full_name': data.get('full_name', ''),
            'job_title': data.get('job_title', ''),
            'secondary_email': data.get('secondary_email', ''),
            'secondary_phone': data.get('secondary_phone', ''),
            'physical_address': data.get('physical_address', ''),
            'primary_instagram': data.get('primary_instagram', ''),
            'primary_linkedin': data.get('primary_linkedin', ''),
            'theme_variant': data.get('theme_variant', 'Auto'),
            'design_line': data.get('design_line', 'Auto'),
        }
        return json.dumps(profile)

    def _normalize_links(self, data):
        normalized = {}

        for link in data.get('links', []):
            name = (link.get('name') or '').strip()
            url = (link.get('url') or '').strip()
            if not name or not url:
                continue
            normalized[name] = {'name': name, 'url': url, 'active': link.get('active', True) is not False}

        special_links = {
            'Sitio Web': (data.get('primary_website') or '').strip(),
            'Correo electrónico': (data.get('contact_email') or '').strip(),
        }

        for name, value in special_links.items():
            if value:
                normalized[name] = {'name': name, 'url': value, 'active': True}

        return list(normalized.values())

    def _decode_json(self, raw_value, default):
        if not raw_value:
            return default
        if isinstance(raw_value, (list, dict)):
            return raw_value
        try:
            return json.loads(raw_value)
        except (TypeError, json.JSONDecodeError):
            return default

    def save_client(self, data):
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            normalized_links = self._normalize_links(data)

            query = """
            INSERT INTO clientes (username, company_name, bio, category, final_url, logo_path, links, profile)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
            company_name = VALUES(company_name),
            bio = VALUES(bio),
            category = VALUES(category),
            final_url = VALUES(final_url),
            logo_path = VALUES(logo_path),
            links = VALUES(links),
            profile = VALUES(profile)
            """
            cursor.execute(query, (
                data['username'],
                data['company_name'],
                data['bio'],
                data['category'],
                data.get('final_url', ''),
                data['logo_path'],
                json.dumps(normalized_links),
                self._build_profile_payload(data)
            ))
            conn.commit()
            cursor.close()
            conn.close()
            return True
        except Error as e:
            print(f"Error saving client: {e}")
            messagebox.showerror("Error", f"Error al guardar en la base de datos: {e}")
            return False

    def list_clients(self):
        try:
            conn = self._get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, username, company_name, category, final_url, created_at
                FROM clientes
                ORDER BY company_name ASC, username ASC
                """
            )
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
            return rows
        except Error as e:
            print(f"Error listing clients: {e}")
            messagebox.showerror("Error", f"No se pudieron listar los clientes: {e}")
            return []

    def get_client_by_username(self, username):
        try:
            conn = self._get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM clientes WHERE username = %s", (username,))
            row = cursor.fetchone()
            cursor.close()
            conn.close()
            if not row:
                return None

            links = self._decode_json(row.get('links'), [])
            profile = self._decode_json(row.get('profile'), {})
            site_link = next((link.get('url', '') for link in links if link.get('name') == 'Sitio Web' and link.get('url')), '')
            phone_link = next((link.get('url', '') for link in links if link.get('name') in {'Teléfono', 'WhatsApp'} and link.get('url')), '')
            email_link = next((link.get('url', '') for link in links if link.get('name') == 'Correo electrónico' and link.get('url')), '')
            return {
                'username': row.get('username', ''),
                'company_name': row.get('company_name', ''),
                'bio': row.get('bio', ''),
                'category': row.get('category', 'abogados'),
                'final_url': row.get('final_url', '') or '',
                'logo_path': row.get('logo_path', '') or '',
                'links': links,
                'catalog_pdf_path': profile.get('catalog_pdf_path', ''),
                'contact_email': profile.get('contact_email', '') or email_link.replace('mailto:', ''),
                'contact_phone': profile.get('contact_phone', '') or phone_link,
                'primary_website': profile.get('primary_website', '') or site_link,
                'full_name': profile.get('full_name', ''),
                'job_title': profile.get('job_title', ''),
                'secondary_email': profile.get('secondary_email', ''),
                'secondary_phone': profile.get('secondary_phone', ''),
                'physical_address': profile.get('physical_address', ''),
                'primary_instagram': profile.get('primary_instagram', ''),
                'primary_linkedin': profile.get('primary_linkedin', ''),
                'theme_variant': profile.get('theme_variant', 'Auto'),
                'design_line': profile.get('design_line', 'Auto'),
            }
        except Error as e:
            print(f"Error loading client: {e}")
            messagebox.showerror("Error", f"No se pudo cargar el cliente: {e}")
            return None

    def delete_client(self, username):
        """Elimina un cliente de la base de datos."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM clientes WHERE username = %s", (username,))
            deleted = cursor.rowcount > 0
            conn.commit()
            cursor.close()
            conn.close()
            return deleted
        except Error as e:
            print(f"Error deleting client: {e}")
            messagebox.showerror("Error", f"No se pudo eliminar el cliente: {e}")
            return False

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

    def export_admin_panel(self, clients, password_config=None, github_config=None):
        password_config = password_config or ADMIN_PANEL_PASSWORD_CONFIG
        github_config = github_config or ADMIN_GITHUB_CONFIG

        admin_dir = Path(self.base_dir) / "admin"
        admin_dir.mkdir(parents=True, exist_ok=True)

        cards = []
        for client in clients:
            username = self._sanitize_username(client.get("username", ""))
            if not username:
                continue

            created_at = client.get("created_at", "")
            if hasattr(created_at, "isoformat"):
                created_at = created_at.isoformat()
            elif created_at:
                created_at = str(created_at)

            preview_path = self._get_client_dir(username) / "index.html"
            cards.append({
                "username": username,
                "company_name": client.get("company_name", ""),
                "category": client.get("category", ""),
                "generated": preview_path.exists(),
                "preview_url": f"../{username}/" if preview_path.exists() else "",
                "created_at": created_at,
            })

        cards.sort(key=lambda item: ((item.get("company_name") or "").lower(), item.get("username") or ""))

        (admin_dir / "clients.json").write_text(
            json.dumps(cards, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (admin_dir / "index.html").write_text(
            self._get_admin_panel_template(password_config, github_config),
            encoding="utf-8",
        )

    def _github_headers(self, token):
        return {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }

    def _github_contents_url(self, remote_path):
        return f"https://api.github.com/repos/{ADMIN_GITHUB_CONFIG['owner']}/{ADMIN_GITHUB_CONFIG['repo']}/contents/{remote_path}"

    def _github_get_sha(self, remote_path, branch, token):
        response = requests.get(
            self._github_contents_url(remote_path),
            headers=self._github_headers(token),
            params={"ref": branch},
            timeout=30,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        return payload.get("sha") if isinstance(payload, dict) else None

    def _github_list_remote_files(self, branch, root_path, token):
        files = []
        response = requests.get(
            f"https://api.github.com/repos/{ADMIN_GITHUB_CONFIG['owner']}/{ADMIN_GITHUB_CONFIG['repo']}/contents/{root_path}" if root_path else f"https://api.github.com/repos/{ADMIN_GITHUB_CONFIG['owner']}/{ADMIN_GITHUB_CONFIG['repo']}/contents",
            headers=self._github_headers(token),
            params={"ref": branch},
            timeout=30,
        )
        if response.status_code == 404:
            return files
        response.raise_for_status()
        entries = response.json()
        if not isinstance(entries, list):
            return files

        for entry in entries:
            if entry.get("type") == "file":
                files.append({"path": entry.get("path"), "sha": entry.get("sha")})
            elif entry.get("type") == "dir":
                files.extend(self._github_list_remote_files(branch, entry.get("path"), token))
        return files

    def _github_upsert_file(self, local_path, remote_path, branch, token):
        payload = {
            "message": f"Update {remote_path}",
            "content": base64.b64encode(local_path.read_bytes()).decode("ascii"),
            "branch": branch,
        }
        sha = self._github_get_sha(remote_path, branch, token)
        if sha:
            payload["sha"] = sha

        response = requests.put(
            self._github_contents_url(remote_path),
            headers=self._github_headers(token),
            json=payload,
            timeout=30,
        )
        response.raise_for_status()

    def _github_delete_file(self, remote_path, branch, token, sha):
        payload = {
            "message": f"Delete {remote_path}",
            "sha": sha,
            "branch": branch,
        }
        response = requests.delete(
            self._github_contents_url(remote_path),
            headers=self._github_headers(token),
            json=payload,
            timeout=30,
        )
        response.raise_for_status()

    def publish_to_github_pages(self, token):
        local_root = Path(self.base_dir)
        branches = [
            ("master", "dist"),
            ("gh-pages", ""),
        ]

        uploaded = 0
        deleted = 0

        local_files = [path for path in local_root.rglob("*") if path.is_file()]

        for branch, prefix in branches:
            expected_remote_paths = set()

            for local_path in local_files:
                relative_path = local_path.relative_to(local_root).as_posix()
                remote_path = f"{prefix}/{relative_path}" if prefix else relative_path
                expected_remote_paths.add(remote_path)
                self._github_upsert_file(local_path, remote_path, branch, token)
                uploaded += 1

            remote_files = self._github_list_remote_files(branch, prefix, token)
            for remote_file in remote_files:
                remote_path = remote_file.get("path")
                if remote_path not in expected_remote_paths:
                    self._github_delete_file(remote_path, branch, token, remote_file.get("sha"))
                    deleted += 1

        return uploaded, deleted

    def _get_admin_panel_template(self, password_config, github_config):
        auth_json = json.dumps(password_config, ensure_ascii=False)
        github_json = json.dumps(github_config, ensure_ascii=False)
        template = """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Administrador de Tarjetas</title>
    <style>
        :root {
            --bg: #0b1220;
            --panel: #121b2d;
            --panel-alt: #19243a;
            --text: #edf2f7;
            --muted: #9fb0c7;
            --accent: #4f8cff;
            --danger: #e5484d;
            --danger-soft: #8f1d21;
            --success: #31a46c;
            --border: rgba(255,255,255,0.08);
        }

        * { box-sizing: border-box; }

        body {
            margin: 0;
            min-height: 100vh;
            font-family: "Segoe UI", Tahoma, sans-serif;
            background:
                radial-gradient(circle at top left, rgba(79,140,255,0.28), transparent 30%),
                radial-gradient(circle at bottom right, rgba(49,164,108,0.18), transparent 25%),
                var(--bg);
            color: var(--text);
        }

        .shell {
            width: min(1120px, calc(100% - 32px));
            margin: 32px auto;
        }

        .hero,
        .card,
        .login-panel {
            background: linear-gradient(180deg, rgba(18,27,45,0.96), rgba(14,21,35,0.96));
            border: 1px solid var(--border);
            border-radius: 24px;
            box-shadow: 0 18px 45px rgba(0,0,0,0.28);
        }

        .hero {
            padding: 28px;
            margin-bottom: 18px;
        }

        .hero h1 {
            margin: 0 0 10px;
            font-size: clamp(1.9rem, 4vw, 2.8rem);
        }

        .hero p,
        .hint,
        .muted {
            color: var(--muted);
        }

        .toolbar {
            display: flex;
            gap: 12px;
            flex-wrap: wrap;
            margin-top: 18px;
        }

        button,
        .link {
            border: 0;
            border-radius: 14px;
            padding: 12px 16px;
            font: inherit;
            cursor: pointer;
            transition: transform 0.18s ease, opacity 0.18s ease, background 0.18s ease;
        }

        button:hover,
        .link:hover {
            transform: translateY(-1px);
        }

        .primary {
            background: var(--accent);
            color: white;
        }

        .secondary {
            background: var(--panel-alt);
            color: var(--text);
            border: 1px solid var(--border);
        }

        .danger {
            background: var(--danger);
            color: white;
        }

        .danger.secondary {
            background: rgba(229,72,77,0.12);
            border: 1px solid rgba(229,72,77,0.28);
            color: #ffb3b5;
        }

        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 16px;
        }

        .card {
            padding: 20px;
        }

        .card h2 {
            margin: 0 0 8px;
            font-size: 1.15rem;
        }

        .meta {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin: 12px 0 16px;
        }

        .chip {
            padding: 6px 10px;
            border-radius: 999px;
            background: rgba(255,255,255,0.06);
            border: 1px solid var(--border);
            font-size: 0.82rem;
            color: var(--muted);
        }

        .actions {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }

        .link {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            text-decoration: none;
        }

        .empty {
            padding: 28px;
            text-align: center;
        }

        .status {
            margin: 14px 0 0;
            min-height: 24px;
            color: var(--muted);
        }

        .status.error { color: #ffb3b5; }
        .status.success { color: #86efac; }

        .overlay {
            position: fixed;
            inset: 0;
            background: rgba(6,10,17,0.82);
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
            z-index: 10;
        }

        .overlay[hidden] {
            display: none;
        }

        .login-panel {
            width: min(460px, 100%);
            padding: 26px;
        }

        .login-panel h2 {
            margin-top: 0;
        }

        .field {
            display: flex;
            flex-direction: column;
            gap: 8px;
            margin: 16px 0;
        }

        input {
            width: 100%;
            border-radius: 14px;
            border: 1px solid var(--border);
            background: #0f1727;
            color: var(--text);
            padding: 14px 16px;
            font: inherit;
        }

        code {
            background: rgba(255,255,255,0.06);
            padding: 2px 6px;
            border-radius: 8px;
        }

        @media (max-width: 720px) {
            .shell {
                width: min(100% - 20px, 1120px);
                margin: 16px auto 28px;
            }

            .hero,
            .card,
            .login-panel {
                border-radius: 18px;
            }
        }
    </style>
</head>
<body>
    <div class="overlay" id="loginOverlay">
        <div class="login-panel">
            <h2>Panel de administración</h2>
            <p class="hint">Este acceso protege el panel HTML. El borrado remoto de tarjetas desplegadas solicita además tu token de GitHub en el momento de uso y nunca se guarda en el código.</p>
            <div class="field">
                <label for="usernameInput">Usuario</label>
                <input id="usernameInput" type="text" autocomplete="username" placeholder="Introduce el usuario del panel">
            </div>
            <div class="field">
                <label for="passwordInput">Contraseña</label>
                <input id="passwordInput" type="password" autocomplete="current-password" placeholder="Introduce la contraseña del panel">
            </div>
            <div class="toolbar">
                <button class="primary" id="unlockButton" type="button">Entrar</button>
            </div>
            <p class="status" id="loginStatus"></p>
        </div>
    </div>

    <div class="shell">
        <section class="hero">
            <h1>Administrador de tarjetas</h1>
            <p>Desde aquí puedes revisar tarjetas generadas y eliminar despliegues innecesarios en GitHub Pages. El borrado local de base de datos y archivos sigue disponible en la app de Python.</p>
            <div class="toolbar">
                <button class="secondary" id="reloadButton" type="button">Recargar tarjetas</button>
                <button class="danger secondary" id="clearTokenButton" type="button">Olvidar token GitHub</button>
            </div>
            <p class="status" id="globalStatus"></p>
        </section>

        <section id="cardsRoot" class="grid"></section>
    </div>

    <script>
        const ADMIN_AUTH = __ADMIN_AUTH__;
        const GITHUB_CONFIG = __GITHUB_CONFIG__;
        const AUTH_SESSION_KEY = "tarjetas_admin_authenticated";
        const TOKEN_SESSION_KEY = "tarjetas_admin_github_token";
        const state = { cards: [] };

        function setStatus(message, kind = "") {
            const node = document.getElementById("globalStatus");
            node.textContent = message || "";
            node.className = kind ? `status ${kind}` : "status";
        }

        function setLoginStatus(message, kind = "") {
            const node = document.getElementById("loginStatus");
            node.textContent = message || "";
            node.className = kind ? `status ${kind}` : "status";
        }

        function hexToBytes(hex) {
            const pairs = hex.match(/.{1,2}/g) || [];
            return new Uint8Array(pairs.map((pair) => parseInt(pair, 16)));
        }

        function bytesToBase64(bytes) {
            let binary = "";
            bytes.forEach((byte) => {
                binary += String.fromCharCode(byte);
            });
            return btoa(binary);
        }

        function utf8ToBase64(text) {
            return btoa(unescape(encodeURIComponent(text)));
        }

        async function derivePasswordHash(password) {
            const keyMaterial = await crypto.subtle.importKey(
                "raw",
                new TextEncoder().encode(password),
                "PBKDF2",
                false,
                ["deriveBits"]
            );
            const bits = await crypto.subtle.deriveBits(
                {
                    name: "PBKDF2",
                    hash: "SHA-256",
                    salt: hexToBytes(ADMIN_AUTH.salt_hex),
                    iterations: ADMIN_AUTH.iterations,
                },
                keyMaterial,
                256
            );
            return bytesToBase64(new Uint8Array(bits));
        }

        function timingSafeEqual(left, right) {
            if (left.length !== right.length) {
                return false;
            }
            let diff = 0;
            for (let index = 0; index < left.length; index += 1) {
                diff |= left.charCodeAt(index) ^ right.charCodeAt(index);
            }
            return diff === 0;
        }

        function contentUrl(path) {
            const encoded = path.split("/").filter(Boolean).map(encodeURIComponent).join("/");
            return `https://api.github.com/repos/${GITHUB_CONFIG.owner}/${GITHUB_CONFIG.repo}/contents/${encoded}`;
        }

        async function getContent(path, branch, token) {
            const response = await fetch(`${contentUrl(path)}?ref=${encodeURIComponent(branch)}`, {
                headers: token ? { Authorization: `token ${token}` } : {},
            });
            if (response.status === 404) {
                return null;
            }
            if (!response.ok) {
                throw new Error(`No se pudo leer ${path} en ${branch} (${response.status}).`);
            }
            return response.json();
        }

        async function collectFiles(path, branch, token) {
            const node = await getContent(path, branch, token);
            if (!node) {
                return [];
            }
            if (Array.isArray(node)) {
                const nested = await Promise.all(
                    node.map((entry) => collectFiles(entry.path, branch, token))
                );
                return nested.flat();
            }
            if (node.type === "file") {
                return [{ path: node.path, sha: node.sha }];
            }
            if (node.type === "dir") {
                return collectFiles(node.path, branch, token);
            }
            return [];
        }

        async function deleteFile(entry, branch, token) {
            const response = await fetch(contentUrl(entry.path), {
                method: "DELETE",
                headers: {
                    Authorization: `token ${token}`,
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    message: `Delete ${entry.path}`,
                    sha: entry.sha,
                    branch,
                }),
            });
            if (!response.ok) {
                const detail = await response.text();
                throw new Error(`No se pudo borrar ${entry.path} en ${branch}. ${detail}`);
            }
        }

        async function putJsonFile(path, branch, data, token) {
            const existing = await getContent(path, branch, token);
            const payload = {
                message: `Update ${path}`,
                content: utf8ToBase64(JSON.stringify(data, null, 2)),
                branch,
            };
            if (existing && !Array.isArray(existing) && existing.sha) {
                payload.sha = existing.sha;
            }
            const response = await fetch(contentUrl(path), {
                method: "PUT",
                headers: {
                    Authorization: `token ${token}`,
                    "Content-Type": "application/json",
                },
                body: JSON.stringify(payload),
            });
            if (!response.ok) {
                const detail = await response.text();
                throw new Error(`No se pudo actualizar ${path}. ${detail}`);
            }
        }

        async function ensureToken() {
            let token = sessionStorage.getItem(TOKEN_SESSION_KEY) || "";
            if (!token) {
                token = window.prompt("Introduce un token de GitHub con permiso repo para borrar tarjetas desplegadas.", "");
                if (!token) {
                    return "";
                }
                sessionStorage.setItem(TOKEN_SESSION_KEY, token.trim());
                token = token.trim();
            }
            return token;
        }

        async function loadCards() {
            const response = await fetch(`./clients.json?ts=${Date.now()}`);
            if (!response.ok) {
                throw new Error("No se pudo cargar el catálogo del panel.");
            }
            state.cards = await response.json();
        }

        function renderCards() {
            const root = document.getElementById("cardsRoot");
            root.innerHTML = "";

            if (!state.cards.length) {
                const empty = document.createElement("div");
                empty.className = "card empty";
                empty.innerHTML = '<h2>Sin tarjetas registradas</h2><p class="muted">Cuando guardes o generes clientes desde la app de Python, este panel se actualizará automáticamente.</p>';
                root.appendChild(empty);
                return;
            }

            state.cards.forEach((card) => {
                const article = document.createElement("article");
                article.className = "card";

                const title = document.createElement("h2");
                title.textContent = card.company_name || card.username;
                article.appendChild(title);

                const subtitle = document.createElement("p");
                subtitle.className = "muted";
                subtitle.textContent = `@${card.username}`;
                article.appendChild(subtitle);

                const meta = document.createElement("div");
                meta.className = "meta";
                [
                    card.category || "sin categoría",
                    card.generated ? "generada" : "sin generar",
                    card.created_at || "sin fecha",
                ].forEach((item) => {
                    const chip = document.createElement("span");
                    chip.className = "chip";
                    chip.textContent = item;
                    meta.appendChild(chip);
                });
                article.appendChild(meta);

                const actions = document.createElement("div");
                actions.className = "actions";

                if (card.preview_url) {
                    const preview = document.createElement("a");
                    preview.className = "link secondary";
                    preview.href = card.preview_url;
                    preview.target = "_blank";
                    preview.rel = "noopener noreferrer";
                    preview.textContent = "Abrir tarjeta";
                    actions.appendChild(preview);
                }

                const remove = document.createElement("button");
                remove.type = "button";
                remove.className = "danger";
                remove.textContent = "Eliminar despliegue";
                remove.addEventListener("click", () => deleteCard(card.username));
                actions.appendChild(remove);

                article.appendChild(actions);
                root.appendChild(article);
            });
        }

        async function persistAdminManifest(token) {
            await putJsonFile("admin/clients.json", GITHUB_CONFIG.pages_branch, state.cards, token);

            if (GITHUB_CONFIG.content_branch && GITHUB_CONFIG.content_prefix) {
                await putJsonFile(`${GITHUB_CONFIG.content_prefix}/admin/clients.json`, GITHUB_CONFIG.content_branch, state.cards, token);
            }
        }

        async function deleteCard(username) {
            const confirmed = window.confirm(`Se eliminará la tarjeta desplegada de @${username} en GitHub Pages y en la rama de contenido. Esta acción no toca la base de datos local. ¿Deseas continuar?`);
            if (!confirmed) {
                return;
            }

            const token = await ensureToken();
            if (!token) {
                setStatus("Se canceló el borrado porque no se proporcionó token.", "error");
                return;
            }

            try {
                setStatus(`Borrando @${username}...`);

                const pagesFiles = await collectFiles(username, GITHUB_CONFIG.pages_branch, token);
                for (const entry of pagesFiles) {
                    await deleteFile(entry, GITHUB_CONFIG.pages_branch, token);
                }

                if (GITHUB_CONFIG.content_branch && GITHUB_CONFIG.content_prefix) {
                    const contentPath = `${GITHUB_CONFIG.content_prefix}/${username}`;
                    const contentFiles = await collectFiles(contentPath, GITHUB_CONFIG.content_branch, token);
                    for (const entry of contentFiles) {
                        await deleteFile(entry, GITHUB_CONFIG.content_branch, token);
                    }
                }

                state.cards = state.cards.filter((card) => card.username !== username);
                await persistAdminManifest(token);
                renderCards();
                setStatus(`La tarjeta desplegada de @${username} fue eliminada correctamente.`, "success");
            } catch (error) {
                setStatus(error.message || "No se pudo eliminar la tarjeta.", "error");
            }
        }

        async function unlock() {
            const username = document.getElementById("usernameInput").value.trim();
            const password = document.getElementById("passwordInput").value;
            if (!username) {
                setLoginStatus("Introduce el usuario del panel.", "error");
                return;
            }
            if (!password) {
                setLoginStatus("Introduce la contraseña del panel.", "error");
                return;
            }

            try {
                if (username !== ADMIN_AUTH.username) {
                    setLoginStatus("Usuario incorrecto.", "error");
                    return;
                }

                const derived = await derivePasswordHash(password);
                if (!timingSafeEqual(derived, ADMIN_AUTH.hash_b64)) {
                    setLoginStatus("Contraseña incorrecta.", "error");
                    return;
                }

                sessionStorage.setItem(AUTH_SESSION_KEY, "ok");
                document.getElementById("loginOverlay").hidden = true;
                setLoginStatus("");
                await refreshCards(true);
            } catch (error) {
                setLoginStatus("No se pudo validar la contraseña en este navegador.", "error");
            }
        }

        async function refreshCards(silent = false) {
            try {
                await loadCards();
                renderCards();
                if (!silent) {
                    setStatus("Panel actualizado.", "success");
                }
            } catch (error) {
                setStatus(error.message || "No se pudo recargar el panel.", "error");
            }
        }

        document.getElementById("unlockButton").addEventListener("click", unlock);
        document.getElementById("usernameInput").addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                unlock();
            }
        });
        document.getElementById("passwordInput").addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                unlock();
            }
        });
        document.getElementById("reloadButton").addEventListener("click", () => refreshCards(false));
        document.getElementById("clearTokenButton").addEventListener("click", () => {
            sessionStorage.removeItem(TOKEN_SESSION_KEY);
            setStatus("El token de GitHub se eliminó de la sesión actual.", "success");
        });

        if (sessionStorage.getItem(AUTH_SESSION_KEY) === "ok") {
            document.getElementById("loginOverlay").hidden = true;
            refreshCards(true);
        }
    </script>
</body>
</html>
"""
        return template.replace("__ADMIN_AUTH__", auth_json).replace("__GITHUB_CONFIG__", github_json)

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

        return "\r\n".join(lines)

    def _normalize_link_href(self, name, value):
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
                variant_index = requested_index % len(candidate_variants)
            else:
                variant_index = 0
        else:
            seed = f"{category}:{client_data.get('username', '')}:{client_data.get('company_name', '')}".encode("utf-8")
            variant_index = int(hashlib.sha256(seed).hexdigest(), 16) % len(candidate_variants)
        profile = dict(candidate_variants[variant_index])
        profile['variant_index'] = variant_index
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
        <section>
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
        <section>
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
    <title>{data['company_name']} - Tarjeta Digital</title>
    <!-- AI: Fonts -->
    <link href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;700;800&family=Cormorant+Garamond:wght@600;700&family=DM+Sans:wght@400;500;700&family=Fraunces:opsz,wght@9..144,600;9..144,700&family=IBM+Plex+Sans:wght@400;500;700&family=Manrope:wght@400;500;700;800&family=Plus+Jakarta+Sans:wght@400;500;700;800&family=Sora:wght@400;600;700&family=Space+Grotesk:wght@500;700&display=swap" rel="stylesheet">
    <!-- AI: Icons -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link rel="stylesheet" href="./css/style.css">
</head>
<body class="layout-{layout_class} category-{safe_category_class} style-{safe_style_class}{' buchona-global' if design_profile.get('design_line') == 'buchona' else ''}">

    <main class="card-container">
        <div class="chip-row">
            <p class="design-chip"><i class="fas fa-sparkles"></i> {safe_design_name}</p>
            <p class="category-chip"><i class="{safe_chip_icon}"></i> {safe_chip}</p>
        </div>

        <!-- AI: Logo -->
        <div class="logo-container">
            <img src="./assets/logo.png" alt="Logo {safe_company}">
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

class BusinessCardApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.db = DatabaseManager()
        self.generator = CardGenerator()

        self.title("Generador de Tarjetas Digitales Interactivas")
        self.geometry("1280x860")
        self.minsize(1180, 760)

        self.logo_path = ""
        self.catalog_pdf_path = ""
        self.selected_client_username = None
        self.links_data = []

        self._setup_ui()
        self._load_clients()
        self._reset_form(clear_selection=True)

    def _sync_link_checkbox(self, item):
        has_value = bool(item['entry'].get().strip())
        if has_value and not item['active'].get():
            item['active'].set(True)
        elif not has_value and item['active'].get():
            item['active'].set(False)

    def _setup_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.configure(fg_color="#0b0f14")

        # --- Cabecera ---
        header_frame = ctk.CTkFrame(self, corner_radius=18, fg_color="#131a24")
        header_frame.pack(pady=(18, 10), padx=18, fill="x")

        ctk.CTkLabel(header_frame, text="Digital Card Generator Pro", font=ctk.CTkFont(size=26, weight="bold")).pack(pady=(16, 4))
        ctk.CTkLabel(header_frame, text="Tarjetas digitales, QR y vCards en caliente", font=ctk.CTkFont(size=13)).pack(pady=(0, 14))

        body_frame = ctk.CTkFrame(self, fg_color="transparent")
        body_frame.pack(pady=(0, 12), padx=18, fill="both", expand=True)
        body_frame.grid_columnconfigure(1, weight=1)
        body_frame.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(body_frame, width=320, corner_radius=18, fg_color="#10151d")
        sidebar.grid(row=0, column=0, sticky="nsw", padx=(0, 12))
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(sidebar, text="Clientes", font=ctk.CTkFont(size=22, weight="bold")).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 4))
        ctk.CTkLabel(sidebar, text="Edita, genera y previsualiza desde aquí.", font=ctk.CTkFont(size=12)).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 12))

        ctk.CTkButton(
            sidebar,
            text="Actualizar GitHub Pages",
            height=42,
            fg_color="#6c5ce7",
            hover_color="#5548c8",
            command=self._publish_github_pages,
        ).grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 12))

        sidebar_actions = ctk.CTkFrame(sidebar, fg_color="transparent")
        sidebar_actions.grid(row=3, column=0, sticky="nsew", padx=12, pady=(0, 12))
        sidebar_actions.grid_rowconfigure(1, weight=1)
        sidebar_actions.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkButton(sidebar_actions, text="Nuevo", command=lambda: self._reset_form(clear_selection=True)).grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=(0, 10))
        ctk.CTkButton(sidebar_actions, text="Refrescar", fg_color="#1b2533", hover_color="#223044", command=self._load_clients).grid(row=0, column=1, sticky="ew", padx=(6, 0), pady=(0, 10))

        self.clients_list_frame = ctk.CTkScrollableFrame(sidebar_actions, corner_radius=14, fg_color="#0c1118")
        self.clients_list_frame.grid(row=1, column=0, columnspan=2, sticky="nsew")

        self.sidebar_status_label = ctk.CTkLabel(sidebar, text="Sin cliente seleccionado", font=ctk.CTkFont(size=12))
        self.sidebar_status_label.grid(row=4, column=0, sticky="w", padx=16, pady=(0, 6))

        ctk.CTkButton(sidebar, text="Vista previa", fg_color="#1b2533", hover_color="#223044", command=self._open_preview).grid(row=5, column=0, sticky="ew", padx=16, pady=(0, 8))
        ctk.CTkButton(sidebar, text="Abrir carpeta", fg_color="#1b2533", hover_color="#223044", command=self._open_output_folder).grid(row=6, column=0, sticky="ew", padx=16, pady=(0, 8))
        ctk.CTkButton(sidebar, text="Eliminar cliente", fg_color="#c1272d", hover_color="#8b1e23", command=self._delete_client_action).grid(row=7, column=0, sticky="ew", padx=16, pady=(0, 16))

        # --- Formulario Principal ---
        main_frame = ctk.CTkScrollableFrame(body_frame, width=860, height=600, corner_radius=18, fg_color="#10151d")
        main_frame.grid(row=0, column=1, sticky="nsew")

        ctk.CTkLabel(main_frame, text="Link final", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=12, pady=(12, 4))
        self.entry_domain = ctk.CTkEntry(main_frame, width=500, placeholder_text="https://midominio.com/cliente/ o link final publicado")
        self.entry_domain.pack(pady=(0, 10), padx=12, fill="x")

        data_frame = ctk.CTkFrame(main_frame)
        data_frame.pack(pady=(0, 10), padx=12, fill="x")

        ctk.CTkLabel(data_frame, text="Username (Carpeta / URL slug)").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.entry_username = ctk.CTkEntry(data_frame)
        self.entry_username.grid(row=1, column=0, sticky="ew", padx=5, pady=5)

        ctk.CTkLabel(data_frame, text="Nombre Empresa/Persona").grid(row=0, column=1, sticky="w", padx=5, pady=5)
        self.entry_company = ctk.CTkEntry(data_frame)
        self.entry_company.grid(row=1, column=1, sticky="ew", padx=5, pady=5)
        data_frame.grid_columnconfigure((0,1), weight=1)

        ctk.CTkLabel(main_frame, text="Biografía / Descripción", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=12)
        self.text_bio = ctk.CTkTextbox(main_frame, height=100)
        self.text_bio.pack(pady=(4, 10), padx=12, fill="x")

        contact_frame = ctk.CTkFrame(main_frame)
        contact_frame.pack(pady=(10, 8), padx=12, fill="x")

        ctk.CTkLabel(contact_frame, text="Contacto principal", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=12, pady=(12, 6))
        primary_contact_frame = ctk.CTkFrame(contact_frame)
        primary_contact_frame.pack(padx=12, pady=(0, 12), fill="x")

        ctk.CTkLabel(primary_contact_frame, text="Email principal").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.entry_contact_email = ctk.CTkEntry(primary_contact_frame, placeholder_text="correo@empresa.com")
        self.entry_contact_email.grid(row=1, column=0, sticky="ew", padx=5, pady=5)

        ctk.CTkLabel(primary_contact_frame, text="Teléfono principal").grid(row=0, column=1, sticky="w", padx=5, pady=5)
        self.entry_contact_phone = ctk.CTkEntry(primary_contact_frame, placeholder_text="+52 55 1234 5678")
        self.entry_contact_phone.grid(row=1, column=1, sticky="ew", padx=5, pady=5)

        ctk.CTkLabel(primary_contact_frame, text="Sitio web principal").grid(row=2, column=0, sticky="w", padx=5, pady=5)
        self.entry_primary_website = ctk.CTkEntry(primary_contact_frame, placeholder_text="https://www.tusitio.com")
        self.entry_primary_website.grid(row=3, column=0, columnspan=2, sticky="ew", padx=5, pady=5)

        ctk.CTkLabel(primary_contact_frame, text="Nombre completo").grid(row=4, column=0, sticky="w", padx=5, pady=5)
        self.entry_full_name = ctk.CTkEntry(primary_contact_frame, placeholder_text="Nombre y apellidos")
        self.entry_full_name.grid(row=5, column=0, sticky="ew", padx=5, pady=5)

        ctk.CTkLabel(primary_contact_frame, text="Cargo / Puesto").grid(row=4, column=1, sticky="w", padx=5, pady=5)
        self.entry_job_title = ctk.CTkEntry(primary_contact_frame, placeholder_text="Director, Diseñador, Abogado...")
        self.entry_job_title.grid(row=5, column=1, sticky="ew", padx=5, pady=5)

        primary_contact_frame.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(contact_frame, text="Opcionales", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=12, pady=(0, 6))
        optional_contact_frame = ctk.CTkFrame(contact_frame)
        optional_contact_frame.pack(padx=12, pady=(0, 12), fill="x")

        ctk.CTkLabel(optional_contact_frame, text="Email alterno").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.entry_secondary_email = ctk.CTkEntry(optional_contact_frame, placeholder_text="email2@empresa.com")
        self.entry_secondary_email.grid(row=1, column=0, sticky="ew", padx=5, pady=5)

        ctk.CTkLabel(optional_contact_frame, text="Teléfono alterno").grid(row=0, column=1, sticky="w", padx=5, pady=5)
        self.entry_secondary_phone = ctk.CTkEntry(optional_contact_frame, placeholder_text="+52 55 0000 0000")
        self.entry_secondary_phone.grid(row=1, column=1, sticky="ew", padx=5, pady=5)

        ctk.CTkLabel(optional_contact_frame, text="Dirección").grid(row=2, column=0, sticky="w", padx=5, pady=5)
        self.entry_physical_address = ctk.CTkEntry(optional_contact_frame, placeholder_text="Calle, número, colonia, ciudad")
        self.entry_physical_address.grid(row=3, column=0, columnspan=2, sticky="ew", padx=5, pady=5)

        ctk.CTkLabel(optional_contact_frame, text="Instagram").grid(row=4, column=0, sticky="w", padx=5, pady=5)
        self.entry_primary_instagram = ctk.CTkEntry(optional_contact_frame, placeholder_text="@usuario o https://...")
        self.entry_primary_instagram.grid(row=5, column=0, sticky="ew", padx=5, pady=5)

        ctk.CTkLabel(optional_contact_frame, text="LinkedIn").grid(row=4, column=1, sticky="w", padx=5, pady=5)
        self.entry_primary_linkedin = ctk.CTkEntry(optional_contact_frame, placeholder_text="@usuario o https://...")
        self.entry_primary_linkedin.grid(row=5, column=1, sticky="ew", padx=5, pady=5)

        optional_contact_frame.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(main_frame, text="Categoría", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=12, pady=(4, 0))
        self.category_var = ctk.StringVar(value="abogados")
        categories = ["abogados", "ingenieria", "belleza", "nutricion", "arquitectura"]
        self.combo_category = ctk.CTkComboBox(main_frame, values=categories, variable=self.category_var)
        self.combo_category.pack(pady=(4, 10), padx=12, fill="x")

        ctk.CTkLabel(main_frame, text="Diseño visual", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=12, pady=(2, 0))
        self.theme_variant_var = ctk.StringVar(value="Auto")
        theme_variants = ["Auto", "Estilo 1", "Estilo 2", "Estilo 3", "Estilo 4", "Estilo 5", "Estilo 6", "Estilo 7"]
        self.combo_theme_variant = ctk.CTkComboBox(main_frame, values=theme_variants, variable=self.theme_variant_var)
        self.combo_theme_variant.pack(pady=(4, 12), padx=12, fill="x")

        ctk.CTkLabel(main_frame, text="Linea de diseño", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=12, pady=(2, 0))
        self.design_line_var = ctk.StringVar(value="Auto")
        design_lines = ["Auto", "Formal", "Moderna", "Buchona", "Lujo", "Minimalista"]
        self.combo_design_line = ctk.CTkComboBox(main_frame, values=design_lines, variable=self.design_line_var)
        self.combo_design_line.pack(pady=(4, 12), padx=12, fill="x")

        logo_frame = ctk.CTkFrame(main_frame)
        logo_frame.pack(pady=(0, 10), padx=12, fill="x")
        self.btn_logo = ctk.CTkButton(logo_frame, text="Logotipo", command=self._select_logo)
        self.btn_logo.pack(side="left", padx=10, pady=10)
        self.label_logo_name = ctk.CTkLabel(logo_frame, text="Sin archivo seleccionado")
        self.label_logo_name.pack(side="left", padx=10)

        catalog_frame = ctk.CTkFrame(main_frame)
        catalog_frame.pack(pady=(0, 12), padx=12, fill="x")
        self.btn_catalog = ctk.CTkButton(catalog_frame, text="Catálogo PDF", command=self._select_catalog_pdf)
        self.btn_catalog.pack(side="left", padx=10, pady=10)
        self.label_catalog_name = ctk.CTkLabel(catalog_frame, text="Sin catálogo seleccionado")
        self.label_catalog_name.pack(side="left", padx=10)

        ctk.CTkLabel(main_frame, text="Enlaces", font=ctk.CTkFont(weight="bold")).pack(pady=(18, 4))
        primary_networks = [
            "Instagram",
            "Facebook",
            "LinkedIn",
            "X (Twitter)",
            "YouTube",
            "TikTok",
            "WhatsApp",
            "Teléfono",
        ]
        additional_networks = [
            "Telegram",
            "Google Maps",
            "Calendly",
            "Behance",
            "Dribbble",
            "Pinterest",
            "Correo electrónico",
            "GitHub",
            "Sitio Web"
        ]

        def create_link_group(title, networks):
            group_frame = ctk.CTkFrame(main_frame)
            group_frame.pack(pady=(8, 10), padx=10, fill="x")
            ctk.CTkLabel(group_frame, text=title, font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=12, pady=(10, 6))

            for net in networks:
                net_frame = ctk.CTkFrame(group_frame)
                net_frame.pack(pady=3, padx=12, fill="x")

                var_active = ctk.BooleanVar(value=False)
                cb = ctk.CTkCheckBox(net_frame, text=net, variable=var_active)
                cb.pack(side="left", padx=10)

                if net == "Correo electrónico":
                    placeholder = "Email"
                elif net == "Teléfono":
                    placeholder = "Número con código país"
                elif net == "Google Maps":
                    placeholder = "Dirección o enlace"
                elif net == "Calendly":
                    placeholder = "Usuario o URL"
                elif net in {"Behance", "Dribbble", "Pinterest"}:
                    placeholder = "Usuario o URL"
                else:
                    placeholder = "URL, usuario o handle"
                entry_url = ctk.CTkEntry(net_frame, placeholder_text=f"{placeholder} de {net}")
                entry_url.pack(side="right", fill="x", expand=True, padx=12, pady=6)

                item = {'name': net, 'active': var_active, 'entry': entry_url}
                entry_url.bind("<KeyRelease>", lambda _event, current_item=item: self._sync_link_checkbox(current_item))
                entry_url.bind("<FocusOut>", lambda _event, current_item=item: self._sync_link_checkbox(current_item))
                self.links_data.append(item)

        create_link_group("Enlaces principales", primary_networks)
        create_link_group("Enlaces adicionales", additional_networks)

        actions_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        actions_frame.pack(pady=18, padx=12, fill="x")
        actions_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        ctk.CTkButton(actions_frame, text="Guardar cliente", height=48, fg_color="#1b2533", hover_color="#223044", command=self._save_client_only).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ctk.CTkButton(actions_frame, text="Generar tarjeta", height=48, fg_color="#2f7dff", hover_color="#2566d6", command=self._save_and_generate).grid(row=0, column=1, sticky="ew", padx=6)
        ctk.CTkButton(actions_frame, text="Vista previa", height=48, fg_color="#1b2533", hover_color="#223044", command=self._open_preview).grid(row=0, column=2, sticky="ew", padx=6)
        ctk.CTkButton(actions_frame, text="Eliminar", height=48, fg_color="#c1272d", hover_color="#8b1e23", command=self._delete_client_action).grid(row=0, column=3, sticky="ew", padx=(6, 0))

    def _get_generated_index_path(self, username):
        if not username:
            return ""
        safe_username = self.generator._sanitize_username(username)
        return os.path.join(self.generator.base_dir, safe_username, "index.html")

    def _get_selected_username(self):
        if self.selected_client_username:
            return self.selected_client_username
        return self.generator._sanitize_username(self.entry_username.get().strip())

    def _load_clients(self):
        for child in self.clients_list_frame.winfo_children():
            child.destroy()

        clients = self.db.list_clients()
        self.generator.export_admin_panel(clients, ADMIN_PANEL_PASSWORD_CONFIG, ADMIN_GITHUB_CONFIG)
        if not clients:
            ctk.CTkLabel(self.clients_list_frame, text="Aún no hay clientes guardados.").pack(anchor="w", padx=12, pady=12)
            return

        for client in clients:
            username = client.get('username', '')
            company_name = client.get('company_name', '')
            generated = os.path.exists(self._get_generated_index_path(username))
            subtitle = f"@{username} · {client.get('category', '')}"
            status = "Generada" if generated else "Sin generar"

            item_frame = ctk.CTkFrame(self.clients_list_frame, corner_radius=12, fg_color="#121824")
            item_frame.pack(fill="x", padx=8, pady=6)

            ctk.CTkButton(
                item_frame,
                text=f"{company_name}\n{subtitle}\n{status}",
                anchor="w",
                height=78,
                fg_color="#121824",
                hover_color="#1a2331",
                command=lambda selected_username=username: self._select_client(selected_username),
            ).pack(fill="x", padx=4, pady=4)

    def _select_client(self, username):
        client = self.db.get_client_by_username(username)
        if not client:
            return
        self.selected_client_username = username
        self._populate_form(client)
        generated = os.path.exists(self._get_generated_index_path(username))
        self.sidebar_status_label.configure(text=f"Seleccionado: @{username} · {'Generada' if generated else 'Sin generar'}")

    def _reset_form(self, clear_selection=False):
        if clear_selection:
            self.selected_client_username = None
            self.sidebar_status_label.configure(text="Nuevo cliente")

        self.entry_domain.delete(0, "end")
        self.entry_username.delete(0, "end")
        self.entry_company.delete(0, "end")
        self.text_bio.delete("1.0", "end")
        self.category_var.set("abogados")
        self.theme_variant_var.set("Auto")
        self.design_line_var.set("Auto")

        form_entries = [
            self.entry_contact_email,
            self.entry_contact_phone,
            self.entry_primary_website,
            self.entry_full_name,
            self.entry_job_title,
            self.entry_secondary_email,
            self.entry_secondary_phone,
            self.entry_physical_address,
            self.entry_primary_instagram,
            self.entry_primary_linkedin,
        ]
        for entry in form_entries:
            entry.delete(0, "end")

        self.logo_path = ""
        self.catalog_pdf_path = ""
        self.label_logo_name.configure(text="Sin archivo seleccionado")
        self.label_catalog_name.configure(text="Sin catálogo seleccionado")
        self._clear_link_inputs()

    def _clear_link_inputs(self):
        for item in self.links_data:
            item['active'].set(False)
            item['entry'].delete(0, "end")

    def _populate_form(self, client):
        self._reset_form(clear_selection=False)

        self.entry_domain.insert(0, client.get('final_url', ''))
        self.entry_username.insert(0, client.get('username', ''))
        self.entry_company.insert(0, client.get('company_name', ''))
        self.text_bio.insert("1.0", client.get('bio', ''))
        self.category_var.set(client.get('category', 'abogados'))
        self.theme_variant_var.set(client.get('theme_variant', 'Auto'))
        self.design_line_var.set(client.get('design_line', 'Auto'))

        self.logo_path = client.get('logo_path', '') or ''
        self.catalog_pdf_path = client.get('catalog_pdf_path', '') or ''
        self.label_logo_name.configure(text=os.path.basename(self.logo_path) if self.logo_path else "Sin archivo seleccionado")
        self.label_catalog_name.configure(text=os.path.basename(self.catalog_pdf_path) if self.catalog_pdf_path else "Sin catálogo seleccionado")

        mappings = [
            (self.entry_contact_email, client.get('contact_email', '')),
            (self.entry_contact_phone, client.get('contact_phone', '')),
            (self.entry_primary_website, client.get('primary_website', '')),
            (self.entry_full_name, client.get('full_name', '')),
            (self.entry_job_title, client.get('job_title', '')),
            (self.entry_secondary_email, client.get('secondary_email', '')),
            (self.entry_secondary_phone, client.get('secondary_phone', '')),
            (self.entry_physical_address, client.get('physical_address', '')),
            (self.entry_primary_instagram, client.get('primary_instagram', '')),
            (self.entry_primary_linkedin, client.get('primary_linkedin', '')),
        ]
        for entry, value in mappings:
            if value:
                entry.insert(0, value)

        link_map = {link.get('name'): link.get('url', '') for link in client.get('links', []) if link.get('active')}
        for item in self.links_data:
            link_value = link_map.get(item['name'], '')
            if link_value:
                item['active'].set(True)
                item['entry'].insert(0, link_value)
            else:
                item['active'].set(False)

    def _select_logo(self):
        file_path = filedialog.askopenfilename(filetypes=[("Image files", "*.png *.jpg *.jpeg *.svg")])
        if file_path:
            self.logo_path = file_path
            self.label_logo_name.configure(text=os.path.basename(file_path))

    def _select_catalog_pdf(self):
        file_path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if file_path:
            self.catalog_pdf_path = file_path
            self.label_catalog_name.configure(text=os.path.basename(file_path))

    def _gather_form_data(self, require_final_url=False):
        username = self.entry_username.get().strip()
        company = self.entry_company.get().strip()
        final_url = self.entry_domain.get().strip()

        if not username or not company:
            messagebox.showwarning("Atención", "Username y Nombre de Empresa son obligatorios.")
            return None

        sanitized_username = self.generator._sanitize_username(username)
        if not sanitized_username:
            messagebox.showwarning("Atención", "El username contiene caracteres inválidos. Usa solo letras, números, puntos, guiones o guion bajo.")
            return None

        if require_final_url and not final_url:
            messagebox.showwarning("Atención", "Debes indicar el link final antes de generar la tarjeta.")
            return None

        if sanitized_username != username:
            self.entry_username.delete(0, "end")
            self.entry_username.insert(0, sanitized_username)

        links = []
        for item in self.links_data:
            raw_value = item['entry'].get().strip()
            if raw_value:
                item['active'].set(True)
                links.append({'name': item['name'], 'url': raw_value, 'active': True})
            else:
                item['active'].set(False)

        primary_website = self.entry_primary_website.get().strip()
        if primary_website and not any(link['name'] == 'Sitio Web' for link in links):
            links.append({'name': 'Sitio Web', 'url': primary_website, 'active': True})

        return {
            'username': sanitized_username,
            'company_name': company,
            'bio': self.text_bio.get("1.0", "end-1c").strip(),
            'category': self.category_var.get(),
            'theme_variant': self.theme_variant_var.get(),
            'design_line': self.design_line_var.get(),
            'final_url': final_url,
            'logo_path': self.logo_path,
            'catalog_pdf_path': self.catalog_pdf_path,
            'contact_email': self.entry_contact_email.get().strip(),
            'contact_phone': self.entry_contact_phone.get().strip(),
            'primary_website': primary_website,
            'full_name': self.entry_full_name.get().strip(),
            'job_title': self.entry_job_title.get().strip(),
            'secondary_email': self.entry_secondary_email.get().strip(),
            'secondary_phone': self.entry_secondary_phone.get().strip(),
            'physical_address': self.entry_physical_address.get().strip(),
            'primary_instagram': self.entry_primary_instagram.get().strip(),
            'primary_linkedin': self.entry_primary_linkedin.get().strip(),
            'links': links,
        }

    def _save_client_only(self):
        client_data = self._gather_form_data(require_final_url=False)
        if not client_data:
            return
        if self.db.save_client(client_data):
            self.selected_client_username = client_data['username']
            self._load_clients()
            self.sidebar_status_label.configure(text=f"Guardado: @{client_data['username']}")
            messagebox.showinfo("Cliente guardado", "El cliente se guardó correctamente. La tarjeta solo se generará cuando exista el link final.")

    def _save_and_generate(self):
        client_data = self._gather_form_data(require_final_url=True)
        if not client_data:
            return
        if self.db.save_client(client_data):
            try:
                qr_path = self.generator.generate(client_data, client_data['final_url'])
            except ValueError as error:
                messagebox.showwarning("Atención", str(error))
                return

            self.selected_client_username = client_data['username']
            self._load_clients()
            self.sidebar_status_label.configure(text=f"Generada: @{client_data['username']}")
            self._show_success_popup(qr_path, client_data['username'])

    def _open_preview(self):
        username = self._get_selected_username()
        preview_path = self._get_generated_index_path(username)
        if not username or not os.path.exists(preview_path):
            messagebox.showinfo("Vista previa", "Este cliente todavía no tiene una tarjeta generada.")
            return
        webbrowser.open(Path(preview_path).resolve().as_uri())

    def _open_output_folder(self):
        username = self._get_selected_username()
        if not username:
            messagebox.showinfo("Carpeta", "Selecciona o guarda un cliente primero.")
            return
        folder_path = os.path.dirname(self._get_generated_index_path(username))
        if not os.path.exists(folder_path):
            messagebox.showinfo("Carpeta", "La tarjeta todavía no se ha generado para este cliente.")
            return
        webbrowser.open(Path(folder_path).resolve().as_uri())

    def _delete_client_action(self):
        username = self._get_selected_username()
        if not username:
            messagebox.showinfo("Eliminar", "Selecciona un cliente primero.")
            return

        # Confirmación
        confirm = messagebox.askyesno(
            "Confirmar eliminación",
            f"¿Está seguro de que desea eliminar al cliente @{username}?\n\nEsto eliminará:\n• Los datos de la base de datos\n• La carpeta con los archivos generados\n\nEsta acción NO se puede deshacer."
        )

        if confirm:
            deleted_db = self.db.delete_client(username)
            deleted_files = self.generator.delete_generated_card(username)
            if deleted_db or deleted_files:
                self._load_clients()
                self._reset_form(clear_selection=True)
                if deleted_db and deleted_files:
                    detail = "registro y archivos generados"
                elif deleted_db:
                    detail = "registro"
                else:
                    detail = "archivos generados"
                messagebox.showinfo("Éxito", f"Se eliminó {detail} de @{username} correctamente.")
            else:
                messagebox.showerror("Error", f"No se pudo eliminar al cliente @{username}")

    def _publish_github_pages(self):
        token = simpledialog.askstring(
            "GitHub Token",
            "Introduce un token de GitHub con permiso repo. No se guardará en el equipo.",
            show="*",
            parent=self,
        )
        if not token:
            return

        confirm = messagebox.askyesno(
            "Confirmar actualización",
            "Se sincronizarán los archivos locales con master/dist y gh-pages. ¿Deseas continuar?",
        )
        if not confirm:
            return

        try:
            self.sidebar_status_label.configure(text="Actualizando GitHub Pages...")
            self.generator.export_admin_panel(self.db.list_clients(), ADMIN_PANEL_PASSWORD_CONFIG, ADMIN_GITHUB_CONFIG)
            uploaded, deleted = self.generator.publish_to_github_pages(token.strip())
            self.sidebar_status_label.configure(text="GitHub Pages actualizado")
            messagebox.showinfo(
                "GitHub Pages actualizado",
                f"Publicación completada.\nArchivos subidos: {uploaded}\nArchivos eliminados: {deleted}",
            )
        except requests.RequestException as error:
            messagebox.showerror("Error de GitHub", f"No se pudo actualizar GitHub Pages:\n{error}")
            self.sidebar_status_label.configure(text="Error al actualizar GitHub Pages")

    def _get_campaign_showcase_selection(self):
        # Curated set intended for social ads and quick client-facing demo reels.
        candidates = [
            ("abogados", "Buchona", "linea-abogados-buchona"),
            ("ingenieria", "Moderna", "linea-ingenieria-moderna"),
            ("belleza", "Lujo", "linea-belleza-lujo"),
            ("nutricion", "Formal", "linea-nutricion-formal"),
            ("arquitectura", "Lujo", "linea-arquitectura-lujo"),
        ]

        dist_dir = Path(self.generator.base_dir)
        selection = []
        for category, line_name, folder in candidates:
            folder_path = dist_dir / folder
            if folder_path.exists():
                selection.append((category, line_name, folder_path))
                continue

            # Fallback to style demos if line folder does not exist yet.
            fallback = dist_dir / f"promo-{category}-estilo-1"
            if fallback.exists():
                selection.append((category, "Estilo 1", fallback))
        return selection

    def _load_campaign_font(self, size, bold=False):
        candidates = [
            ("C:\\Windows\\Fonts\\segoeuib.ttf" if bold else "C:\\Windows\\Fonts\\segoeui.ttf", size),
            ("C:\\Windows\\Fonts\\arialbd.ttf" if bold else "C:\\Windows\\Fonts\\arial.ttf", size),
        ]
        for font_path, font_size in candidates:
            if os.path.exists(font_path):
                try:
                    return ImageFont.truetype(font_path, font_size)
                except Exception:
                    continue
        return ImageFont.load_default()

    def _create_campaign_poster(self, category, line_name, source_dir, output_path):
        color_map = {
            "abogados": ((23, 18, 23), (108, 73, 31), (245, 205, 137)),
            "ingenieria": ((10, 18, 34), (34, 68, 128), (126, 208, 255)),
            "belleza": ((34, 20, 34), (148, 56, 109), (255, 174, 217)),
            "nutricion": ((19, 36, 24), (47, 103, 64), (164, 232, 184)),
            "arquitectura": ((24, 24, 27), (71, 71, 79), (208, 173, 126)),
        }
        start_rgb, end_rgb, accent_rgb = color_map.get(category, color_map["abogados"])

        width, height = 1080, 1350
        poster = Image.new("RGB", (width, height), start_rgb)
        draw = ImageDraw.Draw(poster)

        for y in range(height):
            mix = y / max(height - 1, 1)
            r = int(start_rgb[0] * (1 - mix) + end_rgb[0] * mix)
            g = int(start_rgb[1] * (1 - mix) + end_rgb[1] * mix)
            b = int(start_rgb[2] * (1 - mix) + end_rgb[2] * mix)
            draw.line([(0, y), (width, y)], fill=(r, g, b))

        title_font = self._load_campaign_font(64, bold=True)
        subtitle_font = self._load_campaign_font(34, bold=True)
        body_font = self._load_campaign_font(28, bold=False)

        category_text = category.upper()
        line_text = f"LINEA {line_name.upper()}"

        draw.text((70, 68), category_text, fill=(245, 246, 250), font=title_font)
        draw.rounded_rectangle((70, 160, 530, 220), radius=28, fill=(255, 255, 255, 35), outline=accent_rgb, width=3)
        draw.text((92, 172), line_text, fill=accent_rgb, font=subtitle_font)

        logo_path = source_dir / "assets" / "logo.png"
        qr_path = source_dir / "assets" / "qr_share.png"

        resampling = getattr(Image, "Resampling", Image)
        if logo_path.exists():
            logo = Image.open(logo_path).convert("RGBA").resize((240, 240), resampling.LANCZOS)
            logo_box = Image.new("RGBA", (280, 280), (255, 255, 255, 0))
            logo_draw = ImageDraw.Draw(logo_box)
            logo_draw.ellipse((0, 0, 279, 279), fill=(255, 255, 255, 242), outline=accent_rgb, width=8)

            mask = Image.new("L", (240, 240), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, 239, 239), fill=255)
            clip = Image.new("RGBA", (240, 240), (255, 255, 255, 0))
            clip.paste(logo, (0, 0), mask)
            logo_box.alpha_composite(clip, (20, 20))
            poster.paste(logo_box, (70, 274), logo_box)

        if qr_path.exists():
            qr = Image.open(qr_path).convert("RGB").resize((430, 430), resampling.LANCZOS)
            qr_frame = Image.new("RGB", (470, 470), (255, 255, 255))
            qr_frame.paste(qr, (20, 20))
            poster.paste(qr_frame, (580, 240))

        cta_lines = [
            "Tarjeta digital premium",
            "QR listo para compartir",
            "Ideal para publicidad en redes",
        ]
        text_y = 620
        for line in cta_lines:
            draw.text((72, text_y), line, fill=(241, 244, 250), font=body_font)
            text_y += 46

        footer = "Solicita tu demo personalizada"
        draw.rounded_rectangle((70, 1140, 1010, 1240), radius=22, fill=(255, 255, 255, 30), outline=accent_rgb, width=2)
        draw.text((102, 1172), footer, fill=(249, 251, 255), font=subtitle_font)

        poster.save(output_path)

    def _export_campaign_pack(self, silent=False):
        selection = self._get_campaign_showcase_selection()
        if not selection:
            if not silent:
                messagebox.showinfo("Campaña", "No hay demos suficientes en dist para exportar campaña.")
            return

        campaign_dir = Path(self.generator.base_dir) / "campana"
        posters_dir = campaign_dir / "posters"
        qr_dir = campaign_dir / "qrs"
        campaign_dir.mkdir(parents=True, exist_ok=True)
        posters_dir.mkdir(parents=True, exist_ok=True)
        qr_dir.mkdir(parents=True, exist_ok=True)

        lines = [
            "# Campana Auto-Export",
            "",
            "Orden sugerido para capturas/publicidad:",
            "",
        ]

        for idx, (category, line_name, folder_path) in enumerate(selection, start=1):
            slug = f"{idx:02d}-{category}-{line_name.lower()}".replace(" ", "-")
            poster_out = posters_dir / f"{slug}.png"
            qr_src = folder_path / "assets" / "qr_share.png"
            qr_out = qr_dir / f"{slug}-qr.png"

            self._create_campaign_poster(category, line_name, folder_path, poster_out)
            if qr_src.exists():
                shutil.copy(qr_src, qr_out)

            rel_html = folder_path.relative_to(Path(self.generator.base_dir)).as_posix() + "/index.html"
            rel_poster = poster_out.relative_to(Path(self.generator.base_dir)).as_posix()
            rel_qr = qr_out.relative_to(Path(self.generator.base_dir)).as_posix()

            lines.append(f"{idx}. {category.title()} - {line_name}")
            lines.append(f"   - Demo: [{rel_html}]({rel_html})")
            lines.append(f"   - Poster: [{rel_poster}]({rel_poster})")
            if qr_src.exists():
                lines.append(f"   - QR: [{rel_qr}]({rel_qr})")
            lines.append("")

        readme_path = campaign_dir / "README.md"
        readme_path.write_text("\n".join(lines), encoding="utf-8")

        if not silent:
            webbrowser.open(readme_path.resolve().as_uri())
            webbrowser.open(campaign_dir.resolve().as_uri())
            messagebox.showinfo("Campaña exportada", f"Campaña creada en:\n{campaign_dir}")

    def _show_success_popup(self, qr_path, username):
        popup = ctk.CTkToplevel(self)
        popup.title("¡Generación Exitosa!")
        popup.geometry("460x570")
        popup.configure(fg_color="#0f1117")
        popup.attributes("-topmost", True)
        popup.resizable(False, False)

        popup_frame = ctk.CTkFrame(popup, corner_radius=18, fg_color="#121824")
        popup_frame.pack(fill="both", expand=True, padx=16, pady=16)

        header_frame = ctk.CTkFrame(popup_frame, corner_radius=14, fg_color="#171f2d")
        header_frame.pack(fill="x", padx=16, pady=(16, 12))

        ctk.CTkLabel(header_frame, text="Listo", font=ctk.CTkFont(size=20, weight="bold")).pack(pady=(16, 4))
        ctk.CTkLabel(header_frame, text="Compartible y NFC-ready.", font=ctk.CTkFont(size=12)).pack(pady=(0, 6))
        ctk.CTkLabel(header_frame, text=f"dist/{username}/", font=ctk.CTkFont(size=13)).pack(pady=(0, 14))

        preview_frame = ctk.CTkFrame(popup_frame, corner_radius=14, fg_color="#171f2d")
        preview_frame.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        ctk.CTkLabel(preview_frame, text="QR listo", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(16, 10))

        # Mostrar QR
        img = Image.open(qr_path)
        ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(250, 250))

        qr_label = ctk.CTkLabel(preview_frame, image=ctk_img, text="")
        qr_label.image = ctk_img # Referencia
        qr_label.pack(pady=(4, 14))

        ctk.CTkButton(popup_frame, text="Cerrar", height=42, fg_color="#2f7dff", hover_color="#2566d6", command=popup.destroy).pack(padx=16, pady=(4, 16), fill="x")

if __name__ == "__main__":
    app = BusinessCardApp()
    app.mainloop()
