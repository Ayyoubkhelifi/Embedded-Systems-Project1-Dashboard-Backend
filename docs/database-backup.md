# Database Backup & Recovery

PostgreSQL snapshot strategy with point-in-time correctness:

```bash
# full logical backup (crash-safe, pg >= 14)
docker exec -t ess-postgres-1 pg_dump -U ess -Fc ess | gzip > ess_$(date +%F_%H%M).sql.gz

# restore
gunzip < ess_2026-10-19_0300.sql.gz | \
  docker exec -i ess-postgres-1 pg_restore -U ess -d ess --clean --if-exists

# verify before trusting it:
pg_restore --list ess_2026-10-19_0300.sql.gz | head
```

### Native installs

```bash
pg_dump -Fc ess > ess_$(date +%F_%H%M).dump   # plain host-run equivalent
pg_restore -d ess --clean --if-existers ess_2026-10-19_0300.dump
```

## Gateway SQLite buffer (`buffer.sqlite3`)

The buffer exists to survive restarts/outages, not to be "data of record" —
backend already ACKs what it got. WAL mode keeps concurrent readers happy.

```bash
# hot backup (safe while gateway runs)
sqlite3 ~/.ess-gateway/buffer.sqlite3 ".backup '/opt/ess/buffer_$(date +%F).sqlite3'"
```

After restoring backend from a snapshot, gateway duplicates are harmless:
backend unique index silently converts re-forwarded packets to
`{"stored": false, "duplicate": true}` 200s and the buffer drains.

## Recurrence

- Schedule with cron/systemd-timer nightly, keep 14 daily + 8 weekly.
- Test restores quarterly (see `pg_restore --list` above).
- Store off-host (S3, NFS, or another box) — a snapshot living only on the
  same server is not a backup.

## Recovery matrix

| Scenario | Action |
|----------|--------|
| Lost readings, gateway buffer intact | nothing to do — gateway re-forwards; dedup makes it idempotent |
| Backend wiped | restore pg snapshot; gateway will replay buffer successfully |
| Schema change breaks version | `alembic downgrade -1` only if trivial; prefer redeploy of prior backend image |
| Gateway disk dead | service restarts with fresh buffer (data loss = only undelivered, unACKed frames) |
