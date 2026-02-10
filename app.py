import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Sniper V12.7.4 - Italy Total Scan", layout="wide")
st.title("🎯 SNIPER V12.7.4 - Radar Assoluto Italia")
st.markdown("Monitoraggio forzato Serie C (Lega Pro) + Top Leghe Globali.")

# --- CONFIGURAZIONE API ---
API_KEY = "5977f2e2446bf2620d4c2d356ce590c9"
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

# IDS DI RIFERIMENTO (Estero + Top Italia)
IDS = [
    135, 136, 140, 141, 78, 79, 61, 62, 39, 40, 41, 42, # Top Europe
    106, 107, 108, 110, 111, 94, 95, 119, 120, 113, 114, 103, 104, # Europa
    283, 284, 285, 197, 198, 203, 204, # Est + Turchia
    71, 72, 73, 128, 129, 118, 101, 144, # Sud America
    179, 180, 262, 218, 143 # Extra
]

def style_rows(row):
    """Gestione colori: Verde (Elite), Verde Chiaro (Buono), Azzurro (Focus Italia)"""
    if row.Rating >= 75:
        return ['background-color: #1e7e34; color: white'] * len(row)
    elif row.Rating >= 60:
        return ['background-color: #d4edda; color: #155724'] * len(row)
    elif row.Rating == 1:
        return ['background-color: #f8f9fa; color: #6c757d; font-style: italic'] * len(row)
