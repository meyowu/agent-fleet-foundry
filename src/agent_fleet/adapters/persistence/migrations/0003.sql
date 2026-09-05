CREATE INDEX resource_leases_run_kind_status
ON resource_leases(run_id, kind, status);
