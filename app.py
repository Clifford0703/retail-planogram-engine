import streamlit as st
import pandas as pd
from rapidfuzz import process, fuzz

def modulo_revision_skus(df_matriz, df_cbarras):
    """
    Módulo interactivo en Streamlit para revisar SKUs con < 98% de similitud,
    ofreciendo 2 candidatos automáticos y opción de código manual desde la hoja.
    """
    st.markdown("### 🔍 Módulo de Auditoría y Validación de SKUs (< 98% Similitud)")
    
    # Asegurar columnas de control
    if 'SKU encontrado' not in df_matriz.columns:
        df_matriz['SKU encontrado'] = df_matriz['SKU']
    if '% Similitud' not in df_matriz.columns:
        df_matriz['% Similitud'] = 1.0

    # Filtrar aquellos que necesitan revisión (similitud < 0.98 o marcados como REVISAR)
    mask_revisar = (df_matriz['% Similitud'] < 0.98) | (df_matriz['SKU'].astype(str).str.upper() == "REVISAR")
    df_pendientes = df_matriz[mask_revisar].copy()

    if df_pendientes.empty:
        st.success("🎉 ¡Excelente! No hay productos pendientes de revisión (todos tienen >= 98% de similitud).")
        return df_matriz

    st.warning(f"⚠️ Se encontraron **{len(df_pendientes)} productos** que requieren validación manual o selección de candidato.")

    # Extraer códigos manuales permitidos desde la columna 'SKU MANUAL' (Q5 hacia abajo)
    # Asumimos que df_cbarras o una hoja específica contiene esta columna
    codigos_manuales = []
    if 'SKU MANUAL' in df_cbarras.columns:
        # Tomar valores desde el índice 3 en adelante (equivalente a fila 5 en Excel si 0 es la cabecera)
        codigos_manuales = df_cbarras['SKU MANUAL'].dropna().astype(str).tolist()
    
    # Preparar el maestro para extraer descripciones de los candidatos
    df_maestro = df_cbarras.dropna(subset=['Material', 'Texto breve de material']).copy()
    maestro_materiales = df_maestro['Material'].astype(str).tolist()
    maestro_textos = df_maestro['Texto breve de material'].astype(str).tolist()
    dict_descripciones = dict(zip(maestro_materiales, maestro_textos))

    # Iterar sobre los ítems a revisar de forma interactiva
    df_actualizado = df_matriz.copy()

    for idx, row in df_pendientes.iterrows():
        desc_original = row.get('Descripción', 'Sin descripción')
        sku_actual = row.get('SKU', '')
        
        with st.expander(f"📦 Producto: {desc_original} (SKU actual: {sku_actual})"):
            # Obtener los 2 mejores candidatos usando rapidfuzz
            candidatos = process.extract(str(desc_original), maestro_textos, scorer=fuzz.ratio, limit=2)
            
            opciones_map = {}
            opciones_visuales = []
            
            for texto_cand, puntaje, maestro_idx in candidatos:
                mat_encontrado = maestro_materiales[maestro_idx]
                desc_encontrada = dict_descripciones.get(mat_encontrado, "")
                pct = puntaje / 100.0
                
                label_opcion = f"Candidato 1: [{mat_encontrado}] {desc_encontrada} (Similitud: {pct:.1%})" if not opciones_visuales else f"Candidato 2: [{mat_encontrado}] {desc_encontrada} (Similitud: {pct:.1%})"
                opciones_map[label_opcion] = mat_encontrado
                opciones_visuales.append(label_opcion)

            # Agregar opción de ingreso manual
            opciones_visuales.append("✍️ Ingresar código manualmente (desde SKU MANUAL)")
            
            # Selector para el usuario
            eleccion = st.radio(
                f"Seleccione el código correcto para la fila {idx}:",
                options_visuales,
                key=f"radio_rev_{idx}"
            )

            if "Ingresar código manualmente" in eleccion:
                codigo_manual = st.selectbox(
                    "Seleccione el código de la columna SKU MANUAL:",
                    ["Seleccione..."] + codigos_manuales,
                    key=f"manual_sel_{idx}"
                )
                if codigo_manual != "Seleccione...":
                    df_actualizado.at[idx, 'SKU encontrado'] = codigo_manual
                    df_actualizado.at[idx, '% Similitud'] = 1.0 # Validado manualmente
            else:
                material_seleccionado = opciones_map.get(eleccion, "")
                df_actualizado.at[idx, 'SKU encontrado'] = material_seleccionado
                # Calcular similitud real del candidato elegido
                match_score = fuzz.ratio(str(desc_original), dict_descripciones.get(material_seleccionado, "")) / 100.0
                df_actualizado.at[idx, '% Similitud'] = round(match_score, 4)

    if st.button("💾 Guardar y Aplicar Cambios de Revisión", type="primary"):
        st.success("¡Cambios aplicados correctamente al dashboard!")
        return df_actualizado
    
    return df_actualizado
