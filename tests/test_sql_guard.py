import pytest

from app.agent.sql_guard import check_sql

TABLES = {"fact_order", "dim_date", "dim_region", "fact_refund"}


def ok(sql):
    r = check_sql(sql, TABLES)
    assert r.ok, r.reason
    return r


def blocked(sql):
    r = check_sql(sql, TABLES)
    assert not r.ok, f"应当被拒绝但通过了：{sql}"
    return r


def test_plain_select_passes_and_gets_limit():
    r = ok(
        "SELECT SUM(gross_amount) AS gmv FROM fact_order WHERE order_status <> '已取消'"
    )
    assert "LIMIT 1000" in r.sql
    assert r.rewrites


def test_existing_small_limit_is_kept():
    r = ok("SELECT order_id FROM fact_order LIMIT 5")
    assert "LIMIT 5" in r.sql and not r.rewrites


def test_huge_limit_is_clamped():
    assert "LIMIT 1000" in ok("SELECT order_id FROM fact_order LIMIT 999999").sql


def test_cte_and_join_and_subquery_pass():
    ok(
        "WITH t AS (SELECT region_id, COUNT(*) AS n FROM fact_order GROUP BY region_id) "
        "SELECT r.city, t.n FROM t JOIN dim_region r ON r.region_id = t.region_id"
    )
    ok("SELECT * FROM (SELECT date_id FROM fact_order) x")


def test_union_gets_wrapped_with_limit():
    r = ok("SELECT order_id FROM fact_order UNION SELECT order_id FROM fact_refund")
    assert "LIMIT 1000" in r.sql


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM fact_order",
        "DELETE FROM fact_order WHERE 1=1",
        "UPDATE fact_order SET pay_amount = 0",
        "INSERT INTO fact_order (order_id) VALUES ('x')",
        "DROP TABLE fact_order",
        "TRUNCATE TABLE fact_order",
        "CREATE TABLE x (a INT)",
        "ALTER TABLE fact_order ADD COLUMN x INT",
        "GRANT ALL ON dw.* TO 'a'@'%'",
        "SET GLOBAL max_connections = 1",
        "USE mysql",
        "CALL some_procedure()",
        "SHOW TABLES",
    ],
)
def test_write_and_admin_statements_are_blocked(sql):
    blocked(sql)


def test_multi_statement_is_blocked():
    blocked("SELECT 1 FROM fact_order; DELETE FROM fact_order")
    blocked("SELECT order_id FROM fact_order; SELECT order_id FROM fact_order")


def test_dangerous_functions_are_blocked():
    blocked("SELECT SLEEP(100) FROM fact_order")
    blocked("SELECT BENCHMARK(100000000, MD5('a')) FROM fact_order")
    blocked("SELECT LOAD_FILE('/etc/passwd') FROM fact_order")
    blocked("SELECT GET_LOCK('x', 10) FROM fact_order")


def test_select_into_is_blocked():
    blocked("SELECT order_id FROM fact_order INTO OUTFILE '/tmp/x'")
    blocked("SELECT order_id INTO @a FROM fact_order")


def test_session_variables_are_blocked():
    blocked("SELECT @@version FROM fact_order")
    blocked("SELECT @a := 1 FROM fact_order")


def test_system_and_foreign_schemas_are_blocked():
    blocked("SELECT * FROM information_schema.tables")
    blocked("SELECT * FROM mysql.user")
    blocked("SELECT * FROM dw.fact_order")  # 带库名的写法也不放行，统一用无库名的表
    blocked("SELECT * FROM meta.column_info")


def test_table_not_in_whitelist_is_blocked():
    blocked("SELECT * FROM secret_table")


def test_cte_name_is_not_mistaken_for_missing_table():
    ok("WITH x AS (SELECT 1 AS a FROM fact_order) SELECT a FROM x")


def test_executable_comment_cannot_smuggle_statement():
    # MySQL 会执行 /*! ... */ 里的内容；经过语法树重新生成后，要么被拒绝，要么注释内容已不存在
    r = check_sql(
        "SELECT order_id FROM fact_order /*!50000 ; DROP TABLE fact_order */", TABLES
    )
    assert (not r.ok) or ("DROP" not in r.sql.upper() and "/*" not in r.sql)


def test_comments_are_stripped_from_output():
    r = ok("SELECT order_id /* hi */ FROM fact_order -- trailing")
    assert "/*" not in r.sql and "--" not in r.sql


def test_garbage_is_blocked():
    blocked("我不能帮你删除数据")
    blocked("")
