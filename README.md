# ContaBot

**Contabilidad inteligente para MYPES peruanas.**

ERP open source: facturación SUNAT, registro de gastos por foto (IA), reportes fiscales, todo desde WhatsApp. Gratis y local para siempre.

---

## Funcionalidades

- **Facturación electrónica SUNAT** — emisión, consulta y anulación
- **Gastos por foto** — envía una foto del recibo y la IA lo registra
- **Reportes fiscales** — PDT 621, SIRE, estado de resultados
- **WhatsApp Bot** — opera todo desde tu celular vía WAHA
- **Multi-empresa** — maneja varios RUCs desde una sola instalación
- **100% local** — tus datos nunca salen de tu servidor

## Inicio rápido (Docker)

```bash
git clone https://github.com/tu-usuario/contabot-os.git
cd contabot-os
cp .env.example .env
# Edita .env con tus datos

docker compose up -d
```

Escanea el QR de WhatsApp en `http://localhost:3000/` y listo.

## Instalación manual

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

pip install -e ".[ai]"
python scripts/setup.py
uvicorn contabot.bot.server:app --host 0.0.0.0 --port 8000
```

## Variables de entorno

| Variable | Descripción | Default |
|----------|-------------|---------|
| `DATABASE_PATH` | Ruta a la base de datos SQLite | `data/db/contabot.db` |
| `XAI_API_KEY` | API key de Grok (opcional, para IA) | — |
| `WAHA_URL` | URL del gateway WhatsApp | `http://localhost:3000` |
| `WAHA_SESSION` | Sesión WAHA | `default` |
| `BOT_COMPANY_NAME` | Nombre de tu empresa | `Mi Empresa` |
| `ESCALATION_CONTACT` | Contacto para escalaciones | `soporte` |
| `LOG_LEVEL` | Nivel de logging | `INFO` |

## Estructura

```
contabot/
├── atencion/     # Clasificación de intenciones y respuestas IA
├── bot/          # WhatsApp bot (webhook WAHA + handler)
├── db/           # Conexión, modelos y migraciones SQLite
├── fiscal/       # Cálculos tributarios, gastos, reportes
└── accounting/   # Métricas: LTV, CAC, churn
```

## Licencia

LGPL-3.0 — puedes usar ContaBot en tu negocio sin restricciones.
Si modificas el código fuente de ContaBot, comparte las mejoras.

---

Hecho en Peru.
