"""
generate_updated_reports.py
Genera el Informe del Trabajo Integrador en formato Markdown (.md), Word (.docx) y PDF (.pdf).
"""

import os
import sys
import re
import json
import pandas as pd
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import parse_xml, OxmlElement
from docx.oxml.ns import nsdecls, qn

def sanitize_xml(s: str) -> str:
    if not isinstance(s, str):
        return str(s)
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', s)


from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
TP_FINAL_DIR = os.path.join(BASE_DIR, "..", "TP FINAL")
if not os.path.exists(TP_FINAL_DIR):
    TP_FINAL_DIR = os.path.join(BASE_DIR, "TP FINAL")

MD_PATH = os.path.join(TP_FINAL_DIR, "Informe_Actualizado.md")
DOCX_PATH = os.path.join(TP_FINAL_DIR, "Informe_Actualizado.docx")
PDF_PATH = os.path.join(TP_FINAL_DIR, "Informe_Actualizado.pdf")

# Cargar métricas de evaluación empírica (fuente única de los números del informe)
CSV_PATH = os.path.join(BASE_DIR, "evaluation_results.csv")
if not os.path.exists(CSV_PATH):
    sys.exit(f"No se encontró {CSV_PATH}. Ejecutá primero: python evaluate_model.py")
df_metrics = pd.read_csv(CSV_PATH)

DATASET_PATH = os.path.join(BASE_DIR, "evaluation_dataset.json")
if not os.path.exists(DATASET_PATH):
    sys.exit(f"No se encontró {DATASET_PATH}. Ejecutá primero: python evaluate_model.py")
with open(DATASET_PATH, encoding="utf-8") as _f:
    dataset_stats = json.load(_f)

M_RAND = "Baseline 2025: Carrusel Aleatorio"
M_POP = "Baseline: Top-N Popularidad"
M_HYB = "Recomendador Híbrido (Cascada CF+CB+Pop)"
M_RR = "Recomendador Híbrido + Re-ranking Prescriptivo"
DISPLAY_NAMES = {
    M_RAND: "Carrusel Aleatorio (2025)",
    M_POP: "Top-N Popularidad",
    M_HYB: "Recomendador Híbrido",
    M_RR: "Híbrido + Re-ranking Presc.",
}


def _es(x, dec=2):
    """Formato numérico es-AR: 1.234,56."""
    return f"{x:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _row(model, n):
    sel = df_metrics[(df_metrics["Modelo"] == model) & (df_metrics["Top-N"] == n)]
    if sel.empty:
        sys.exit(f"evaluation_results.csv no tiene la fila: {model} (Top-{n}). Volvé a ejecutar evaluate_model.py")
    return sel.iloc[0]


def build_dataset_section():
    d = dataset_stats
    test_pct = d["test_items"] / d["interactions"] * 100 if d["interactions"] else 0
    return (
        f"- **Población Sintética Controlada:** {_es(d['users'], 0)} usuarios distribuidos en 5 arquetipos de consumo literario "
        "(*Sci-Fi/Distopía*, *Novela/Realismo Mágico*, *Terror/Thriller*, *Fantasía/Aventura*, *Clásico/Ensayo*), "
        f"totalizando **{_es(d['interactions'], 0)} interacciones** de los cinco tipos, con entre {d['purchases_min']} y {d['purchases_max']} "
        f"compras por usuario (media {_es(d['purchases_mean'], 1)}).\n"
        "- **Partición Train / Test:** por cada usuario se retiene el 25% de sus compras y favoritos (mínimo 2) como conjunto de prueba.\n"
        f"  - **Train Set:** {_es(d['train_interactions'], 0)} interacciones, utilizadas para poblar la matriz de preferencias y calcular similitudes.\n"
        f"  - **Test Set (Ground Truth):** {_es(d['test_items'], 0)} compras y favoritos retenidos para evaluar la capacidad predictiva del recomendador.\n"
        f"- **Reproducibilidad:** semilla aleatoria {d['seed']}; tasa de compra casual del {_es(d['casual_purchase_rate'] * 100, 0)}% sobre ítems recomendados no comprados."
    )


def build_confusion_matrices(n=10):
    titles = [
        (M_RAND, f"Baseline 2025 (Carrusel Aleatorio, N={n})"),
        (M_POP, f"Baseline Top-N Popularidad (N={n})"),
        (M_HYB, f"Recomendador Híbrido Propuesto (Cascada CF+CB+Pop, N={n})"),
        (M_RR, f"Recomendador Híbrido + Re-ranking Prescriptivo por Precio (N={n})"),
    ]
    blocks = []
    for model, title in titles:
        r = _row(model, n)
        tp, fp, fn, tn = (int(r[c]) for c in ("TP", "FP", "FN", "TN"))
        blocks.append(
            f"#### Matriz de Confusión: {title}\n"
            "| | Relevante (Test) | No Relevante | Total |\n"
            "| :---: | :---: | :---: | :---: |\n"
            f"| **Recomendado (Top-{n})** | **TP = {_es(tp, 0)}** | **FP = {_es(fp, 0)}** | {_es(tp + fp, 0)} |\n"
            f"| **No Recomendado** | **FN = {_es(fn, 0)}** | **TN = {_es(tn, 0)}** | {_es(fn + tn, 0)} |\n"
            f"| **Total** | {_es(tp + fn, 0)} | {_es(fp + tn, 0)} | {_es(tp + fp + fn + tn, 0)} |\n"
        )
    return "\n".join(blocks)


def build_metrics_table():
    lines = [
        "| Modelo Evaluado | Top-N | TP | FP | FN | TN | Precision@k | Recall@k | F1-Score | Specificity | Accuracy | Hit Rate@k | Catalog Cov. | Ingreso Medio / Usuario |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]
    for model in (M_RAND, M_POP, M_HYB, M_RR):
        for n in (5, 10):
            r = _row(model, n)
            lines.append(
                f"| **{DISPLAY_NAMES[model]}** | {n} | {_es(r['TP'], 0)} | {_es(r['FP'], 0)} | {_es(r['FN'], 0)} | {_es(r['TN'], 0)} "
                f"| {_es(r['Precision@k'], 4)} | {_es(r['Recall@k'], 4)} | {_es(r['F1-Score@k'], 4)} | {_es(r['Specificity'], 4)} "
                f"| {_es(r['Accuracy'], 4)} | {_es(r['Hit Rate@k'])}% | {_es(r['Catalog Cov %'], 1)}% | ${_es(r['Avg Revenue/User ($)'])} |"
            )
    return "\n".join(lines)


def _change(old_v, new_v):
    return f"{_es((new_v - old_v) / old_v * 100, 0)}%" if old_v else "n/d"


def build_interpretation():
    rand, pop, hyb = _row(M_RAND, 10), _row(M_POP, 10), _row(M_HYB, 10)
    return (
        "#### Interpretación Técnica de los Resultados:\n"
        f"1. **Precisión y Sensitividad:** El Recomendador Híbrido pasa de un Recall@10 de **{_es(rand['Recall@k'] * 100)}% a {_es(hyb['Recall@k'] * 100)}%** "
        f"({_change(rand['Recall@k'], hyb['Recall@k'])}) y de una Precision@10 de **{_es(rand['Precision@k'] * 100)}% a {_es(hyb['Precision@k'] * 100)}%** "
        f"({_change(rand['Precision@k'], hyb['Precision@k'])}) respecto al carrusel aleatorio del año 2025.\n"
        f"2. **Tasa de Acierto (Hit Rate@10):** Pasa del **{_es(rand['Hit Rate@k'])}% al {_es(hyb['Hit Rate@k'])}%** de los usuarios con al menos un acierto.\n"
        "3. **Re-ranking prescriptivo:** Al reordenar los mismos ítems, no modifica TP, FP, FN ni TN, y por lo tanto tampoco las métricas de clasificación ni el ingreso simulado.\n"
        f"4. **Diversidad de Catálogo (Catalog Coverage):** La popularidad pura recomienda solo el {_es(pop['Catalog Cov %'], 1)}% de los libros; "
        f"el sistema híbrido cubre el **{_es(hyb['Catalog Cov %'], 1)}% del catálogo**."
    )


def build_financial_list():
    rand, hyb = _row(M_RAND, 10), _row(M_HYB, 10)
    base, new = float(rand["Avg Revenue/User ($)"]), float(hyb["Avg Revenue/User ($)"])
    delta = (new - base) / base * 100 if base else 0.0
    verdict = "lo que supera el objetivo del +10%" if delta >= 10 else "lo que no alcanza el objetivo del +10%"
    return (
        f"- **Año 2025 (Carrusel Aleatorio, N=10):** ingreso promedio simulado de **${_es(base)} por usuario**.\n"
        f"- **Año 2026 (Recomendador Híbrido, N=10):** ingreso promedio simulado de **${_es(new)} por usuario** "
        f"({'+' if delta >= 0 else ''}{_es(delta)}% frente al carrusel aleatorio), {verdict}.\n"
        "- **Re-ranking prescriptivo:** no cambia los libros recomendados, por lo que el ingreso simulado es idéntico al del híbrido. "
        "Su efecto sobre la facturación real depende del comportamiento de compra frente al orden de la lista y no se midió."
    )


os.makedirs(TP_FINAL_DIR, exist_ok=True)
print(f"Generando entregables en: {TP_FINAL_DIR}")

# -----------------------------------------------------------------------------
# 1. CONTENIDO COMPLETO EN MARKDOWN
# -----------------------------------------------------------------------------
md_content = """# Universidad Tecnológica Nacional
## Facultad Regional Concepción del Uruguay
### Ingeniería en Sistemas de Información — Ciencia de Datos

---

# Trabajo Práctico Integrador: Sistema Recomendador Híbrido para Comercio Electrónico
**Metodología CRISP-DM**

**Integrantes:**
- Alu, Gerónimo
- Galarraga, Tadeo
- Gregoraschuk, Lautaro
- Haffner, Ignacio

**Docentes:**
- Dr. Ing. Rottoli, Giovanni Daian
- Ing. Aguirre, Lía Lucía

**Año Académico:** 2025 / 2026  
**Repositorio del Proyecto:** Servicio REST FastAPI con PostgreSQL en la nube  

---

## Índice General
1. [Entendimiento del Negocio (Business Understanding)](#1---entendimiento-del-negocio)
   - 1.1 Contexto y descripción del problema
   - 1.2 Objetivo de negocio
   - 1.3 Objetivos de Data Mining
   - 1.4 Criterios de éxito
2. [Entendimiento de los Datos (Data Understanding)](#2---entendimiento-de-los-datos)
   - 2.1 Descripción de las fuentes de información
   - 2.2 Diseño de atributos de las entidades
   - 2.3 Diseño del esquema relacional en PostgreSQL
   - 2.4 Verificación de la calidad, tipado estricto e integridad
   - 2.5 Análisis exploratorio de datos
3. [Preparación de los Datos (Data Preparation)](#3---preparación-de-los-datos)
   - 3.1 Proceso de extracción y canalización de datos
   - 3.2 Especificación del endpoint `/preference` y escala multivariable
   - 3.3 Desacoplamiento computacional: persistencia de similitudes
4. [Modelado (Modeling)](#4---modelado)
   - 4.1 Arquitectura híbrida en cascada
   - 4.2 Filtro Colaborativo
   - 4.3 Analítica Prescriptiva: Re-ranking por precio
   - 4.4 Mitigación del problema de Cold Start
5. [Evaluación (Evaluation)](#5---evaluación)
   - 5.1 Metodología experimental y dataset de prueba
   - 5.2 Matrices de Confusión experimentales
   - 5.3 Métricas cuantitativas de clasificación y ranking
   - 5.4 Simulación financiera y objetivo de negocio
6. [Despliegue (Deployment)](#6---despliegue)
   - 6.1 Arquitectura de despliegue REST modular
   - 6.2 Seguridad y gestión de credenciales
   - 6.3 Plan de monitoreo y concurrencia
   - 6.4 Conclusiones

---

## 1 - Entendimiento del Negocio

### 1.1 - Contexto y descripción del problema
El comitente gestiona una plataforma de comercio electrónico orientada a la venta de libros. Actualmente, su aplicación web exhibe un carrusel que presenta a los usuarios un conjunto de artículos de forma puramente aleatoria. Esta ausencia de personalización degrada la experiencia del cliente y desaprovecha las intenciones de compra, limitando la tasa de conversión y el volumen de ventas.

El catálogo del negocio posee una restricción operativa única: el vendedor comercializa exactamente **100 artículos literarios desde hace 25 años** y, por una estricta política de cábala, este número es inamovible (no se agregarán nuevos ítems). Sin embargo, el negocio registra un flujo constante de **usuarios nuevos**, quienes compran típicamente entre 7 y 8 libros por año (algunos hasta 10). La inexistencia de una base de datos histórica exigió el diseño desde cero de un modelo de persistencia para usuarios, catálogo y preferencias.

### 1.2 - Objetivo de negocio
El objetivo primordial, cuantificable y estratégico consiste en **aumentar las ganancias por ventas en un 10% para el año 2026**, tomando como base comparativa el volumen facturado en 2025 bajo la modalidad de carrusel aleatorio.

### 1.3 - Objetivos de Data Mining
1. Diseñar e implementar un Sistema Recomendador (SR) híbrido de alto rendimiento que reemplace el carrusel aleatorio.
2. Inferir y ordenar las preferencias de los usuarios a partir de retroalimentación implícita y explícita multidimensional.
3. Resolver el problema de arranque en frío (*cold start*) para usuarios nuevos sin historial transaccional.
4. Integrar analítica prescriptiva basada en precios para maximizar el margen de beneficio en cada recomendación.
5. Exponer el servicio bajo los estándares REST solicitados mediante la especificación OpenAPI provista.

### 1.4 - Criterios de éxito
- **Criterio Técnico:** Disponibilidad del 100% de recomendaciones solicitadas ($n$ ítems exactos), tiempo de respuesta $< 80\text{ ms}$ en inferencia con concurrencia masiva, error rate $< 0.1%$, y mejora estadísticamente comprobable en precisión, recall y F1-score frente a baselines aleatorios y de popularidad.
- **Criterio Comercial:** Aumento de la tasa de conversión y del ticket promedio (AOV), alcanzando un incremento superior al 10% en ingresos por usuario proyectados para 2026.

---

## 2 - Entendimiento de los Datos

### 2.1 - Descripción de las fuentes de información
Se estructuraron cuatro tablas relacionales en PostgreSQL (hospedada en Neon Serverless):
1. `items`: Catálogo cerrado de 100 libros con atributos fijos y campos semiestructurados.
2. `users`: Información de perfil, identificador único y géneros de preferencia declarados.
3. `preferences`: Registro transaccional de eventos de interacción usuario-ítem ponderados.
4. `user_similarities`: Tabla de persistencia física de la matriz de similitud de cosenos entre usuarios, optimizada para lecturas concurrentes instantáneas.

### 2.2 - Diseño de atributos de las entidades

#### Entidad Item (Libros)
| Atributo | Tipo de Dato | Restricción | Uso en Recomendación |
| :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | Clave Primaria (1 a 100) | Identificador unívoco del libro. |
| `name` | `VARCHAR(255)` | NOT NULL | Título para presentación y búsqueda. |
| `author` | `VARCHAR(255)` | NOT NULL | Agrupamiento y filtrado de contenido. |
| `genre` | `VARCHAR(100)` | NOT NULL | Categoría literaria principal (Content-Based). |
| `publish_year` | `INTEGER` | NOT NULL | Antigüedad y contexto temporal. |
| `price` | `REAL / NUMERIC(10,2)` | NOT NULL | Optimización prescriptiva de margen comercial. |
| `attributes` | `JSONB` | Valid JSON | Metadatos flexibles (saga, idioma, formato, páginas). |

#### Entidad User (Clientes)
| Atributo | Tipo de Dato | Restricción | Uso en Recomendación |
| :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | Clave Primaria (Autoincremental) | Identificador unívoco del cliente. |
| `username` | `VARCHAR(100)` | NOT NULL, UNIQUE | Autenticación y perfil de usuario. |
| `preferred_genres`| `JSONB` | Lista de strings | Mitigación de Cold Start (Content-Based inicial). |
| `attributes` | `JSONB` | Valid JSON | Atributos demográficos opcionales (edad, ciudad). |

### 2.3 - Diseño del esquema relacional en PostgreSQL

```sql
-- Catálogo de 100 libros
CREATE TABLE IF NOT EXISTS items (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    author VARCHAR(255) NOT NULL,
    genre VARCHAR(100) NOT NULL,
    publish_year INT NOT NULL,
    price REAL NOT NULL,
    attributes JSONB DEFAULT '{}'::jsonb
);

-- Usuarios registrados
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    preferred_genres JSONB DEFAULT '[]'::jsonb,
    attributes JSONB DEFAULT '{}'::jsonb
);

-- Transacciones e interacciones de preferencias
CREATE TABLE IF NOT EXISTS preferences (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item_id INT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    interaction_type VARCHAR(50) NOT NULL,
    value INT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Persistencia física de similitudes de usuarios (Alta Concurrencia)
CREATE TABLE IF NOT EXISTS user_similarities (
    user_id_1 INT NOT NULL,
    user_id_2 INT NOT NULL,
    similarity_score DOUBLE PRECISION NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id_1, user_id_2)
);
```

### 2.4 - Verificación de la calidad, tipado estricto e integridad
La integridad de los datos se garantiza en múltiples capas:
1. **Tipado Estricto en FastAPI:** Pydantic valida estrictamente todas las entradas HTTP. El tipo de interacción está tipado mediante el enum `InteractionType`, rechazando automáticamente cadenas arbitrarias (`HTTP 422`).
2. **Restricciones Relacionales:** Claves foráneas y tipos nativos (`INTEGER`, `REAL`, `JSONB`) en PostgreSQL impiden inconsistencias de tipo o referencias huérfanas.
3. **Conversión Defensiva en Modelado:** En `recommender.py`, las operaciones vectoriales utilizan `pd.to_numeric(..., errors='coerce').fillna(0)` como defensa ante valores nulos en la matriz dispersa usuario-ítem.

### 2.5 - Análisis exploratorio de datos (EDA)
- **Catálogo:** 100 libros distribuidos en 23 géneros literarios. Predomina *Novela* (23%), *Ciencia Ficción* (8%), *Fantasía* (8%) y *Thriller* (7%), junto a categorías de nicho (*Ensayo*, *Terror*, *Infantil*, *Divulgación*).
- **Rango de Precios:** Rango comprendido entre $1.200,00 y $4.500,00, con un valor medio de $2.135,00 y desviación estándar de $642,00. Esta dispersión ofrece el margen económico necesario para que la analítica prescriptiva favorezca libros de mayor rentabilidad sin desvirtuar el gusto del lector.

---

## 3 - Preparación de los Datos

### 3.1 - Proceso de extracción y canalización de datos
Los datos se extraen mediante consultas parametrizadas en PostgreSQL evitando transferencias masivas de datos:
- El perfilado de usuario y géneros preferidos se obtiene mediante consulta directa por `id`.
- La lista de candidatos de catálogo se recupera mediante indexación por lote (`id = ANY(%s)`).

### 3.2 - Especificación del endpoint `/preference` y escala multivariable
Se diseñó un modelo de **preferencias implícitas y explícitas multidimensional** graduado según el embudo de conversión e-commerce:

```
[VIEW: 1] -> [SEARCH: 2] -> [ADD_TO_CART: 5] -> [FAVORITE: 7] -> [PURCHASE: 10]
```

| Tipo de Interacción | Ponderación (`value`) | Naturaleza de la Señal | Política de Exclusión en Recomendación |
| :--- | :---: | :--- | :--- |
| `VIEW` | 1 | Interés exploratorio pasivo | **No se excluye** (candidato a recompra/conversión). |
| `SEARCH` | 2 | Intención activa de búsqueda | **No se excluye** (señal de afinidad tematica). |
| `ADD_TO_CART` | 5 | Fuerte intención comercial | **No se excluye** (oportunidad de cierre de venta). |
| `FAVORITE` | 7 | Afinidad explícita duradera | **Se excluye** (el usuario ya lo atesora). |
| `PURCHASE` | 10 | Conversión efectiva concretada | **Se excluye** (evitar recomendar lo ya adquirido). |

### 3.3 - Desacoplamiento computacional: persistencia de similitudes
Para sostener la escalabilidad y la concurrencia (muchos usuarios consultando a la vez), el cálculo de similitudes se separa de la inferencia:
1. **Almacenamiento Persistente:** Las similitudes usuario-usuario se persisten en la tabla `user_similarities`. Se precalculan una vez al iniciar el servicio.
2. **Recálculo en Segundo Plano (`BackgroundTasks`):** El endpoint `POST /preference` registra la interacción y responde de inmediato. Solo las señales fuertes (`ADD_TO_CART`, `FAVORITE`, `PURCHASE`) agendan el recálculo; `VIEW` y `SEARCH`, que ocurren constantemente durante la navegación, no lo disparan. Si ya hay un recálculo en curso, el nuevo se omite y el siguiente evento fuerte lo vuelve a agendar. El reemplazo de la tabla (`DELETE` + `INSERT` con `execute_values`) ocurre en una única transacción.
3. **Inferencia sin cómputo vectorial:** El endpoint de recomendación no recalcula similitudes. Ejecuta una consulta indexada por clave primaria: `SELECT user_id_2, similarity_score FROM user_similarities WHERE user_id_1 = %s ORDER BY similarity_score DESC LIMIT 5`.
4. **Limitaciones conocidas:** `BackgroundTasks` se ejecuta dentro del mismo proceso del servidor, y cada recálculo procesa la matriz completa de preferencias. La protección contra recálculos simultáneos es local a cada proceso. En un entorno de producción con varios procesos o alto volumen de eventos fuertes, el recálculo debería delegarse a un trabajo periódico o a una cola.

---

## 4 - Modelado

### 4.1 - Arquitectura híbrida en cascada (Switching & Cascade)
El motor de recomendación opera bajo un esquema en cascada que garantiza siempre la entrega de $n$ recomendaciones:
1. **Paso 1 — Filtro Colaborativo (CF):** Si el usuario tiene historial de interacciones, busca sus 5 vecinos más similares y pondera sus ítems preferidos.
2. **Paso 2 — Filtro Basado en Contenido (CB):** Si la lista no alcanza $n$, completa con libros que coinciden con `preferred_genres` del usuario, priorizados por interacción histórica.
3. **Paso 3 — Popularidad Global (Best Sellers):** Si aún restan cupos, rellena con los libros más interactuados del catálogo general.
4. **Paso 4 — Analítica Prescriptiva (Price Re-ranking):** Reordena la lista final ponderando la relevancia con el precio del ítem.

### 4.2 - Filtro Colaborativo en memoria optimizado
Para los vecinos más cercanos $v \in N_u$ identificados en `user_similarities`, la predicción de preferencia para cada ítem candidato $i$ se rige por:

$$\hat{r}_{u,i} = \frac{\sum_{v \in N_u} \text{sim}(u, v) \cdot r_{v,i}}{\sum_{v \in N_u} \text{sim}(u, v)}$$

Donde $\text{sim}(u, v)$ proviene de la similitud del coseno:

$$\text{sim}(u, v) = \frac{\vec{u} \cdot \vec{v}}{\|\vec{u}\| \|\vec{v}\|}$$

### 4.3 - Analítica Prescriptiva: Re-ranking por precio y margen comercial
Para conectar el algoritmo directamente con el objetivo de negocio (+10% en ganancias en 2026), se implementó una función de re-ranking prescriptivo:

$$\text{Score}_{\text{final}}(u, i) = \text{Score}_{\text{rec}}(u, i) \cdot \left(1 + \alpha \cdot \frac{P_i - P_{\min}}{P_{\max} - P_{\min}}\right)$$

Con $\alpha = 0.20$ y $P_{\min}$, $P_{\max}$ tomados del catálogo completo. El re-ranking se aplica dentro de cada estrategia de la cascada (colaborativa, contenido, popularidad), porque sus puntajes no son comparables entre sí. Ante dos obras de afinidad similar, el sistema prioriza la de mayor precio.

El re-ranking **solo modifica el orden** de los ítems de cada estrategia: no cambia qué libros se recomiendan, por lo que no altera los aciertos medidos en la evaluación. Su efecto sobre la facturación no se mide en este trabajo; se presenta como una decisión de diseño alineada con el objetivo de negocio.

### 4.4 - Mitigación del problema de Cold Start
- **Usuario Nuevo con Géneros Declarados:** Se activa en modo *Content-Based*, recuperando los libros más populares de sus categorías de interés.
- **Usuario Totalmente Anónimo:** Fallback transparente a *Popularidad Global* (Best Sellers históricos).
- **Ítems Nuevos:** Problema inexistente debido a la condición de negocio de catálogo estático (100 libros fijos).

---

## 5 - Evaluación

### 5.1 - Metodología experimental y dataset de prueba (Test Benchmark)
Siguiendo las pautas metodológicas de CRISP-DM, se construyó un entorno de evaluación cuantitativo:
@@DATASET@@

### 5.2 - Matrices de Confusión experimentales
Para cada usuario, la recomendación de Top-$N$ libros sobre el catálogo total de 100 obras clasifica a cada ítem en:
- **Verdadero Positivo (TP):** Ítem recomendado que el usuario efectivamente compró en el Test Set.
- **Falso Positivo (FP):** Ítem recomendado que el usuario no consumió en el Test Set.
- **Falso Negativo (FN):** Ítem que el usuario compró en el Test Set pero el modelo no llegó a sugerir.
- **Verdadero Negativo (TN):** Ítem no recomendado que el usuario no compró (resto del catálogo de 100 libros).

A continuación se presentan las **Matrices de Confusión Agregadas** evaluadas sobre los usuarios del benchmark (una clasificación por cada libro del catálogo y por cada usuario, para $N=10$):

@@MATRICES@@

### 5.3 - Métricas cuantitativas de clasificación y ranking

@@TABLA_METRICAS@@

@@INTERPRETACION@@

### 5.4 - Simulación financiera y objetivo de negocio
El ingreso por usuario es una **simulación** con dos supuestos explícitos del equipo: (a) cada acierto (TP) genera una compra por el precio real del libro, y (b) cada libro recomendado que el usuario no compró tiene una probabilidad del 3% de comprarse de forma casual. La compra casual se decide de manera determinista por par (usuario, libro), de modo que dos modelos que recomiendan los mismos libros obtienen el mismo ingreso.
@@FINANCIERA@@

Los resultados dependen de un dataset sintético y de los supuestos anteriores; deben interpretarse como evidencia de la capacidad predictiva del modelo y no como una proyección de facturación real.

---

## 6 - Despliegue

### 6.1 - Arquitectura de despliegue REST modular
El sistema se organiza en una arquitectura limpia y desacoplada:
- `main.py`: Entrada principal de FastAPI, configuración de ciclo de vida (`startup`), logging e inclusión de routers.
- `config.py`: Gestión tipada de variables de entorno mediante `pydantic-settings` con validación estricta y soporte para SSL de Neon.
- `database.py`: Factoría de conexiones mediante `psycopg2` e inicializador automático de la tabla `user_similarities`.
- `schemas.py`: Modelos de datos DTO (`User`, `Item`, `ItemArray`, `PreferenceInput`, `Error`, `InteractionType`).
- `recommender.py`: Motor matemático con estrategias colaborativa (usando tabla indexada), basada en contenido, popularidad y re-ranking prescriptivo.
- `routers/`: Separación modular de endpoints:
  - `user.py`: `POST /user`, `GET /user/{userId}`
  - `recommendation.py`: `GET /user/{userId}/recommend` con verificación estricta de existencia de usuario (`HTTP 404` en caso negativo).
  - `preference.py`: `POST /preference` con actualización asíncrona de similitudes (solo ante eventos fuertes) mediante `BackgroundTasks`.
- `evaluate_model.py`: Suite de evaluación empírica reproducible que computa matrices de confusión y métricas CRISP-DM.

### 6.2 - Estrategia de seguridad y rotación de credenciales
- Archivo `.env.example` sanitizado completamente con placeholders genéricos (`localhost`, `postgres`, `your_secure_password`).
- Inclusión garantizada de `.env` en `.gitignore`.
- Las credenciales de la base de datos se cargan exclusivamente desde variables de entorno (`.env` o variables estándar de PostgreSQL) y nunca se versionan.

### 6.3 - Plan de monitoreo y concurrencia
- **Manejo de Concurrencia:** Con la persistencia en `user_similarities` y la consulta directa indexada por clave primaria, cada recomendación se resuelve con lecturas indexadas por clave primaria, sin recalcular similitudes dentro de la petición.
- **Niveles de Logging:** Configuración estructurada con niveles `INFO` (flujo y estrategia seleccionada), `WARNING` (activación de fallbacks) y `ERROR` (fallos transaccionales o desconexión).

### 6.4 - Conclusiones
Se implementó un sistema recomendador híbrido en cascada (colaborativo, basado en contenido y popularidad) expuesto mediante una API REST, con persistencia de similitudes, una escala de preferencias de cinco niveles y un re-ranking por precio alineado al objetivo comercial.
1. El recomendador híbrido supera a los baselines aleatorio y de popularidad en precisión, recall y tasa de acierto sobre el dataset sintético de evaluación.
2. La escala de preferencias de cinco niveles (`VIEW`, `SEARCH`, `ADD_TO_CART`, `FAVORITE`, `PURCHASE`) permite distinguir distintos grados de interés.
3. La persistencia de similitudes evita recalcularlas en cada recomendación; el recálculo se agenda en segundo plano ante eventos fuertes.
4. Como trabajo futuro: delegar el recálculo a un trabajo periódico o una cola, y medir el efecto del re-ranking sobre la conversión con datos reales.
"""

md_content = (md_content
    .replace("@@DATASET@@", build_dataset_section())
    .replace("@@MATRICES@@", build_confusion_matrices(10))
    .replace("@@TABLA_METRICAS@@", build_metrics_table())
    .replace("@@INTERPRETACION@@", build_interpretation())
    .replace("@@FINANCIERA@@", build_financial_list()))

# Guardar Markdown
with open(MD_PATH, "w", encoding="utf-8") as f:
    f.write(md_content)
print(f"[OK] Archivo Markdown creado exitosamente: {MD_PATH}")

# -----------------------------------------------------------------------------
# 2. GENERACIÓN DEL DOCUMENTO WORD (.DOCX)
# -----------------------------------------------------------------------------
def set_cell_background(cell, fill_hex):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    tcPr.append(shd)

def create_styled_docx():
    doc = Document()
    
    # Configurar márgenes estándar
    sections = doc.sections
    for section in sections:
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)

    # Estilos de fuente base
    normal_style = doc.styles['Normal']
    normal_style.font.name = 'Calibri'
    normal_style.font.size = Pt(11)
    normal_style.font.color.rgb = RGBColor(51, 51, 51)

    # PORTADA
    title_p = doc.add_paragraph()
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_inst = title_p.add_run("Universidad Tecnológica Nacional\nFacultad Regional Concepción del Uruguay\n")
    run_inst.font.size = Pt(14)
    run_inst.font.bold = True
    run_inst.font.color.rgb = RGBColor(31, 78, 121)

    run_dept = title_p.add_run("Ingeniería en Sistemas de Información — Ciencia de Datos\n\n\n")
    run_dept.font.size = Pt(12)
    run_dept.font.color.rgb = RGBColor(89, 89, 89)

    run_title = title_p.add_run("TRABAJO PRÁCTICO INTEGRADOR\nSISTEMA RECOMENDADOR HÍBRIDO\nPARA COMERCIO ELECTRÓNICO\n")
    run_title.font.size = Pt(22)
    run_title.font.bold = True
    run_title.font.color.rgb = RGBColor(31, 78, 121)

    run_sub = title_p.add_run("Metodología CRISP-DM\n\n\n\n")
    run_sub.font.size = Pt(13)
    run_sub.font.italic = True

    info_p = doc.add_paragraph()
    info_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    info_run = info_p.add_run(
        "Integrantes:\nAlu, Gerónimo | Galarraga, Tadeo | Gregoraschuk, Lautaro | Haffner, Ignacio\n\n"
        "Docentes:\nDr. Ing. Rottoli, Giovanni Daian | Ing. Aguirre, Lía Lucía\n\n"
        "Año Académico: 2025 / 2026\n"
    )
    info_run.font.size = Pt(11)
    info_run.font.color.rgb = RGBColor(51, 51, 51)

    doc.add_page_break()

    # Procesar markdown para poblar el documento
    lines = md_content.split("\n")
    in_table = False
    table_rows = []

    def flush_table():
        nonlocal in_table, table_rows
        if not table_rows:
            return
        
        # Filtrar separadores de markdown |---|---|
        clean_rows = []
        for r in table_rows:
            cells = [c.strip() for c in r.strip().strip('|').split('|')]
            if cells and not all(set(c).issubset({'-', ':', ' '}) for c in cells):
                clean_rows.append(cells)
        
        if clean_rows:
            num_cols = max(len(r) for r in clean_rows)
            t = doc.add_table(rows=len(clean_rows), cols=num_cols)
            t.alignment = WD_TABLE_ALIGNMENT.CENTER
            for r_idx, r_data in enumerate(clean_rows):
                for c_idx in range(num_cols):
                    val = r_data[c_idx] if c_idx < len(r_data) else ""
                    cell = t.cell(r_idx, c_idx)
                    cell.text = sanitize_xml(val)
                    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
                    # Estilo cabecera
                    if r_idx == 0:
                        set_cell_background(cell, "1F4E79")
                        for p in cell.paragraphs:
                            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                            for run in p.runs:
                                run.font.bold = True
                                run.font.color.rgb = RGBColor(255, 255, 255)
                                run.font.size = Pt(9.5)
                    else:
                        bg = "F2F4F7" if r_idx % 2 == 1 else "FFFFFF"
                        set_cell_background(cell, bg)
                        for p in cell.paragraphs:
                            for run in p.runs:
                                run.font.size = Pt(9)
            doc.add_paragraph()
        table_rows = []
        in_table = False

    for line in lines:
        stripped = line.strip()
        
        # Ignorar portada en el flujo de texto
        if stripped.startswith("# Universidad") or stripped.startswith("## Facultad") or stripped.startswith("### Ingeniería"):
            continue
        if stripped.startswith("**Integrantes:**") or stripped.startswith("- Alu,") or stripped.startswith("- Galarraga,") or stripped.startswith("- Gregoraschuk,") or stripped.startswith("- Haffner,"):
            continue
        if stripped.startswith("**Docentes:**") or stripped.startswith("- Dr. Ing.") or stripped.startswith("- Ing. Aguirre"):
            continue
        if stripped.startswith("**Año Académico:**") or stripped.startswith("**Repositorio"):
            continue

        # Tablas Markdown
        if stripped.startswith("|"):
            in_table = True
            table_rows.append(stripped)
            continue
        else:
            if in_table:
                flush_table()

        # Encabezados
        if stripped.startswith("## "):
            h2 = doc.add_heading(level=1)
            run = h2.add_run(sanitize_xml(stripped[3:]))
            run.font.color.rgb = RGBColor(31, 78, 121)
            run.font.bold = True
            continue
        elif stripped.startswith("### "):
            h3 = doc.add_heading(level=2)
            run = h3.add_run(sanitize_xml(stripped[4:]))
            run.font.color.rgb = RGBColor(46, 117, 182)
            run.font.bold = True
            continue
        elif stripped.startswith("#### "):
            h4 = doc.add_heading(level=3)
            run = h4.add_run(sanitize_xml(stripped[5:]))
            run.font.color.rgb = RGBColor(89, 89, 89)
            run.font.bold = True
            continue
        elif stripped.startswith("# "):
            continue
        elif stripped == "---":
            continue

        # Párrafos de texto
        if stripped:
            p = doc.add_paragraph()
            # Tratamiento de viñetas
            if stripped.startswith("- ") or stripped.startswith("● "):
                p.style = 'List Bullet'
                text_content = stripped[2:]
            elif stripped.startswith("1. ") or stripped.startswith("2. ") or stripped.startswith("3. ") or stripped.startswith("4. ") or stripped.startswith("5. "):
                p.style = 'List Number'
                text_content = stripped[3:]
            else:
                text_content = stripped

            # Procesar negritas simples
            parts = text_content.split("**")
            for i, part in enumerate(parts):
                if not part: continue
                run = p.add_run(sanitize_xml(part))
                if i % 2 == 1:
                    run.font.bold = True

    if in_table:
        flush_table()

    doc.save(DOCX_PATH)
    print(f"[OK] Archivo Word (.docx) creado exitosamente: {DOCX_PATH}")


create_styled_docx()

# -----------------------------------------------------------------------------
# 3. GENERACIÓN DEL DOCUMENTO PDF (.PDF) CON REPORTLAB
# -----------------------------------------------------------------------------
class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super(NumberedCanvas, self).__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super(NumberedCanvas, self).showPage()
        super(NumberedCanvas, self).save()

    def draw_page_decorations(self, page_count):
        if self._pageNumber > 1:
            self.saveState()
            self.setFont("Helvetica", 8)
            self.setFillColor(colors.HexColor("#555555"))
            
            # Encabezado
            self.drawString(54, 750, "UTN FRCU — Ciencia de Datos: Trabajo Integrador (Sistema Recomendador)")
            self.setStrokeColor(colors.HexColor("#CCCCCC"))
            self.setLineWidth(0.5)
            self.line(54, 744, 558, 744)

            # Pie de página
            self.line(54, 45, 558, 45)
            page_text = f"Página {self._pageNumber} de {page_count}"
            self.drawRightString(558, 32, page_text)
            self.drawString(54, 32, "Metodología CRISP-DM")
            self.restoreState()

def create_styled_pdf():
    pdf_doc = SimpleDocTemplate(
        PDF_PATH,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=60,
        bottomMargin=54
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'CoverTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#1F4E79"),
        alignment=1,
        spaceAfter=15
    )

    h1_style = ParagraphStyle(
        'Heading1_Custom',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=15,
        leading=18,
        textColor=colors.HexColor("#1F4E79"),
        spaceBefore=16,
        spaceAfter=8,
        keepWithNext=True
    )

    h2_style = ParagraphStyle(
        'Heading2_Custom',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=15,
        textColor=colors.HexColor("#2E75B6"),
        spaceBefore=12,
        spaceAfter=6,
        keepWithNext=True
    )

    h3_style = ParagraphStyle(
        'Heading3_Custom',
        parent=styles['Heading3'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#444444"),
        spaceBefore=8,
        spaceAfter=4,
        keepWithNext=True
    )

    body_style = ParagraphStyle(
        'Body_Custom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#222222"),
        spaceAfter=5
    )

    bullet_style = ParagraphStyle(
        'Bullet_Custom',
        parent=body_style,
        leftIndent=15,
        bulletIndent=5,
        spaceAfter=3
    )

    cell_style = ParagraphStyle(
        'Cell_Custom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor("#222222")
    )

    cell_header_style = ParagraphStyle(
        'Cell_Header',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=colors.white,
        alignment=1
    )

    story = []

    # PORTADA
    story.append(Spacer(1, 40))
    story.append(Paragraph("<b>Universidad Tecnológica Nacional</b><br/>Facultad Regional Concepción del Uruguay", ParagraphStyle('Inst', parent=title_style, fontSize=13, leading=16, textColor=colors.HexColor("#1F4E79"))))
    story.append(Paragraph("Ingeniería en Sistemas de Información — Ciencia de Datos", ParagraphStyle('Dept', parent=title_style, fontSize=11, leading=14, textColor=colors.HexColor("#666666"))))
    story.append(Spacer(1, 30))
    story.append(Paragraph("TRABAJO PRÁCTICO INTEGRADOR<br/>SISTEMA RECOMENDADOR HÍBRIDO<br/>PARA COMERCIO ELECTRÓNICO", title_style))
    story.append(HRFlowable(width="60%", thickness=2, color=colors.HexColor("#1F4E79"), spaceBefore=10, spaceAfter=15))
    story.append(Paragraph("<i>Metodología CRISP-DM</i>", ParagraphStyle('Sub', parent=title_style, fontSize=11, leading=14, textColor=colors.HexColor("#444444"))))
    story.append(Spacer(1, 60))

    cover_info = """
    <b>Integrantes:</b><br/>
    • Alu, Gerónimo<br/>
    • Galarraga, Tadeo<br/>
    • Gregoraschuk, Lautaro<br/>
    • Haffner, Ignacio<br/><br/>
    <b>Docentes:</b><br/>
    • Dr. Ing. Rottoli, Giovanni Daian<br/>
    • Ing. Aguirre, Lía Lucía<br/><br/>
    <b>Año Académico:</b> 2025 / 2026<br/>
    <b>Tecnologías:</b> Python 3.12+ | FastAPI | PostgreSQL (Neon) | Scikit-Learn | Pandas
    """
    story.append(Paragraph(cover_info, ParagraphStyle('CoverInfo', parent=body_style, fontSize=10, leading=15, alignment=1)))
    story.append(PageBreak())

    # Flujo de contenido
    lines = md_content.split("\n")
    in_table = False
    table_lines = []

    def flush_pdf_table():
        nonlocal in_table, table_lines
        if not table_lines:
            return
        clean_rows = []
        for r in table_lines:
            cells = [c.strip() for c in r.strip().strip('|').split('|')]
            if cells and not all(set(c).issubset({'-', ':', ' '}) for c in cells):
                clean_rows.append(cells)
        if clean_rows:
            num_cols = max(len(r) for r in clean_rows)
            # Normalizar ancho
            avail_width = 504 # 612 - 108
            col_width = avail_width / num_cols
            col_widths = [col_width] * num_cols

            data = []
            for r_idx, r_data in enumerate(clean_rows):
                row_cells = []
                for c_idx in range(num_cols):
                    val = r_data[c_idx] if c_idx < len(r_data) else ""
                    val_p = Paragraph(val, cell_header_style if r_idx == 0 else cell_style)
                    row_cells.append(val_p)
                data.append(row_cells)

            t = Table(data, colWidths=col_widths, repeatRows=1)
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#D3D3D3")),
                ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor("#1F4E79")),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor("#F9FAFC"), colors.white])
            ]))
            story.append(Spacer(1, 4))
            story.append(t)
            story.append(Spacer(1, 6))

        table_lines = []
        in_table = False

    for line in lines:
        stripped = line.strip()

        # Filtrar portada
        if stripped.startswith("# Universidad") or stripped.startswith("## Facultad") or stripped.startswith("### Ingeniería"):
            continue
        if stripped.startswith("**Integrantes:**") or stripped.startswith("- Alu,") or stripped.startswith("- Galarraga,") or stripped.startswith("- Gregoraschuk,") or stripped.startswith("- Haffner,"):
            continue
        if stripped.startswith("**Docentes:**") or stripped.startswith("- Dr. Ing.") or stripped.startswith("- Ing. Aguirre"):
            continue
        if stripped.startswith("**Año Académico:**") or stripped.startswith("**Repositorio"):
            continue

        if stripped.startswith("|"):
            in_table = True
            table_lines.append(stripped)
            continue
        else:
            if in_table:
                flush_pdf_table()

        if stripped.startswith("## "):
            story.append(Paragraph(stripped[3:], h1_style))
            continue
        elif stripped.startswith("### "):
            story.append(Paragraph(stripped[4:], h2_style))
            continue
        elif stripped.startswith("#### "):
            story.append(Paragraph(stripped[5:], h3_style))
            continue
        elif stripped.startswith("# "):
            continue
        elif stripped == "---":
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#D0D0D0"), spaceBefore=8, spaceAfter=8))
            continue

        if stripped:
            text_p = stripped
            # Convertir markdown a tags xml de reportlab
            text_p = text_p.replace("&", "&amp;")
            # Reemplazar negritas
            parts = text_p.split("**")
            if len(parts) > 1:
                formatted = ""
                for idx, part in enumerate(parts):
                    if idx % 2 == 1:
                        formatted += f"<b>{part}</b>"
                    else:
                        formatted += part
                text_p = formatted

            if stripped.startswith("- ") or stripped.startswith("● "):
                story.append(Paragraph(f"• {text_p[2:]}", bullet_style))
            elif stripped.startswith("1. ") or stripped.startswith("2. ") or stripped.startswith("3. ") or stripped.startswith("4. ") or stripped.startswith("5. "):
                story.append(Paragraph(text_p, bullet_style))
            else:
                story.append(Paragraph(text_p, body_style))

    if in_table:
        flush_pdf_table()

    pdf_doc.build(story, canvasmaker=NumberedCanvas)
    print(f"[OK] Archivo PDF (.pdf) creado exitosamente: {PDF_PATH}")

create_styled_pdf()
print("\n>>> TODOS LOS INFORMES ACTUALIZADOS HAN SIDO GENERADOS EXITOSAMENTE! <<<")
