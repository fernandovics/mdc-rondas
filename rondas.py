# rondas.py — MDC Ronda (QR Público, sem login) — MVP (Google Sheets + Drive)
# Deploy: Streamlit Cloud
# URL: https://mdc-rondas.streamlit.app/?ronda=adm__portaria

import io
import json
import os
import re
from datetime import datetime
from pathlib import Path

import streamlit as st
from PIL import Image

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload


# -----------------------
# Config / UI
# -----------------------
APP_TITLE = "Rondas de Segurança"
st.set_page_config(page_title="MDC Ronda", layout="centered")
APP_VERSION = "2026-01-13_01"

st.set_page_config(page_title="MDC Ronda", layout="centered")
st.caption(f"versão: {APP_VERSION}")

# IDs fixos (MVP)
DEFAULT_RONDAS = {
    "adm__portaria": {"grupo": "ADM", "local": "Portaria"},
    "adm__cozinha": {"grupo": "ADM", "local": "Cozinha"},
    "adm__alojamento": {"grupo": "ADM", "local": "Alojamento"},
    "adm__administrativo": {"grupo": "ADM", "local": "Administrativo"},
    "operacao__resumo": {"grupo": "Operação", "local": "Resumo"},
    "operacao__linha": {"grupo": "Operação", "local": "Linha"},
    "operacao__cava": {"grupo": "Operação", "local": "Cava"},
    "operacao__bota-fora": {"grupo": "Operação", "local": "Bota-Fora"},
}

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


# -----------------------
# Helpers
# -----------------------
def now_str() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M")


def safe_filename(name: str) -> str:
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9_\-\.]+", "_", name)
    return name[:120] if len(name) > 120 else name


def get_query_param(key: str):
    qp = st.query_params
    val = qp.get(key)
    if isinstance(val, list):
        return val[0] if val else None
    return val


def get_gcp_creds() -> Credentials:
    """Credenciais via Streamlit Secrets (JSON como string)."""
    sa_raw = st.secrets.get("GCP_SERVICE_ACCOUNT_JSON", "")
    if not sa_raw:
        st.error("Secrets ausentes: GCP_SERVICE_ACCOUNT_JSON")
        st.stop()

    # sa_raw pode vir como string JSON
    try:
        sa_info = json.loads(sa_raw)
    except Exception:
        st.error("GCP_SERVICE_ACCOUNT_JSON não está em formato JSON válido no Secrets.")
        st.stop()

    return Credentials.from_service_account_info(sa_info, scopes=SCOPES)


@st.cache_resource
def get_clients():
    """Cacheia os clients (Sheets/Drive) para performance."""
    creds = get_gcp_creds()
    sheets = build("sheets", "v4", credentials=creds)
    drive = build("drive", "v3", credentials=creds)
    return sheets, drive


def ensure_sheet_header():
    """Garante cabeçalho na linha 1 (não destrói dados)."""
    sheet_id = st.secrets.get("SHEET_ID", "")
    if not sheet_id:
        st.error("Secrets ausentes: SHEET_ID")
        st.stop()

    sheets, _ = get_clients()

    # tenta ler A1:H1
    resp = sheets.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range="A1:H1"
    ).execute()

    values = resp.get("values", [])
    if values and len(values[0]) >= 2:
        # já tem algo, não mexe
        return

    header = [[
        "data_hora",
        "ronda_id",
        "grupo",
        "local",
        "responsavel",
        "status_ronda",
        "descricao_ocorrencias",
        "fotos_links"
    ]]

    sheets.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range="A1:H1",
        valueInputOption="RAW",
        body={"values": header},
    ).execute()


def upload_photos_to_drive(ronda_id: str, files):
    """Sobe fotos e retorna lista de links (webViewLink)."""
    if not files:
        return []

    folder_id = st.secrets.get("DRIVE_FOLDER_ID", "")
    if not folder_id:
        st.error("Secrets ausentes: DRIVE_FOLDER_ID")
        st.stop()

    _, drive = get_clients()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    links = []

    for f in files:
        filename = safe_filename(f"{ronda_id}_{ts}_{f.name}")

        media = MediaIoBaseUpload(
            io.BytesIO(f.getbuffer()),
            mimetype=f.type or "application/octet-stream",
            resumable=False
        )

        file_metadata = {"name": filename, "parents": [folder_id]}

        created = drive.files().create(
            body=file_metadata,
            media_body=media,
            fields="id"
        ).execute()

        file_id = created["id"]

        # MVP: público por link (pra não dar dor de permissão no celular da galera)
        drive.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
        ).execute()

        info = drive.files().get(
            fileId=file_id,
            fields="webViewLink"
        ).execute()

        links.append(info["webViewLink"])

    return links


def append_to_sheet(payload: dict, photo_links: list[str]):
    sheet_id = st.secrets.get("SHEET_ID", "")
    if not sheet_id:
        st.error("Secrets ausentes: SHEET_ID")
        st.stop()

    sheets, _ = get_clients()

    row = [[
        payload.get("data_hora", ""),
        payload.get("ronda_id", ""),
        payload.get("grupo", ""),
        payload.get("local", ""),
        payload.get("responsavel", ""),
        payload.get("status_ronda", ""),
        payload.get("descricao_ocorrencias", ""),
        " | ".join(photo_links),
    ]]

    sheets.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range="A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": row},
    ).execute()


def whatsapp_message(grupo, local, ronda_id, responsavel, status_ronda, descricao, photo_links):
    linhas = []

    if status_ronda == "SEM_ALTERACOES":
        linhas.append("✅ *Rondas Realizadas, Sem Alterações!* ✅")
    else:
        linhas.append("⚠️ *Ronda Realizada, Com Ocorrências!* ⚠️")

    linhas.append(f"📍 *Local:* {local} ({grupo})" if grupo and local else f"📍 *Ronda:* {ronda_id}")
    linhas.append(f"🕒 *Data/Hora:* {now_str()}")
    linhas.append(f"👤 *Responsável:* {responsavel}")

    if status_ronda != "SEM_ALTERACOES" and descricao.strip():
        linhas.append("")
        linhas.append(f"📝 *Ocorrências:* {descricao.strip()}")

    if photo_links:
        linhas.append(f"📷 *Fotos:* {len(photo_links)} (links no registro)")

    return "\n".join(linhas)


# -----------------------
# UI - Header
# -----------------------
logo_path = Path("assets/logo_mdc.png")
if logo_path.exists():
    logo = Image.open(str(logo_path))
else:
    logo = None

col1, col2 = st.columns([1, 6])
with col1:
    if logo:
        st.image(logo, width=220)
with col2:
    st.markdown('<h2 style="margin:0; padding-top:3px;">Rondas de Segurança</h2>', unsafe_allow_html=True)

# sanity: garantir header na planilha (sem matar dados)
ensure_sheet_header()

# -----------------------
# Param / Ronda
# -----------------------
ronda_id = get_query_param("ronda")

if not ronda_id:
    st.info("Abra pelo QR Code com parâmetro. Exemplo:")
    st.code("https://mdc-rondas.streamlit.app/?ronda=adm__portaria")
    st.markdown("**IDs cadastrados:**")
    st.write(sorted(DEFAULT_RONDAS.keys()))
    st.stop()

cfg = DEFAULT_RONDAS.get(ronda_id)
if not cfg:
    st.error(f"Ronda inválida: `{ronda_id}`")
    st.markdown("**IDs cadastrados:**")
    st.write(sorted(DEFAULT_RONDAS.keys()))
    st.stop()

grupo = cfg.get("grupo")
local = cfg.get("local")

st.markdown(f"### 📍 {local}  \n**Grupo:** {grupo}")
st.caption(f"ID: `{ronda_id}` • {now_str()}")

st.markdown("#### Status da ronda")

# Fora do form: atualiza na hora
status_ui = st.radio(
    "Selecione:",
    ["✅ Sem alterações", "⚠️ Com ocorrências"],
    index=0,
    key="status_ui"
)

with st.form("ronda_form", clear_on_submit=False):
    responsavel = st.text_input("👤 Responsável", placeholder="Nome:")

    descricao_ocorrencias = ""
    if st.session_state["status_ui"].startswith("⚠️"):
        descricao_ocorrencias = st.text_area(
            "📝 Descrição",
            placeholder="Descreva a ocorrência observada na ronda.",
            height=120
        )

    st.markdown("#### 📷 Fotos")
    fotos = st.file_uploader(
        "Anexar registro",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=True
    )

    submitted = st.form_submit_button("✅ Finalizar Ronda")

if not submitted:
    st.stop()

# validações
if not responsavel or not responsavel.strip():
    st.error("Coloque o nome do responsável.")
    st.stop()

status_ronda = "SEM_ALTERACOES" if status_ui.startswith("✅") else "COM_OCORRENCIAS"

if status_ronda == "COM_OCORRENCIAS" and not descricao_ocorrencias.strip():
    st.error("Você marcou 'Com ocorrências'. Escreva rapidamente o que foi encontrado.")
    st.stop()

payload = {
    "ronda_id": ronda_id,
    "grupo": grupo,
    "local": local,
    "responsavel": responsavel.strip(),
    "data_hora": datetime.now().isoformat(timespec="seconds"),
    "status_ronda": status_ronda,
    "descricao_ocorrencias": descricao_ocorrencias.strip(),
}

# upload + sheet
try:
    with st.spinner("Salvando..."):
        photo_links = upload_photos_to_drive(ronda_id, fotos)
        append_to_sheet(payload, photo_links)
except Exception as e:
    st.error("❌ Falha ao salvar no Google Drive / Sheets")
    st.exception(e)
    st.stop()

st.success("Ronda registrada ✅")

msg = whatsapp_message(
    grupo, local, ronda_id,
    responsavel.strip(),
    status_ronda,
    descricao_ocorrencias,
    photo_links
)

st.markdown("### 📲 Mensagem para WhatsApp (copiar e colar)")
st.text_area("Mensagem", value=msg, height=260)

if photo_links:
    with st.expander("📷 Links das fotos"):
        for link in photo_links:
            st.code(link)

st.caption("Dica: anexe as fotos no WhatsApp junto da mensagem.")
