import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Sniper V12.7.2 - Lega Pro Edition", layout="wide")
st.title("🎯 SNIPER V12.7.2 - Deep Vision & Serie C")
st.markdown("Monitoraggio Elite: Serie A/B/C, Championship e Leghe Globali.")

# --- CONFIGURAZIONE API ---
API_KEY = "5977f2e2446bf2620d4c2d356ce590c9"
HOST = "v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

# IDS AGGIORNATI: Top Europe + SERIE C COMPLETA (Gironi A, B, C)
IDS = [
    135, 136, 140, 141, 78, 79, 61, 62, 39, 40, 41, 42, # Top Europe & English
    137, 138, 139, 810, 811, 812, 181, # SERIE C ITALIA (Tutti i gironi + Lega Pro)
    106, 107, 108, 110, 111, 94, 95, 119, 120, 113, 114, 103, 104, # Europa
    283, 284, 285, 197, 198, 203, 204, # Est + Turchia + Grecia
    71, 72, 73, 128, 129, 118, 101, 144, # Sud America
    179, 180, 262, 218, 143 # Extra: Scozia, Austria, Belgio, Svizzera
]

def style_rows(row):
    """Gestione colori: Verde (Elite), Verde Chiaro (Buono), Azzurro (Serie C)"""
    if row.Rating >= 75:
        return ['background-color: #1e7e34; color: white'] * len(row)
    elif row.Rating >= 60:
        return ['background-color: #d4edda; color: #155724'] * len(row)
    elif any(x in str(row.Lega) for x in ["Serie C", "Group C", "Lega Pro", "Serie B"]):
        return ['background-color: #e3f2fd; color: #0d47a1'] * len(row)
    return [''] * len(row)

if st.button('🚀 AVVIA RADAR PROFONDO'):
    # Usiamo la data corrente impostata sul 10 Febbraio 2026
    oggi = datetime.now().strftime('%Y-%m-%d')
    res = requests.get(f"https://{HOST}/fixtures", headers=HEADERS, params={"date": oggi, "timezone": "Europe/Rome"})
    partite = res.json().get('response', [])
    
    # Debug info in sidebar
    st.sidebar.
