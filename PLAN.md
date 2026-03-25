# ContaBot Open Source — Plan de Empaquetado

## Qué es
ERP open source para MYPES peruanas. Contabilidad, facturación SUNAT, impuestos,
gastos por foto (IA), reportes financieros — todo desde WhatsApp. Gratis local siempre.

## Estructura objetivo

```
contabot-os/
├── README.md
├── LICENSE                    (LGPL-3.0)
├── pyproject.toml
├── docker-compose.yml         (SQLite + WAHA + ContaBot)
├── .env.example
├── .gitignore
├── contabot/
│   ├── __init__.py
│   ├── config.py              (env vars, zero hardcoded secrets)
│   ├── db/
│   │   ├── __init__.py
│   │   ├── connection.py      (sanitized from core/db/connection.py)
│   │   ├── models.py          (sanitized — sin vault, sin D:/ALPHA)
│   │   ├── session.py         (clean copy)
│   │   └── migration.py       (todas las tablas: facturas, compras, emisores, clientes, contabot_clientes)
│   ├── fiscal/
│   │   ├── __init__.py
│   │   ├── calculator.py      (clean copy — no secrets)
│   │   ├── expenses.py        (clean copy)
│   │   ├── expense_intake.py  (sanitized — sin .xai_key path, solo env var)
│   │   ├── report.py          (clean copy)
│   │   └── financial_report.py (sanitized — sin _leer_xai_key, fix nombre)
│   ├── atencion/
│   │   ├── __init__.py
│   │   ├── intents.py         (clean — ya usa env vars)
│   │   └── responder.py       (sanitized — sin "Grupo Norigal", parametrizado)
│   ├── accounting/
│   │   ├── __init__.py
│   │   ├── models.py, ltv.py, cac.py, churn.py, dashboard.py
│   │   └── migration.py
│   └── bot/
│       ├── __init__.py
│       ├── handler.py         (de core/contabot/bot.py — sanitized)
│       ├── onboarding.py      (clean)
│       ├── weekly_report.py   (clean)
│       └── server.py          (sanitized — env vars para WAHA)
├── scripts/
│   └── setup.py               (inicializar DB, crear tablas, seed data ejemplo)
├── tests/
│   └── test_basic.py
└── data/
    └── db/                    (gitignored, se crea en setup)
```

## Qué sanitizar (del audit)

### CRÍTICO — NO copiar tal cual:
1. core/config/credentials.py → línea 134: `sys.path.insert(0, "D:/ALPHA")` + vault import
2. core/fiscal/expense_intake.py → línea 160: path `.xai_key`
3. core/fiscal/financial_report.py → `_leer_xai_key()` function
4. core/atencion/responder.py → "Grupo Norigal", "Luis" hardcoded
5. core/contabot/server.py → "D:/ALPHA" en docstring, import de active._development

### NO incluir estos archivos:
- migrate_credentials_to_vault.py
- sanitize_creds.py
- Cualquier archivo que importe de `vault`
- data/config/credentials_store.json
- data/config/.xai_key

### Config via env vars (documentar en .env.example):
```
XAI_API_KEY=           # Grok API key (opcional — IA commentary)
WAHA_URL=http://localhost:3000
WAHA_SESSION=default
BOT_COMPANY_NAME=Mi Empresa
DATABASE_PATH=data/db/contabot.db
```

## Fuentes (archivos del monorepo a copiar/sanitizar)

| Destino OS | Fuente monorepo | Sanitización |
|---|---|---|
| contabot/db/connection.py | core/db/connection.py | Ninguna (ya es relativa) |
| contabot/db/models.py | core/db/models.py | Remover vault imports, simplificar |
| contabot/db/session.py | core/db/session.py | Ninguna |
| contabot/fiscal/calculator.py | core/fiscal/calculator.py | Ninguna |
| contabot/fiscal/expenses.py | core/fiscal/expenses.py | Ninguna |
| contabot/fiscal/expense_intake.py | core/fiscal/expense_intake.py | Remover .xai_key path |
| contabot/fiscal/report.py | core/fiscal/report.py | Ninguna |
| contabot/fiscal/financial_report.py | core/fiscal/financial_report.py | Fix nombre, remover _leer_xai_key |
| contabot/atencion/intents.py | core/atencion/intents.py | Ninguna |
| contabot/atencion/responder.py | core/atencion/responder.py | Parametrizar empresa |
| contabot/accounting/* | core/accounting/* | Ninguna |
| contabot/bot/* | core/contabot/* | Sanitizar paths, env vars |

## Próximos pasos
1. Escribir cada archivo limpio (NO copiar, reescribir sin secretos)
2. README.md con pitch, screenshots, setup
3. docker-compose.yml
4. Test E2E
5. git init + push a GitHub público
