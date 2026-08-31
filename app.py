import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from rapidfuzz import process, fuzz
import unicodedata
import re
import tempfile
import json

# =====================================================================
# CONFIGURACIÓN DE LA PÁGINA
# =====================================================================
st.set_page_config(page_title="Retail Planogram Engine", page_icon="📊", layout="wide")

st.title("📊 Retail Planogram Engine")
st.markdown("Motor de automatización, homologación y sincronización bidireccional con Google Sheets (**factPlano**).")
st.markdown("---")

# =====================================================================
# 1. FUNCIÓN DE CONEXIÓN CON RECONSTRUCCIÓN PEM MATEMÁTICA
# =====================================================================
def conectar_google_sheets():
    """Autentica limpiando y reestructurando la clave privada en bloques exactos de 64 caracteres."""
    try:
        if "gcp_service_account" not in st.secrets:
            st.error("⚠️ No se encontraron los secretos de GCP en Streamlit.")
            return None
            
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        creds_dict = dict(st.secrets["gcp_service_account"])
        
        # Reconstrucción estricta del formato PEM para evitar errores de offset
        if "private_key" in creds_dict:
            pk = str(creds_dict["private_key"])
            
            # 1. Quitar encabezados y pies actuales
            pk = pk.replace("-----BEGIN PRIVATE KEY-----", "")
            pk = pk.replace("-----END PRIVATE KEY-----", "")
            
            # 2. Eliminar cualquier espacio, salto de línea o tabulación residual
            pk = "".join(pk.split())
            
            # 3. Dividir el contenido base64 en bloques limpios exactamente de 64 caracteres
            chunks = [pk[i:i+64] for i in range(0, len(pk), 64)]
            
            # 4. Reensamblar la llave privada con la estructura estándar exacta
            pk_reconstruida = "-----BEGIN PRIVATE KEY-----\n" + "\n".join(chunks) + "\n-----END PRIVATE KEY-----\n"
            creds_dict["private_key"] = pk_reconstruida
            
        # Crear archivo temporal seguro con el diccionario normalizado
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as temp_file:
            json.dump(creds_dict, temp_file)
            temp_path = temp_file.name
            
        creds = Credentials.from_service_account_file(temp_path, scopes=scopes)
        cliente = gspread.authorize(creds)
        return cliente
    except Exception as e:
        st.error(f"❌ Error de autenticación: {e}")
        return None

def cargar_datos_seguros():
    cliente = conectar_google_sheets()
    if not cliente:
        return None, None
    try:
        sh = cliente.open("factPlano")
        ws_matriz = sh.worksheet("MATRIZ")
        ws_cbarras = sh.worksheet("CBARRAS")
        
        df_matriz = pd.DataFrame(ws_matriz.get_all_records())
        df_cbarras = pd.DataFrame(ws_cbarras.get_all_records())
        
        return df_matriz, df_cbarras
    except Exception as e:
        st.error(f"❌ Error al conectar o leer el archivo 'factPlano': {e}")
        return None, None

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
# 3. INTERFAZ DE USUARIO
# =====================================================================
st.info("Haz clic en el botón para iniciar la conexión con Google Sheets y procesar las reglas del motor.")

if st.button("🚀 Ejecutar Motor y Cargar Datos", type="primary"):
    with st.spinner("Conectando con factPlano y procesando homologaciones..."):
        df_matriz, df_cbarras = cargar_datos_seguros()
        
        if df_matriz is not None and df_cbarras is not None:
            df_resultado = procesar_motor(df_matriz, df_cbarras)
            st.session_state['df_resultado'] = df_resultado
            st.session_state['df_cbarras'] = df_cbarras
            st.success("¡Datos procesados correctamente!")

# Mostrar resultados y panel de revisión si ya se ejecutó
if 'df_resultado' in st.session_state:
    df_res = st.session_state['df_resultado']
    df_cbarras = st.session_state['df_cbarras']
    
    st.markdown("### 📋 Vista Previa de Resultados")
    st.dataframe(df_res.head(10), use_container_width=True)
    
    mask_revisar = (df_res['% Similitud'] < 0.98) | (df_res['SKU'].astype(str).str.upper() == "REVISAR")
    df_pendientes = df_res[mask_revisar].copy()
    
    if not df_pendientes.empty:
        st.warning(f"⚠️ Se encontraron **{len(df_pendientes)} elementos** que requieren auditoría manual (< 98%).")
        
        codigos_manuales = []
        if 'SKU MANUAL' in df_cbarras.columns:
            codigos_manuales = [str(c) for c in df_cbarras['SKU MANUAL'].dropna().tolist() if str(c).strip() != ""]

        df_maestro = df_cbarras.dropna(subset=['Material', 'Texto breve de material']).copy()
        maestro_materiales = df_maestro['Material'].astype(str).tolist()
        maestro_textos = df_maestro['Texto breve de material'].astype(str).tolist()
        dict_desc = dict(zip(maestro_materiales, maestro_textos))

        df_actualizado = df_res.copy()

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
        
        if st.button("💾 Guardar y Sincronizar Cambios en factPlano", type="primary"):
            with st.spinner("Escribiendo cambios en Google Sheets..."):
                try:
                    cliente = conectar_google_sheets()
                    if cliente:
                        sh = cliente.open("factPlano")
                        worksheet = sh.worksheet("MATRIZ")
                        
                        headers = worksheet.row_values(1)
                        if "SKU encontrado" in headers and "% Similitud" in headers:
                            col_s = headers.index("SKU encontrado") + 1
                            col_m = headers.index("% Similitud") + 1
                            
                            lista_skus = df_actualizado['SKU encontrado'].tolist()
                            lista_sims = df_actualizado['% Similitud'].apply(lambda x: f"{x*100:.2f}%" if pd.notna(x) else "").tolist()
                            
                            fila_inicio = 6
                            rango_s = f"{gspread.utils.rowcol_to_a1(fila_inicio, col_s)}:{gspread.utils.rowcol_to_a1(fila_inicio + len(lista_skus) - 1, col_s)}"
                            rango_m = f"{gspread.utils.rowcol_to_a1(fila_inicio, col_m)}:{gspread.utils.rowcol_to_a1(fila_inicio + len(lista_sims) - 1, col_m)}"
                            
                            worksheet.update(rango_s, [[v] for v in lista_skus])
                            worksheet.update(rango_m, [[v] for v in lista_sims])
                            
                            st.success("✅ ¡Cambios sincronizados exitosamente en Google Sheets!")
                        else:
                            st.error("No se encontraron las columnas de salida en la hoja MATRIZ.")
                except Exception as e:
                    st.error(f"Error al escribir en Google Sheets: {e}")
    else:
        st.success("🎉 ¡Todos los productos superan el 98% de similitud!")
