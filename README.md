# SPL Dashboard — GitHub Pages (sin servidor)

Dashboard estático del Sindicato de Pilotos LATAM.
Se despliega automáticamente en **GitHub Pages** cada vez que subes un nuevo archivo Excel.

## Estructura del repositorio

```
spl-dashboard/
├── data/                    ← 📂 AQUÍ van los archivos Excel de roles
│   ├── CA__DIGOS_IFN.xlsx   ← Tabla de códigos (no borrar)
│   └── *.xlsx               ← Archivos de roles (agregar aquí)
├── docs/                    ← Generado automáticamente (no editar)
│   ├── index.html           ← El dashboard
│   └── data.json            ← Datos pre-procesados (auto-generado)
├── scripts/
│   └── build_data.py        ← Script que genera data.json
├── data_parser.py           ← Parser de archivos Excel
├── requirements.txt
├── SPL_logo.png
└── .github/workflows/
    └── deploy.yml           ← CI/CD: build + deploy automático
```

## Configuración inicial (una sola vez)

### 1. Crear repositorio en GitHub
```bash
git init
git add .
git commit -m "feat: SPL Dashboard inicial"
git remote add origin https://github.com/TU_USUARIO/spl-dashboard.git
git push -u origin main
```

### 2. Activar GitHub Pages
1. En el repo → **Settings** → **Pages**
2. En "Source" selecciona **GitHub Actions**
3. Listo ✓

Después del primer push, el workflow se ejecuta y en ~2 minutos
el dashboard estará en: `https://TU_USUARIO.github.io/spl-dashboard`

## Agregar nuevo mes de datos

```bash
# 1. Copia el archivo a la carpeta data/
cp RolEjecutado_Jun26.xlsx data/

# 2. Commit y push
git add data/RolEjecutado_Jun26.xlsx
git commit -m "feat: agregar rol ejecutado junio 2026"
git push
```

GitHub Actions detecta el push → genera nuevo `data.json` → despliega.
El dashboard se actualiza en ~2 minutos. No necesitas hacer nada más.

## KPIs disponibles

| Vista | KPIs y gráficos |
|-------|----------------|
| **General** | Total/activos, horas prom., sectores, adherencia, distribuciones, actividades, tendencias, top 20 |
| **Piloto** | Horas vs publicado, sectores, adherencia, comparativa vs grupo, evolución histórica, percentil |

## Adherencia

Ratio `horas_ejecutadas / horas_publicadas`:
- **0.0** → No voló nada de lo programado
- **1.0** → Adherencia total
- **> 1.0** → Voló más que lo programado

Se excluyen del promedio grupal los pilotos con ≥ 7 días de VAC / SICK / OOF.

## Ver el dashboard localmente

```bash
# Instalar dependencias
pip install -r requirements.txt

# Generar data.json
python scripts/build_data.py

# Servir con Python
cd docs && python3 -m http.server 8080
# Abrir http://localhost:8080
```
