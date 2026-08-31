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

st.title("📊 Retail Planogram Engine (factplano & dimcodbarras)")
st.markdown("Motor de automatización y homologación conectado directamente a tus Google Sheets oficiales.")
st.markdown("---")

# =====================================================================
# 1. URLS OFICIALES DE GOOGLE SHEETS
# =====================================================================
st.sidebar.header("🔗 Enlaces de Google Sheets")
url_matriz = st.sidebar.text_input(
    "Libro Principal (factplano):",
    value="https://docs.google.com/spreadsheets/d/1pbGYgDB8UBZnm0aJZLGOhZwWYq0IlDO8Uqv2n1-MgxI/edit?usp=sharing"
)
url_cbarras = st.sidebar.text_input(
    "Libro Maestro (dimcodbarras):",
    value="https://docs.google.com/spreadsheets/d/1veTjECI6wlFRqOVg1AKmV0yghxyGR5T0j0Im2AooukM/edit?usp=sharing"
)

def extraer_spreadsheet_id(url):
    match = re.search(r'/d/([a-zA-Z0-9-_]+)', url)
    if match:
        return match.group(1)
    return None

def cargar_hoja_inteligente(id_sheet, nombre_pestaña, palabras_clave):
    """Escanea el archivo CSV para encontrar la fila exacta donde inician los encabezados."""
    csv_url = f"https://docs.google.com/spreadsheets/d/{id_sheet}/gviz/tq?tqx=out:csv&sheet={nombre_pestaña}"
    
    df_temp = pd.read_csv(csv_url, header=None)
    header_row = 0
    
    for idx, row in df_temp.iterrows():
        fila_texto = " ".join(row.astype(str)).lower()
        if any(palabra in fila_texto for palabra in palabras_clave):
            header_row = idx
            break
            
    df = pd.read_csv(csv_url, header=header_row)
    return df

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

def limpiar_y_mapear_columnas(df_matriz, df_cbarras):
    """Homologa y estandariza los nombres de columnas de ambas tablas."""
    df_matriz.columns = [str(c).strip() for c in df_matriz.columns]
    df_cbarras.columns = [str(c).strip() for c in df_cbarras.columns]
    
    # Mapeo flexible para CBARRAS
    mapa_cbarras = {}
    for col in df_cbarras.columns:
        col_lower = col.lower()
        if 'material' in col_lower and 'sku' not in col_lower:
            mapa_cbarras[col] = 'Material'
        elif 'texto' in col_lower or 'descripcion' in col_lower or 'breve' in col_lower:
            mapa_cbarras[col] = 'Texto breve de material'
        elif 'manual' in col_lower:
            mapa_cbarras[col] = 'SKU MANUAL'
            
    df_cbarras = df_cbarras.rename(columns=mapa_cbarras)
    return df_matriz, df_cbarras

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
# 3. INTERFAZ PRINCIPAL Y CARGA DESDE GOOGLE SHEETS
# =====================================================================
if st.button("🚀 Conectar a Google Sheets y Ejecutar Motor", type="primary"):
    with st.spinner("Leyendo las tablas DATOST y CBARRAS desde los enlaces..."):
        try:
            id_matriz = extraer_spreadsheet_id(url_matriz)
            id_cbarras = extraer_spreadsheet_id(url_cbarras)
            
            if not id_matriz or not id_cbarras:
                st.error("❌ Los enlaces de Google Sheets proporcionados no son válidos.")
                st.stop()

            # Carga inteligente detectando encabezados reales en las pestañas exactas
            df_matriz = cargar_hoja_inteligente(id_matriz, "DATOST", ['bandeja', 'descripción', 'sku'])
            df_cbarras = cargar_hoja_inteligente(id_cbarras, "CBARRAS", ['material', 'texto breve'])

            # Normalizar y homologar columnas
            df_matriz, df_cbarras = limpiar_y_mapear_columnas(df_matriz, df_cbarras)

            df_resultado = procesar_motor(df_matriz, df_cbarras)
            st.session_state['df_resultado'] = df_resultado
            st.session_state['df_cbarras'] = df_cbarras
            st.success("¡Datos extraídos y motor ejecutado con éxito desde factplano y dimcodbarras!")
            
        except Exception as e:
            st.error(f"❌ Error al conectar o procesar las tablas. Verifica que las hojas sean públicas ('Cualquier persona con el enlace'). Detalle: {e}")

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
