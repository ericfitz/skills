-- Lookup tables
CREATE TABLE IF NOT EXISTS result_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS fuzzers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS servers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    base_url TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS paths (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    contract_path TEXT
);

CREATE TABLE IF NOT EXISTS http_methods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    method TEXT NOT NULL UNIQUE
);

-- Main tables
CREATE TABLE IF NOT EXISTS tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_id TEXT NOT NULL UNIQUE,
    test_number INTEGER NOT NULL,
    trace_id TEXT NOT NULL,
    scenario TEXT NOT NULL,
    expected_result TEXT NOT NULL,
    result_type_id INTEGER NOT NULL,
    fuzzer_id INTEGER NOT NULL,
    server_id INTEGER NOT NULL,
    path_id INTEGER NOT NULL,
    result_reason TEXT,
    result_details TEXT,
    source_file TEXT NOT NULL,
    is_false_positive BOOLEAN DEFAULT 0,
    fp_rule TEXT,
    FOREIGN KEY (result_type_id) REFERENCES result_types(id),
    FOREIGN KEY (fuzzer_id) REFERENCES fuzzers(id),
    FOREIGN KEY (server_id) REFERENCES servers(id),
    FOREIGN KEY (path_id) REFERENCES paths(id)
);

CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_id INTEGER NOT NULL UNIQUE,
    http_method_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    request_body TEXT,
    FOREIGN KEY (test_id) REFERENCES tests(id) ON DELETE CASCADE,
    FOREIGN KEY (http_method_id) REFERENCES http_methods(id)
);

CREATE TABLE IF NOT EXISTS responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_id INTEGER NOT NULL UNIQUE,
    http_method_id INTEGER NOT NULL,
    response_code INTEGER NOT NULL,
    response_time_ms INTEGER,
    num_words INTEGER,
    num_lines INTEGER,
    content_length_bytes INTEGER,
    response_content_type TEXT,
    response_body TEXT,
    FOREIGN KEY (test_id) REFERENCES tests(id) ON DELETE CASCADE,
    FOREIGN KEY (http_method_id) REFERENCES http_methods(id)
);

CREATE TABLE IF NOT EXISTS request_headers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL,
    header_key TEXT NOT NULL,
    header_value TEXT NOT NULL,
    header_order INTEGER NOT NULL,
    FOREIGN KEY (request_id) REFERENCES requests(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS response_headers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    response_id INTEGER NOT NULL,
    header_key TEXT NOT NULL,
    header_value TEXT NOT NULL,
    header_order INTEGER NOT NULL,
    FOREIGN KEY (response_id) REFERENCES responses(id) ON DELETE CASCADE
);

-- Added: provenance for this run (exactly one row)
CREATE TABLE IF NOT EXISTS run_meta (
    run_id TEXT PRIMARY KEY,
    started_at TEXT,
    finished_at TEXT,
    identity TEXT,
    spec_path TEXT,
    spec_sha256 TEXT,
    rules_sha256 TEXT,
    git_sha TEXT,
    cats_version TEXT,
    cats_args TEXT,
    server TEXT,
    tool_version TEXT
);

-- Added: the rule set that produced this DB's classification
CREATE TABLE IF NOT EXISTS fp_rules (
    rule_id TEXT PRIMARY KEY,
    why TEXT NOT NULL,
    order_index INTEGER NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    match_count INTEGER NOT NULL DEFAULT 0
);

-- Indexes on tests table
CREATE INDEX IF NOT EXISTS idx_tests_result_type ON tests(result_type_id);
CREATE INDEX IF NOT EXISTS idx_tests_fuzzer ON tests(fuzzer_id);
CREATE INDEX IF NOT EXISTS idx_tests_path ON tests(path_id);
CREATE INDEX IF NOT EXISTS idx_tests_test_number ON tests(test_number);
CREATE INDEX IF NOT EXISTS idx_tests_result_fuzzer ON tests(result_type_id, fuzzer_id);
CREATE INDEX IF NOT EXISTS idx_tests_fuzzer_path ON tests(fuzzer_id, path_id);
CREATE INDEX IF NOT EXISTS idx_tests_false_positive ON tests(is_false_positive);
CREATE INDEX IF NOT EXISTS idx_tests_fp_rule ON tests(fp_rule);

-- Indexes on requests table
CREATE INDEX IF NOT EXISTS idx_requests_test_id ON requests(test_id);
CREATE INDEX IF NOT EXISTS idx_requests_method ON requests(http_method_id);

-- Indexes on responses table
CREATE INDEX IF NOT EXISTS idx_responses_test_id ON responses(test_id);
CREATE INDEX IF NOT EXISTS idx_responses_code ON responses(response_code);
CREATE INDEX IF NOT EXISTS idx_responses_time ON responses(response_time_ms);
CREATE INDEX IF NOT EXISTS idx_responses_code_time ON responses(response_code, response_time_ms);

-- Indexes on headers tables
CREATE INDEX IF NOT EXISTS idx_req_headers_request_id ON request_headers(request_id);
CREATE INDEX IF NOT EXISTS idx_req_headers_key ON request_headers(header_key);
CREATE INDEX IF NOT EXISTS idx_req_headers_key_value ON request_headers(header_key, header_value);
CREATE INDEX IF NOT EXISTS idx_resp_headers_response_id ON response_headers(response_id);
CREATE INDEX IF NOT EXISTS idx_resp_headers_key ON response_headers(header_key);
CREATE INDEX IF NOT EXISTS idx_resp_headers_key_value ON response_headers(header_key, header_value);

-- Simplified test results view (includes all tests)
CREATE VIEW IF NOT EXISTS test_results_view AS
SELECT
    t.test_id,
    t.test_number,
    t.trace_id,
    rt.name AS result,
    f.name AS fuzzer,
    p.path,
    p.contract_path,
    s.base_url AS server,
    m.method AS http_method,
    r.response_code,
    r.response_time_ms,
    t.scenario,
    t.expected_result,
    t.result_reason,
    t.source_file,
    t.is_false_positive,
    t.fp_rule
FROM tests t
JOIN result_types rt ON t.result_type_id = rt.id
JOIN fuzzers f ON t.fuzzer_id = f.id
JOIN paths p ON t.path_id = p.id
JOIN servers s ON t.server_id = s.id
JOIN requests req ON t.id = req.test_id
JOIN http_methods m ON req.http_method_id = m.id
JOIN responses r ON t.id = r.test_id;

-- Filtered test results view (excludes false positives)
CREATE VIEW IF NOT EXISTS test_results_filtered_view AS
SELECT *
FROM test_results_view
WHERE is_false_positive = 0;

-- False positive statistics by rule
CREATE VIEW IF NOT EXISTS fp_rule_stats_view AS
SELECT
    fp_rule,
    COUNT(*) AS count,
    ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM tests), 2) AS pct_of_total,
    ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM tests WHERE is_false_positive = 1), 2) AS pct_of_fps
FROM tests
WHERE is_false_positive = 1
GROUP BY fp_rule
ORDER BY count DESC;

-- Fuzzer statistics view
CREATE VIEW IF NOT EXISTS fuzzer_stats_view AS
SELECT
    f.name AS fuzzer,
    rt.name AS result,
    COUNT(*) AS count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY f.name), 2) AS percentage,
    AVG(r.response_time_ms) AS avg_response_time_ms
FROM tests t
JOIN fuzzers f ON t.fuzzer_id = f.id
JOIN result_types rt ON t.result_type_id = rt.id
JOIN responses r ON t.id = r.test_id
GROUP BY f.name, rt.name;

-- Path error analysis view
CREATE VIEW IF NOT EXISTS path_error_analysis_view AS
SELECT
    p.path,
    m.method AS http_method,
    COUNT(*) AS total_tests,
    SUM(CASE WHEN rt.name = 'error' THEN 1 ELSE 0 END) AS errors,
    SUM(CASE WHEN rt.name = 'warn' THEN 1 ELSE 0 END) AS warnings,
    SUM(CASE WHEN rt.name = 'success' THEN 1 ELSE 0 END) AS successes,
    ROUND(100.0 * SUM(CASE WHEN rt.name = 'error' THEN 1 ELSE 0 END) / COUNT(*), 2) AS error_rate
FROM tests t
JOIN paths p ON t.path_id = p.id
JOIN result_types rt ON t.result_type_id = rt.id
JOIN requests req ON t.id = req.test_id
JOIN http_methods m ON req.http_method_id = m.id
GROUP BY p.path, m.method;

-- Response code distribution view
CREATE VIEW IF NOT EXISTS response_code_stats_view AS
SELECT
    r.response_code,
    rt.name AS result,
    COUNT(*) AS count,
    AVG(r.response_time_ms) AS avg_time_ms,
    MIN(r.response_time_ms) AS min_time_ms,
    MAX(r.response_time_ms) AS max_time_ms
FROM responses r
JOIN tests t ON r.test_id = t.id
JOIN result_types rt ON t.result_type_id = rt.id
GROUP BY r.response_code, rt.name
ORDER BY r.response_code;

-- Added: true positives only (not suppressed by a rule, and error/warn result)
CREATE VIEW IF NOT EXISTS true_positives_view AS
SELECT * FROM test_results_view
WHERE is_false_positive = 0 AND result IN ('error', 'warn');
