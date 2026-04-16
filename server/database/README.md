# Database Setup

This service is PostgreSQL-only. SQLite is no longer supported anywhere in `server/database`.

## User Onboarding Flow

- Each NFC tag maps to one unique `nfc_tag_id`.
- On each tap, the device checks whether that NFC tag already has a complete profile.
- If the profile is missing or incomplete, the OLED shows a registration QR that opens the hosted form.
- Submitting the registration form creates or updates the user row and stores a password hash.
- After registration, tap the NFC card again so the device can reload the profile.
- `user_password` is stored as a password hash, not plain text.
- `user_name` only allows unaccented letters, digits, and underscores.
- `name` only allows letters and spaces, including accented letters.
- The device-facing profile endpoint returns an ASCII-only playback name so Vietnamese accents do not break pronunciation downstream.

## Requirements

- PostgreSQL 14+ running locally or reachable over the network
- `psql` CLI available
- Python environment with the packages from `requirements.txt`

## Connection String

The app reads `DATABASE_URL` only from `server/database/.env`.
It does not fall back to shell environment variables or built-in default values.

Format:

```env
DATABASE_URL=postgresql://<user>:<password>@<host>:<port>/<database>
```

Local development default used in this folder:

```env
DATABASE_URL=postgresql://ss_project_admin:admin123@localhost:5432/ss_project
```

## 1. Start PostgreSQL

If you installed PostgreSQL with Homebrew:

```bash
brew services start postgresql@18
pg_isready -h localhost -p 5432
```

If you use another PostgreSQL install, just make sure the server is listening on the host and port from `DATABASE_URL`.

## 2. Create the Role and Database

Open `psql` with a superuser account:

```bash
psql postgres
```

Run:

```sql
DROP DATABASE IF EXISTS ss_project WITH (FORCE);
DROP ROLE IF EXISTS ss_project_admin;
CREATE ROLE ss_project_admin WITH LOGIN PASSWORD 'admin123';
CREATE DATABASE ss_project OWNER ss_project_admin;
\q
```

If you want different credentials, update both the SQL above and `server/database/.env`.

## 3. Configure Environment Variables

Copy the example file and adjust values if needed:

```bash
cp server/database/.env.example server/database/.env
```

Important fields:

- `DATABASE_URL`: PostgreSQL connection string stored in `server/database/.env`
- Backend / AI variables now live in `server/backend/.env`, not in `server/database/.env`

## Device Config

The ESP32 uses one shared server base URL in [secrets.example.h](/Users/phatv/Documents/dev-local/smart-speaker/include/secrets.example.h) and [secrets.h](/Users/phatv/Documents/dev-local/smart-speaker/include/secrets.h):

```c
#define SERVER_URL "https://ssproject.hyperformancelabs.click"
```

The firmware derives both the profile API endpoint and the registration page from this value.

## 4. Install Python Dependencies

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r server/database/requirements.txt
```

## 5. Initialize the Schema

You have two supported options.

Option A: let Flask-SQLAlchemy create tables on startup.

```bash
python3 server/database/app.py
```

Option B: create the PostgreSQL schema explicitly first.

```bash
psql postgresql://ss_project_admin:admin123@localhost:5432/ss_project -f server/database/schema.sql
python3 server/database/app.py
```

`schema.sql` is PostgreSQL-specific and safe to run multiple times because it uses `IF NOT EXISTS` where applicable.

If you already created the old schema before adding `user_name` and `user_password`, rerun:

```bash
psql postgresql://ss_project_admin:admin123@localhost:5432/ss_project -f server/database/schema.sql
```

The script now also updates the existing `users` table by:

- adding `user_name` if missing
- adding `user_password` if missing
- removing the `NOT NULL` constraint from `name`

## 6. Verify the Service

Health check:

```bash
curl http://localhost:8386/health
```

Expected response when PostgreSQL is reachable:

```json
{
  "status": "ok",
  "database": "postgresql"
}
```

## Production Deploy

To keep the public endpoint responsive, deploy the Flask service as an always-on web process from the `server/database` directory.

- Do not run the built-in Flask debug server in production.
- Use the included [Procfile](/Users/phatv/Documents/dev-local/smart-speaker/server/database/Procfile) and [gunicorn.conf.py](/Users/phatv/Documents/dev-local/smart-speaker/server/database/gunicorn.conf.py).
- Keep the application service and PostgreSQL in the same region or on the same provider network.
- Disable any platform idle sleep or scale-to-zero setting for the web service.
- Point health checks at `/health` so the platform can keep the process alive.

Manual launch example:

```bash
cd server/database
gunicorn --config gunicorn.conf.py app:app
```

## Notes

- The app validates that `DATABASE_URL` from `server/database/.env` uses a PostgreSQL URI.
- JSON fields use PostgreSQL `JSONB`.
- UUID primary keys are generated in Python and also supported by `schema.sql` through `pgcrypto`.
- The `/health` endpoint checks the actual database connection, not just Flask process liveness.
- `user_name` is unique when provided.
- `user_password` is hashed before being stored in PostgreSQL.

## Common Errors

`password authentication failed for user`

- The username or password in `DATABASE_URL` does not match the PostgreSQL role.

`database "ss_project" does not exist`

- Create the database first with `CREATE DATABASE ss_project OWNER ss_project_admin;`.

`localhost:5432 - no response`

- PostgreSQL is not running, is listening on another port, or your `DATABASE_URL` points to the wrong host.
