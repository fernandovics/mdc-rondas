# rondas.py — MDC Ronda (QR Público, sem login)
# FASE 01 — Supabase como fonte oficial (Postgres + Storage privado)
# Deploy: Streamlit Cloud

import re
from datetime import datetime
from pathlib import Path

import streamlit as st
from PIL import Image
from supabase import create_client


# -----------------------
# Config / UI
# -----------------------
APP_TITLE = "Rondas de Segurança"
APP_VERSION = "2026-01-13_02"

st.set_page_config(page_title=APP_TITLE, layout="centered")
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


# -----------------------
# Helpers
# -----------------------

@st.cache_resource
def get_supabase():
    url = st.secrets.get("SUPABASE_URL", "")
    key = st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        st.error("❌ Secrets ausentes: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY")
        st.stop()
    return create_client(url, key)


def now_str() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M")


def safe_filename(name: str) -> str:
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9_\-\.]+", "_", name)
    return name[:120]


def get_query_param(key: str):
    qp = st.query_params
    val = qp.get(key)
    if isinstance(val, list):
        return val[0] if val else None
    return val


def upload_photos_to_storage(ronda_id: str, files):
    """
    Sobe fotos no Supabase Storage (bucket privado)
    Retorna lista de PATHS (não links)
    """
    if not files:
        return []

    sb = get_supabase()
    bucket = st.secrets.get("SUPABASE_BUCKET", "mdc-rondas")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    day = datetime.now().strftime("%Y-%m-%d")

    stored_paths = []

    for f in files:
        filename = safe_filename(f"{ronda_id}_{ts}_{f.name}")
        path = f"rondas/{day}/{ronda_id}/{filename}"

        content = f.getbuffer().tobytes()
        content_type = f.type or "application/octet-stream"

        sb.storage.from_(bucket).upload(
            path=path,
            file=content,
            file_options={"content-type": content_type, "upsert": False},
        )

        stored_paths.append(path)

    return stored_paths


def insert_to_supabase(payload: dict, fotos_paths: list[str]):
    sb = get_supabase()

    row = {
        "ronda_id": payload["ronda_id"],
        "grupo": payload["grupo"],
        "local": payload["local"],
        "responsavel": payload["responsavel"],
        "status_ronda": payload["status_ronda"],
        "descricao_ocorrencias": payload["descricao_ocorrencias"],
        "fotos_paths": fotos_paths,
    }

    sb.table("rondas").insert(row).execute()


def whatsapp_message(grupo, local, ronda_id, responsavel, status_ronda, descricao, fotos_paths):
    linhas = []

    if status_ronda == "SEM_ALTERACOES":
        linhas.append("✅ *Rondas Realizadas, Sem Alterações!*")
    else:
        linhas.append("⚠️ *Ronda Realizada, Com Ocorrências!*")

    linhas.append(f"📍 *Local:* {local} ({grupo})")
    linhas.append(f"🕒 *Data/Hora:* {now_str()}")
    linhas.append(f"👤 *Responsável:* {responsavel}")

    if status_ronda == "COM_OCORRENCIAS" and descricao:
        linhas.append("")
        linhas.append(f"📝 *Ocorrências:* {descricao}")

    if fotos_paths:
        linhas.append(f"📷 *Fotos:* {len(fotos_paths)} (arquivadas no sistema)")

    return "\n".join(linhas)


# -----------------------
# UI - Header
# -----------------------
logo_path = Path("assets/logo_mdc.png")
logo = Image.open(logo_path) if logo_path.exists() else None

col1, col2 = st.columns([1, 6])
with col1:
    if logo:
        st.image(logo, width=200)
with col2:
    st.markdown("## Rondas de Segurança")


# -----------------------
# Param / Ronda
# -----------------------
ronda_id = get_query_param("ronda")

if not ronda_id:
    st.info("Abra pelo QR Code com parâmetro. Exemplo:")
    st.code("https://mdc-rondas.streamlit.app/?ronda=adm__portaria")
    st.write("IDs válidos:", sorted(DEFAULT_RONDAS.keys()))
    st.stop()

cfg = DEFAULT_RONDAS.get(ronda_id)
if not cfg:
    st.error(f"Ronda inválida: `{ronda_id}`")
    st.stop()

grupo = cfg["grupo"]
local = cfg["local"]

st.markdown(f"### 📍 {local}")
st.caption(f"Grupo: {grupo} • ID: `{ronda_id}` • {now_str()}")

# -----------------------
# Form
# -----------------------
st.markdown("#### Status da ronda")

status_ui = st.radio(
    "Selecione:",
    ["✅ Sem alterações", "⚠️ Com ocorrências"],
    index=0
)

with st.form("ronda_form"):
    responsavel = st.text_input("👤 Responsável")

    descricao_ocorrencias = ""
    if status_ui.startswith("⚠️"):
        descricao_ocorrencias = st.text_area(
            "📝 Descrição das ocorrências",
            height=120
        )

    fotos = st.file_uploader(
        "📷 Anexar fotos",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=True
    )

    submitted = st.form_submit_button("✅ Finalizar Ronda")

if not submitted:
    st.stop()

# -----------------------
# Validações
# -----------------------
if not responsavel.strip():
    st.error("Informe o nome do responsável.")
    st.stop()

status_ronda = "SEM_ALTERACOES" if status_ui.startswith("✅") else "COM_OCORRENCIAS"

if status_ronda == "COM_OCORRENCIAS" and not descricao_ocorrencias.strip():
    st.error("Descreva as ocorrências observadas.")
    st.stop()

payload = {
    "ronda_id": ronda_id,
    "grupo": grupo,
    "local": local,
    "responsavel": responsavel.strip(),
    "status_ronda": status_ronda,
    "descricao_ocorrencias": descricao_ocorrencias.strip(),
}

# -----------------------
# Persistência (Supabase)
# -----------------------
try:
    with st.spinner("Salvando..."):
        fotos_paths = upload_photos_to_storage(ronda_id, fotos)
        insert_to_supabase(payload, fotos_paths)
except Exception as e:
    st.error("❌ Falha ao salvar a ronda no sistema.")
    st.exception(e)
    st.stop()

st.success("✅ Ronda registrada com sucesso!")

# -----------------------
# WhatsApp
# -----------------------
msg = whatsapp_message(
    grupo,
    local,
    ronda_id,
    responsavel.strip(),
    status_ronda,
    descricao_ocorrencias.strip(),
    fotos_paths
)

st.markdown("### 📲 Mensagem para WhatsApp")
st.text_area("Copiar e colar", value=msg, height=240)

if fotos_paths:
    with st.expander("📷 Arquivos armazenados (paths internos)"):
        for p in fotos_paths:
            st.code(p)

st.caption("As fotos ficam armazenadas internamente no sistema (não públicas).")
