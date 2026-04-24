# Deploy — opciones para que otra persona pruebe el proyecto

Tienes 4 caminos según cuánto quieres mostrar y cuánto estás dispuesto a gastar/mantener.

| # | Opción | Qué ve la persona | Costo/mes | Esfuerzo | Permanente |
|---|---|---|---|---|---|
| 1 | **Solo docs en GitHub Pages** | Presentaciones, PDFs, arquitectura, código | $0 | Bajo | Sí |
| 2 | **Docs + demo en video** | Opción 1 + video del pipeline corriendo | $0 | Bajo | Sí |
| 3 | **Stack live en VPS** | Prefect UI, MinIO, Grafana corriendo real | $5–20 | Medio | Sí (mientras pagues) |
| 4 | **Deploy AWS completo** | Todo en AWS real, multi-AZ, serverless | ~$200 | Alto | Sí |

**Recomendación para portfolio / aplicación a empleo:** combinar **Opción 1 + 2**. Docs siempre disponibles, video de 2 min que muestra el sistema vivo, sin mantenimiento ni costo.

---

## Opción 1 — Solo docs en GitHub Pages (recomendada)

Publica toda la documentación HTML + PDFs en una URL pública:

```
https://TU_USER.github.io/legaldataplatform/
├── index.html                 ← landing page con todos los links
├── presentacion.html          ← versión niños
├── presentacion-pro.html      ← versión profesional
├── manual-uso.html            ← manual paso a paso
└── pdf/                       ← los 9 PDFs descargables
```

### Pasos (5 minutos)

1. **Crea el repo en GitHub:**
   ```bash
   cd E:\Proyectos\LegalDataPlatform
   git init
   git add .
   git commit -m "initial"
   gh repo create legaldataplatform --public --source=. --push
   ```

2. **Activa GitHub Pages:**
   - GitHub → tu repo → Settings → Pages
   - Source: **GitHub Actions**

3. **El workflow ya está listo** (`.github/workflows/deploy-docs.yml`). Al hacer push a `main` se publica automáticamente.

4. **Comparte el link:**
   ```
   https://TU_USER.github.io/legaldataplatform/
   ```

### Qué ve la otra persona

- Landing con resumen ejecutivo
- Las 3 presentaciones (niños, profesional, manual de uso) navegables
- Los 9 PDFs descargables
- Código fuente del repo en un click

---

## Opción 2 — Docs + demo en video

A la Opción 1 le agregas un video corto mostrando el sistema corriendo.

### Cómo grabarlo

Herramientas gratis:
- **Loom** (https://loom.com) — comparte un link, el video queda hospedado
- **OBS** (https://obsproject.com) — graba local, sube a YouTube
- **ScreenToGif** — para GIFs en Windows
- **QuickTime** — para macOS

### Qué grabar (script de 2–3 min)

```
00:00 - Intro: "Esta es LegalDataPlatform. Voy a mostrarles el pipeline
                corriendo end-to-end en local."

00:15 - Terminal: docker compose up -d
                  Muestra los 6 contenedores arriba.

00:35 - Terminal: python scripts/seed_data.py
                  Muestra la generación de 27K registros.

00:50 - Terminal: make pipeline
                  Muestra los logs estructurados pasando por las stages.

01:30 - Browser: http://localhost:4200
                  Muestra el flow run exitoso en Prefect UI con timings.

01:50 - Browser: http://localhost:9001
                  Muestra los buckets Bronze/Silver con Parquet generados.

02:10 - Browser: http://localhost:3000
                  Muestra Grafana con métricas de records_loaded.

02:25 - Terminal: psql ... SELECT count(*) FROM legal_documents
                  Muestra los datos en PostgreSQL.

02:40 - Cierre: "Código, presentación y docs en <url de GitHub Pages>"
```

Sube el video a YouTube unlisted o Loom, y agrega el link al README y a la landing page.

---

## Opción 3 — Stack live en VPS

Deja el sistema corriendo 24/7 en un servidor propio con URLs públicas:

```
https://prefect.tudominio.com       ← Prefect UI
https://minio.tudominio.com         ← MinIO
https://grafana.tudominio.com       ← Dashboards
```

### Proveedores económicos

| Proveedor | Spec mínimo | Costo/mes | Notas |
|---|---|---|---|
| **Oracle Cloud Free Tier** | 4 vCPU ARM, 24 GB RAM | **$0** (Always Free) | ¡Gratis para siempre! Pero aprovisionar toma paciencia. |
| **Hetzner Cloud CAX11** | 2 vCPU ARM, 4 GB RAM | €3.79 | Mejor relación precio/performance. |
| **Railway** | 1 vCPU, 1 GB RAM | $5 (trial gratis) | Deploy desde git, HTTPS automático. |
| **Fly.io** | Shared CPU, 256 MB | Desde $0 (tier free) | Regions globales. |
| **DigitalOcean** | 2 vCPU, 4 GB | $24 | UI familiar, snapshots fáciles. |

### Arquitectura recomendada para VPS

```
                        Internet
                           ↓
                  ┌─────────────────┐
                  │  Caddy / Traefik │  HTTPS + basic auth
                  └────────┬─────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ↓                 ↓                 ↓
    Prefect UI        MinIO Console      Grafana
    :4200             :9001              :3000
         │                 │                 │
         └────────┬────────┴─────────┬──────┘
                  ↓                  ↓
             Postgres 16         (all in docker-compose)
```

### Pasos generales

1. Compra/activa el VPS.
2. Instala Docker + Docker Compose.
3. Clona el repo.
4. Agrega [Caddy](https://caddyserver.com/) como reverse proxy con HTTPS automático (necesita un dominio apuntando al IP).
5. Agrega basic auth para que no sea público-abierto.
6. `docker compose up -d`.

Hay un ejemplo de config Caddy en [infra/docker/Caddyfile.example](infra/docker/Caddyfile.example).

### Riesgos a considerar

- **Seguridad:** nunca expongas PgBouncer/Postgres al internet. Solo las UIs vía reverse proxy con auth.
- **Secretos:** pon las credenciales en variables de entorno del VPS, no en el repo.
- **Backups:** snapshot periódico del volumen de Postgres.
- **Data privacy:** si usas datos reales, necesitas encriptación + compliance.

---

## Opción 4 — Deploy AWS completo

Esta es la versión "production-grade". Usa el Terraform que ya existe en [infra/terraform/](infra/terraform/).

### Lo que se provisiona

- Aurora PostgreSQL Serverless v2 (multi-AZ)
- S3 buckets (Bronze/Silver/Gold/Quarantine) con KMS + versioning
- SQS + DLQ
- Lambda handlers
- Glue PySpark job
- Secrets Manager
- IAM roles y policies

### Costo estimado

~$200/mes en carga moderada (detallado en [docs/AWS_DEPLOYMENT.md](docs/AWS_DEPLOYMENT.md)).

### Cuándo usarla

Solo si:
- Ya tienes cuenta AWS con billing activo.
- Quieres demostrarlo corriendo en producción real (no demo).
- Estás dispuesto a mantener la infraestructura (monitoreo, costos, rotación de keys).

Para una entrevista, **la Opción 1+2 suele ser más impactante** porque demuestra que pensaste en costos y en experiencia del evaluador (nadie quiere pagar $200 por probar algo 5 min).

---

## Mi recomendación concreta

**Ruta sugerida para aplicar al puesto:**

1. Hoy: implementar Opción 1 (GitHub Pages con las docs y presentaciones).
2. Mañana: grabar el video de 2–3 min (Opción 2).
3. En el mensaje de aplicación incluir:
   - Link a la landing de GitHub Pages.
   - Link al video.
   - Link al repo de GitHub.
   - Mención de que el stack se levanta local con `bash scripts/setup.sh` si quieren validarlo.
4. Si en la entrevista técnica piden verlo corriendo: deploy temporal en Opción 3 (Hetzner €4 por un mes).

Los archivos para Opción 1 ya están listos en este commit. Para Opción 3 tienes el Caddyfile de ejemplo.
