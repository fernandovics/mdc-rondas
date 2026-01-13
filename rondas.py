# rondas.py — MDC Ronda (QR Público, sem login) — Versão SIMPLES
# Rodar:
#   C:\Users\ferna\anaconda3\python.exe -m streamlit run rondas.py
# Abrir:
#   http://localhost:8501/?ronda=adm__portaria

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from PIL import Image

import base64
import streamlit as st


# -----------------------
# Config
# -----------------------
APP_TITLE = "🛡️ MDC — Rondas"
DATA_DIR = Path("data")
UPLOADS_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "ronda.db"

DATA_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

st.set_page_config(page_title="MDC Ronda", layout="centered")


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


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor() 
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rondas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ronda_id TEXT NOT NULL,
            grupo TEXT,
            local TEXT,
            responsavel TEXT NOT NULL,
            data_hora TEXT NOT NULL,
            status_ronda TEXT NOT NULL,
            descricao_ocorrencias TEXT,
            fotos_json TEXT
        )
    """)
    conn.commit()
    return conn


def save_submission(payload: dict):
    conn = init_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO rondas (
            ronda_id, grupo, local, responsavel, data_hora,
            status_ronda, descricao_ocorrencias, fotos_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        payload["ronda_id"],
        payload.get("grupo"),
        payload.get("local"),
        payload["responsavel"],
        payload["data_hora"],
        payload["status_ronda"],
        payload.get("descricao_ocorrencias", ""),
        json.dumps(payload.get("fotos", []), ensure_ascii=False),
    ))
    conn.commit()
    conn.close()


def save_photos(ronda_id: str, files):
    saved = []
    if not files:
        return saved

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = UPLOADS_DIR / safe_filename(ronda_id) / ts
    folder.mkdir(parents=True, exist_ok=True)

    for f in files:
        fname = safe_filename(f.name)
        out = folder / fname
        out.write_bytes(f.getbuffer())
        saved.append(str(out).replace("\\", "/"))
    return saved


def whatsapp_message(grupo, local, ronda_id, responsavel, status_ronda, descricao, fotos_paths):
    linhas = []

    if status_ronda == "SEM_ALTERACOES":
        linhas.append("✅ *Rondas Realizadas, Sem Alterações!* ✅")
    else:
        linhas.append("⚠️ *Ronda Realizada, Com Ocorrências!* ⚠️")

    linhas.append(f"📍 *Local:* {local} ({grupo})" if grupo and local else f"📍 *Ronda:* {ronda_id}")
    linhas.append(f"🕒 *Data/Hora:* {now_str()}")
    linhas.append(f"👤 *Responsável:* {responsavel}")

    if status_ronda != "SEM_ALTERACOES":
        if descricao.strip():
            linhas.append("")
            linhas.append(f"📝 *Ocorrências:* {descricao.strip()}")

    if fotos_paths:
        linhas.append(f"📷 *Fotos:* {len(fotos_paths)} (anexadas no sistema)")

    return "\n".join(linhas)


# -----------------------
# Cadastro de locais (MVP)
# - Depois pode vir de Excel/DB
# -----------------------
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
# UI
# -----------------------
logo = Image.open("assets/logo_mdc.png")

col1, col2 = st.columns([1, 6])
with col1:
    st.image(logo, width=220)
with col2:
    st.markdown(
    '<h2 style="margin:0; padding-top:3px;">Rondas de Segurança</h2>',
    unsafe_allow_html=True
)

ronda_id = get_query_param("ronda")

if not ronda_id:
    st.info("Abra pelo QR Code com parâmetro. Exemplo:")
    st.code("http://localhost:8501/?ronda=adm__portaria")
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

# FORA do form -> atualiza na hora
status_ui = st.radio(
    "Selecione:",
    ["✅ Sem alterações", "⚠️ Com ocorrências"],
    index=0,
    key="status_ui"
)

with st.form("ronda_form", clear_on_submit=False):
    responsavel = st.text_input("👤 Responsável ", placeholder="Nome:")

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

# salvar fotos + registro
saved_photos = save_photos(ronda_id, fotos)

payload = {
    "ronda_id": ronda_id,
    "grupo": grupo,
    "local": local,
    "responsavel": responsavel.strip(),
    "data_hora": datetime.now().isoformat(timespec="seconds"),
    "status_ronda": status_ronda,
    "descricao_ocorrencias": descricao_ocorrencias.strip(),
    "fotos": saved_photos
}
save_submission(payload)

st.success("Ronda registrada ✅")

msg = whatsapp_message(
    grupo, local, ronda_id,
    responsavel.strip(),
    status_ronda,
    descricao_ocorrencias,
    saved_photos
)

st.markdown("### 📲 Mensagem para WhatsApp (copiar e colar)")
st.text_area("Mensagem", value=msg, height=260)

if saved_photos:
    with st.expander("📷 Fotos salvas (referência)"):
        for p in saved_photos:
            st.code(p)

st.caption("Dica: anexe as fotos no WhatsApp junto da mensagem (se o grupo exigir).")
