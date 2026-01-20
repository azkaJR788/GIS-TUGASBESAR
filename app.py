import streamlit as st
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
import requests
import json
import os
import urllib3

# Bypass SSL Warning (Agar tidak error di server pemerintah yg SSL-nya kadang bermasalah)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(
    page_title="GIS Disabilitas Jabar",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.title("🗺️ Sistem Informasi Geografis (GIS) Disabilitas Jawa Barat")
st.markdown("Status: **Live System** | Mode: **Hybrid (API/Local)**")

# --- 2. FITUR SCRAPING (BROWSER MIMIC MODE) ---
@st.cache_data(ttl=3600)
def get_dataset():
    api_url = (
        "https://data.jabarprov.go.id/api-backend/bigdata/"
        "disdukcapil_2/od_16998_jml_penduduk_penyandang_disabilitas__kategori_disa_v5"
        "?limit=1100"
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json",
        "Referer": "https://opendata.jabarprov.go.id/"
    }

    df = pd.DataFrame()
    source = "UNKNOWN"

    session = requests.Session()
    session.headers.update(headers)

    try:
        # 🔑 STEP 1: Warm-up session (ambil cookie)
        session.get(
            "https://opendata.jabarprov.go.id/",
            timeout=10
        )

        # 🔑 STEP 2: Hit API (TANPA verify=False)
        resp = session.get(api_url, timeout=15)
        resp.raise_for_status()

        data = resp.json().get("data", [])
        df = pd.DataFrame(data)
        source = "API"

    except Exception:
        # Fallback ke lokal (STABIL & WARAS)
        local_file = "jabar.json"
        if os.path.exists(local_file):
            with open(local_file) as f:
                data = json.load(f).get("data", [])
            df = pd.DataFrame(data)
            source = "LOCAL"
        else:
            source = "EMPTY"

    if not df.empty:
        df["jumlah_penduduk"] = pd.to_numeric(
            df["jumlah_penduduk"], errors="coerce"
        )

    return df, source


# Eksekusi Scraping
with st.spinner('Menghubungkan ke Server JabarProv...'):
    df_disabilitas, status_sumber = get_dataset()

# Notifikasi Status (Supaya user tau sumber datanya)
if "Live" in status_sumber:
    st.success(f"Sumber Data: {status_sumber}")
else:
    # Tampilkan warna oranye agar terlihat "siaga" bukan "rusak"
    st.warning(f"Mode: {status_sumber}")

# --- 3. FITUR GIS (Load Peta) ---
@st.cache_data
def load_map():
    map_path = 'Jabar_By_Kab.geojson'
    if os.path.exists(map_path):
        return gpd.read_file(map_path)
    return gpd.GeoDataFrame()

gdf_jabar = load_map()

# --- 4. LOGIKA VISUALISASI ---
if not df_disabilitas.empty and not gdf_jabar.empty:
    
    # Ambil Tahun Terbaru
    tahun_terbaru = df_disabilitas['tahun'].max()
    
    # Filter Data Tahun Terbaru
    df_active = df_disabilitas[df_disabilitas['tahun'] == tahun_terbaru].copy()
    
    # CLEANING NAMA KOTA (PENTING AGAR PETA MUNCUL)
    def clean_name(text):
        if isinstance(text, str):
            # Hapus kata "KABUPATEN/KOTA" agar cocok dengan GeoJSON
            return text.upper().replace("KABUPATEN ", "").replace("KOTA ", "").replace("KAB. ", "").strip()
        return str(text)

    df_active['nama_join'] = df_active['nama_kabupaten_kota'].apply(clean_name)
    
    # Cari Kolom Nama di GeoJSON (Otomatis)
    target_col = 'KABKOT' # Default
    possible_cols = ['KABKOT', 'NAMEOBJ', 'WADMKK', 'NAME_2', 'Kabupaten']
    for col in possible_cols:
        if col in gdf_jabar.columns:
            target_col = col
            break
            
    gdf_jabar['nama_join'] = gdf_jabar[target_col].astype(str).str.upper().str.strip()

    # Agregasi Data (Group by Kota)
    df_map_agg = df_active.groupby('nama_join')['jumlah_penduduk'].sum().reset_index()
    
    # Merge Data Statistik ke Peta
    gdf_final = gdf_jabar.merge(df_map_agg, on='nama_join', how='left')
    gdf_final['jumlah_penduduk'] = gdf_final['jumlah_penduduk'].fillna(0)

    # --- TAMPILAN DASHBOARD ---
    
    # KPI Metrics
    col1, col2, col3 = st.columns(3)
    total_pop = df_active['jumlah_penduduk'].sum()
    
    try:
        top_city = df_map_agg.sort_values('jumlah_penduduk', ascending=False).iloc[0]
        top_name = top_city['nama_join']
        top_val = top_city['jumlah_penduduk']
    except:
        top_name = "-"
        top_val = 0
    
    col1.metric("Total Data", f"{int(total_pop):,} Jiwa")
    col2.metric("Wilayah Tertinggi", f"{top_name}")
    col3.metric("Jumlah Tertinggi", f"{int(top_val):,} Jiwa")

    st.markdown("---")

    # Layout Peta (Kiri) & Grafik (Kanan)
    col_left, col_right = st.columns([2, 1])

    with col_left:
        st.subheader(f"📍 Peta Sebaran ({tahun_terbaru})")
        
        # Proyeksi ke Meter (Agar tidak gepeng & akurat)
        gdf_viz = gdf_final.to_crs(epsg=3857)
        
        fig, ax = plt.subplots(figsize=(10, 8))
        gdf_viz.plot(
            column='jumlah_penduduk',
            cmap='Reds', # Warna Merah
            linewidth=0.8,
            ax=ax,
            edgecolor='0.6',
            legend=True,
            legend_kwds={'label': "Jumlah Penduduk", 'orientation': "horizontal", 'shrink': 0.7}
        )
        
        # Label Nama Kota di Peta
        for x, y, label in zip(gdf_viz.geometry.centroid.x, gdf_viz.geometry.centroid.y, gdf_viz[target_col]):
            ax.text(x, y, label, fontsize=6, ha='center', color='black', weight='bold', alpha=0.5)
            
        ax.axis('off')
        st.pyplot(fig)

    with col_right:
        st.subheader("📊 Analisis Data")
        
        tab1, tab2 = st.tabs(["Top 10 Wilayah", "Per Kategori"])
        
        with tab1:
            df_top = df_active.groupby('nama_kabupaten_kota')['jumlah_penduduk'].sum().sort_values(ascending=False).head(10)
            st.bar_chart(df_top, color="#ff4b4b")
            
        with tab2:
            df_kat = df_active.groupby('kategori_disabilitas')['jumlah_penduduk'].sum().sort_values()
            st.bar_chart(df_kat, color="#ffa500", horizontal=True)

else:
    st.error("Gagal memuat data. Pastikan file 'jabar.json' dan 'Jabar_By_Kab.geojson' ada di folder aplikasi.")