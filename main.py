import json
import numpy as np
import pandas as pd

# --- CAJA 1: INGESTA ---
def extraer_datos_json(ruta_archivo):
    """Abre el JSON y lo convierte en un diccionario."""
    print(f"-> Leyendo el archivo: {ruta_archivo}")
    with open(ruta_archivo, 'r') as archivo:
        return json.load(archivo)

# --- CAJA 2: TRANSFORMACIÓN ---
def transformar_grids_a_filas(tarea_json, id_tarea):
    """Aplana las matrices y arma la estructura de la tabla."""
    print("-> Transformando matrices a formato tabular...")
    filas_datos = []
    
    for fase in ['train', 'test']:
        if fase in tarea_json:
            for indice, ejemplo in enumerate(tarea_json[fase]):
                for tipo_grid in ['input', 'output']:
                    matriz = np.array(ejemplo[tipo_grid])
                    
                    fila = {
                        "id_tarea": id_tarea,
                        "fase": fase,
                        "num_ejemplo": indice + 1,
                        "tipo_grid": tipo_grid,
                        "filas": matriz.shape[0],
                        "columnas": matriz.shape[1],
                        "matriz_plana": matriz.flatten().tolist()
                    }
                    filas_datos.append(fila)
    
    return pd.DataFrame(filas_datos)

# --- CAJA 3: ALMACENAMIENTO ---
def guardar_como_parquet(dataframe, ruta_salida):
    """Guarda la tabla final en un archivo .parquet ultraligero."""
    print(f"-> Guardando base de datos en: {ruta_salida}")
    dataframe.to_parquet(ruta_salida, engine='pyarrow')
    print("✅ ¡Pipeline ejecutado con éxito!")

# --- EL ORQUESTADOR PRINCIPAL ---
# Este bloque solo se ejecuta si corres este archivo directamente
if __name__ == "__main__":
    print("🚀 INICIANDO ETL DE ARC-AGI...")
    
    # 1. Definimos las rutas
    archivo_entrada = 'dummy_task.json'
    archivo_salida = 'base_analitica.parquet'
    
    # 2. Ejecutamos paso a paso usando nuestras funciones
    datos_crudos = extraer_datos_json(archivo_entrada)
    
    tabla_transformada = transformar_grids_a_filas(datos_crudos, id_tarea="dummy_001")
    
    guardar_como_parquet(tabla_transformada, archivo_salida)