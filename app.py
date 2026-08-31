import streamlit as st
import pandas as pd
from rapidfuzz import process, fuzz
import unicodedata
import re
import io
import json
import tempfile
from google.oauth2.service_account import Credentials
import gspread

# =====================================================================
# CONFIGURACIÓN DE LA PÁGINA
# =====================================================================
st.set_page_config(page_title="Retail Planogram Engine", page_icon="📊", layout="wide")

st.title("📊 Retail Planogram Engine (Conexión Google Sheets: DATOST y CBARRAS)")
st.markdown("Motor de automatización y homologación conectado directamente a las pestañas **DATOST** y **CBARRAS**.")
st.markdown("---")

# =====================================================================
# 1. URLS DE GOOGLE SHEETS
# =====================================================================
st.sidebar.header("🔗 Configuración de Google Sheets")
url_matriz = st.sidebar.text_input(
    "Enlace Google Sheet Principal:",
    value="https://docs.google.com/spreadsheets/d/1pbGYgDB8UBZnm0aJZLGOhZwWYq0IlDO8Uqv2n1-MgxI/edit?usp=sharing"
)
url_cbarras = st.sidebar.text_input(
    "Enlace Google Sheet Códigos de Barras:",
    value="https://docs.google.com/spreadsheets/d/1veTjECI6wlFRqOVg1AKmV0yghxyGR5T0j0Im2AooukM/edit?usp=sharing"
)

# Función para extraer el ID de un enlace de Google Sheets
def extraer_spreadsheet_id(url):
    match = re.search(r'/d/([a-zA-Z0-9-_]+)', url)
    if match:
        return match.group(1)
    return None

def conectar_google_sheets():
    """Autentica con Google Sheets usando los secretos de Streamlit de forma segura."""
    try:
        if "gcp_service_account" not in st.secrets:
            return None
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds_dict = dict(st.secrets["gcp_service_account"])
        if "private_key" in creds_dict:
            creds_dict["private_key"] = str(creds_dict["private_key"]).replace("\\n", "\n")
            
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as temp_file:
            json.dump(creds_dict, temp_file)
            temp_path = temp_file.name
            
        creds = Credentials.from_service_account_file(temp_path, scopes=scopes)
        return gspread.authorize(creds)
    except Exception:
        return None

# =====================================================================
# 2. FUNCIONES DE LÓGICA Y SIMILITUD
# =====================================================================
def extraer_valor_y_unidad(texto):
    if pd.isna(texto):
        return None, ""
    match = re.search(r'(\d+(?:\.\d+)?)\s*(ml|g|kg|l|lt|gr|cc|oz)?', str(texto).lower())
    if match:
        val = float(match.group(1))
        unidad = match.group(2) if match.group(2) else ""
        if unidad in ['gr', 'gramos']: unidad = 'g'
        if unidad in ['lt', 'litros']: unidad = 'l'
        return val, unidad
    return None, ""

def normalizar_texto(texto):
    if pd.isna(texto):
        return ""
    texto = str(texto).upper()
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    texto = re.sub(r'[.,;:_\-/\\()\[\]{{}}""\'!¡?¿#%&=*+]', ' ', texto)
    texto = re.sub(r'\s+', ' ', texto).strip()
    return texto

def procesar_motor(df_matriz, df_cbarras, tolerancia_max=200.0):
    df = df_matriz.copy()
    
    if 'SKU encontrado' not in df.columns:
        df['SKU encontrado'] = ""
    if '% Similitud' not in df.columns:
        df['% Similitud'] = 0.0

    df_cbarras = df_cbarras.dropna(subset=['Material', 'Texto breve de material']).copy()
    df_cbarras['Texto_Norm'] = df_cbarras['Texto breve de material'].apply(normalizar_texto)
    
    datos_maestro = []
    for _, r in df_cbarras.iterrows():
        val, unidad = extraer_valor_y_unidad(r['Texto breve de material'])
        datos_maestro.append({
            'material': str(r['Material']),
            'texto_norm': r['Texto_Norm'],
            'valor': val,
            'unidad': unidad
        })

    for idx, row in df.iterrows():
        sku_actual = str(row.get('SKU', '')).strip()
        
        if sku_actual == "" or pd.isna(row.get('SKU', '')):
            df.at[idx, 'SKU encontrado'] = ""
            df.at[idx, '% Similitud'] = None
            
        elif sku_actual.upper() == "REVISAR":
            desc_original = row.get('Descripción', '')
            desc_buscada = normalizar_texto(desc_original)
            val_buscado, unidad_buscado = extraer_valor_y_unidad(desc_original)
            
            if desc_buscada != "" and len(datos_maestro) > 0:
                mejor_puntaje = -1
                mejor_material = ""
                
                for item in datos_maestro:
                    puntaje_txt = fuzz.ratio(desc_buscada, item['texto_norm'])
                    
                    if val_buscado is not None and item['valor'] is not None:
                        if unidad_buscado and item['unidad'] and unidad_buscado != item['unidad']:
                            puntaje_txt = puntaje_txt * 0.1 
                        else:
                            diferencia = abs(val_buscado - item['valor'])
                            if diferencia > tolerancia_max:
                                puntaje_txt = puntaje_txt * 0.15
                    
                    if puntaje_txt > mejor_puntaje:
                        mejor_puntaje = puntaje_txt
                        mejor_material = item['material']
                
                df.at[idx, 'SKU encontrado'] = mejor_material
                df.at[idx, '% Similitud'] = round(max(0, mejor_puntaje) / 100.0, 4)
            else:
                df.at[idx, 'SKU encontrado'] = ""
                df.at[idx, '% Similitud'] = 0.0
        else:
            df.at[idx, 'SKU encontrado'] = sku_actual
            df.at[idx, '% Similitud'] = 1.0

    return df


# =====================================================================
# 3. INTERFAZ PRINCIPAL Y CARGA DE DATOS DESDE SHEETS
# =====================================================================
if st.button("🚀 Conectar a Google Sheets y Ejecutar Motor", type="primary"):
    with st.spinner("Conectando a las pestañas DATOST y CBARRAS..."):
        try:
            id_matriz = extraer_spreadsheet_id(url_matriz)
            id_cbarras = extraer_spreadsheet_id(url_cbarras)
            
            cliente = conectar_google_sheets()
            
            if cliente and id_matriz and id_cbarras:
                # Método oficial mediante API con gspread
                sh_matriz = cliente.open_by_key(id_matriz)
                ws_datost = sh_matriz.worksheet("DATOST")
                df_matriz = pd.DataFrame(ws_datost.get_all_records())
                
                sh_cbarras = cliente.open_by_key(id_cbarras)
                ws_cbarras = sh_cbarras.worksheet("CBARRAS")
                df_cbarras = pd.DataFrame(ws_cbarras.get_all_records())
            else:
                # Método alternativo por exportación CSV si no hay secretos configurados
                csv_matriz = f"https://docs.google.com/spreadsheets/d/{id_matriz}/gviz/tq?tqx=out:csv&sheet=DATOST"
                csv_cbarras = f"https://docs.google.com/spreadsheets/d/{id_cbarras}/gviz/tq?tqx=out:csv&sheet=CBARRAS"
                
                df_matriz = pd.read_csv(csv_matriz)
                df_cbarras = pd.read_csv(csv_cbarras)

            df_resultado = procesar_motor(df_matriz, df_cbarras)
            st.session_state['df_resultado'] = df_resultado
            st.session_state['df_cbarras'] = df_cbarras
            st.success("¡Datos extraídos correctamente de DATOST y CBARRAS!")
            
        except Exception as e:
            st.error(f"❌ Error al conectar o leer las pestañas. Verifica que las hojas tengan los nombres exactos ('DATOST' y 'CBARRAS') y sean públicas. Detalle: {e}")

# Mostrar resultados y panel de revisión si ya se ejecutó
if 'df_resultado' in st.session_state:
    df_res = st.session_state['df_resultado']
    df_cbarras = st.session_state['df_cbarras']
    
    st.markdown("### 📋 Vista Previa de Resultados")
    st.dataframe(df_res.head(10), use_container_width=True)
    
    mask_revisar = (df_res['% Similitud'] < 0.98) | (df_res['SKU'].astype(str).str.upper() == "REVISAR")
    df_pendientes = df_res[mask_revisar].copy()
    
    df_actualizado = df_res.copy()

    if not df_pendientes.empty:
        st.warning(f"⚠️ Se encontraron **{len(df_pendientes)} elementos** que requieren auditoría manual (< 98%).")
        
        codigos_manuales = []
        if 'SKU MANUAL' in df_cbarras.columns:
            codigos_manuales = [str(c) for c in df_cbarras['SKU MANUAL'].dropna().tolist() if str(c).strip() != ""]

        df_maestro = df_cbarras.dropna(subset=['Material', 'Texto breve de material']).copy()
        maestro_materiales = df_maestro['Material'].astype(str).tolist()
        maestro_textos = df_maestro['Texto breve de material'].astype(str).tolist()
        dict_desc = dict(zip(maestro_materiales, maestro_textos))

        for idx, row in df_pendientes.iterrows():
            desc_original = row.get('Descripción', 'Sin descripción')
            sku_actual = row.get('SKU', '')
            
            with st.expander(f"📦 Revisar: {desc_original} (SKU actual: {sku_actual})"):
                candidatos = process.extract(str(desc_original), maestro_textos, scorer=fuzz.ratio, limit=2)
                
                opciones_map = {}
                opciones_visuales = []
                
                for texto_cand, puntaje, maestro_idx in candidatos:
                    mat_enc = maestro_materiales[maestro_idx]
                    desc_enc = dict_desc.get(mat_enc, "")
                    pct = puntaje / 100.0
                    
                    label_op = f"Candidato: [{mat_enc}] {desc_enc} (Similitud: {pct:.1%})"
                    opciones_map[label_op] = mat_enc
                    opciones_visuales.append(label_op)
                
                opciones_visuales.append("✍️ Ingresar código manualmente (desde SKU MANUAL)")
                
                eleccion = st.radio(
                    f"Seleccione el SKU correcto para la fila {idx}:",
                    options_visuales,
                    key=f"radio_{idx}"
                )
                
                if "Ingresar código manualmente" in eleccion:
                    cod_manual = st.selectbox(
                        "Seleccione de la columna SKU MANUAL:",
                        ["Seleccione..."] + codigos_manuales,
                        key=f"man_{idx}"
                    )
                    if cod_manual != "Seleccione...":
                        df_actualizado.at[idx, 'SKU encontrado'] = cod_manual
                        df_actualizado.at[idx, '% Similitud'] = 1.0
                else:
                    mat_elegido = opciones_map.get(eleccion, "")
                    df_actualizado.at[idx, 'SKU encontrado'] = mat_elegido
                    score_real = fuzz.ratio(str(desc_original), dict_desc.get(mat_elegido, "")) / 100.0
                    df_actualizado.at[idx, '% Similitud'] = round(score_real, 4)
    else:
        st.success("🎉 ¡Todos los productos superan el 98% de similitud!")

    # =====================================================================
    # 4. BOTÓN DE DESCARGA EN EXCEL
    # =====================================================================
    st.markdown("---")
    st.markdown("### 📥 Descargar Archivo Procesado")
    
    df_excel_final = df_actualizado.copy()
    if '% Similitud' in df_excel_final.columns:
        df_excel_final['% Similitud'] = df_excel_final['% Similitud'].apply(lambda x: f"{x*100:.2f}%" if pd.notna(x) else "")

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_excel_final.to_excel(writer, sheet_name='DATOST', index=False)
        df_cbarras.to_excel(writer, sheet_name='CBARRAS', index=False)
    processed_data = output.getvalue()

    st.download_button(
        label="📥 Descargar Excel Actualizado",
        data=processed_data,
        file_name="factPlano_procesado.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary"
    )
