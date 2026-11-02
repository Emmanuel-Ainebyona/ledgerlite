# API reference

Base path `/api`. Responses: `{"data": ...}` (+ `"meta": {page, per_page, total, pages}` for lists) or `{"error": {"code", "message", "details"?}}`.
Authenticate with `Authorization: Bearer <token>` from `POST /api/auth/login`. Public endpoints: `GET /api/health`, `POST /api/auth/register`, `POST /api/auth/login`.
List endpoints accept `q`, `page`, `per_page` (max 100), `sort`, `order=asc|desc` and resource-specific filters.

## Endpoints (generated from the running app)

| Path | Methods |
|---|---|
| `/api/accounts` | GET |
| `/api/accounts` | POST |
| `/api/accounts/Falserid>` | DELETE |
| `/api/accounts/Falserid>` | GET |
| `/api/accounts/Falserid>` | PATCH, PUT |
| `/api/audit` | GET |
| `/api/auth/login` | POST |
| `/api/auth/logout` | POST |
| `/api/auth/me` | GET |
| `/api/auth/register` | POST |
| `/api/customers` | GET |
| `/api/customers` | POST |
| `/api/customers/Falserid>` | DELETE |
| `/api/customers/Falserid>` | GET |
| `/api/customers/Falserid>` | PATCH, PUT |
| `/api/directory` | GET |
| `/api/health` | GET |
| `/api/income-statement` | GET |
| `/api/invoices` | GET |
| `/api/invoices` | POST |
| `/api/invoices/Falseiid>` | GET |
| `/api/invoices/Falseiid>/payments` | POST |
| `/api/invoices/Falseiid>/void` | POST |
| `/api/journal` | GET |
| `/api/journal` | POST |
| `/api/journal/Falseeid>` | GET |
| `/api/journal/Falseeid>/reverse` | POST |
| `/api/stats` | GET |
| `/api/trial-balance` | GET |
| `/api/users` | GET |
| `/api/users/Falserid>` | GET |
| `/api/users/Falserid>` | PATCH, PUT |
| `/api/users/Falseuid>/reset-password` | POST |

## Example

```bash
TOKEN=$(curl -s localhost:8000/api/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"admin@demo.test","password":"Demo-Pass-2026!"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["token"])')
curl -s localhost:8000/api/stats -H "Authorization: Bearer $TOKEN"
```
