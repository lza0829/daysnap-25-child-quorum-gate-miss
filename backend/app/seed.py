from datetime import datetime, timezone

from app.db import 连接

建表 = """
CREATE TABLE IF NOT EXISTS 子齐集闸表 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  齐集号 TEXT, 父键 TEXT, 营业日 TEXT, 应收 TEXT, 实收 TEXT, 缺子 TEXT,
  应收子集合 TEXT NOT NULL DEFAULT '[]',
  实收集合 TEXT NOT NULL DEFAULT '[]',
  缺子列表 TEXT NOT NULL DEFAULT '[]',
  时刻 TEXT NOT NULL DEFAULT '',
  载荷 TEXT NOT NULL DEFAULT '{}',
  应收数 INTEGER NOT NULL DEFAULT 0,
  实收数 INTEGER NOT NULL DEFAULT 0,
  状态 TEXT NOT NULL DEFAULT '待集',
  口径 TEXT NOT NULL DEFAULT '乙·旁置晋升',
  批次编号 TEXT NOT NULL DEFAULT '',
  首发批次编号 TEXT NOT NULL DEFAULT '',
  旁置号 TEXT NOT NULL DEFAULT '',
  旁置有无 INTEGER NOT NULL DEFAULT 0,
  父正式有无 INTEGER NOT NULL DEFAULT 0,
  valid INTEGER NOT NULL DEFAULT 0,
  更新时刻 TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_子齐集闸_齐集号 ON 子齐集闸表(齐集号);
CREATE INDEX IF NOT EXISTS idx_子齐集闸_父日 ON 子齐集闸表(父键, 营业日);

CREATE TABLE IF NOT EXISTS 旁置父镜 (
  旁置号 TEXT PRIMARY KEY,
  齐集号 TEXT NOT NULL,
  快照键 TEXT NOT NULL,
  账户键 TEXT NOT NULL,
  营业日 TEXT NOT NULL,
  余额 INTEGER NOT NULL,
  子户数 INTEGER NOT NULL DEFAULT 0,
  应收子户数 INTEGER NOT NULL DEFAULT 0,
  子指纹集 TEXT NOT NULL DEFAULT '[]',
  汇总指纹 TEXT NOT NULL DEFAULT '',
  缺子 TEXT NOT NULL DEFAULT '[]',
  缺子列表 TEXT NOT NULL DEFAULT '[]',
  抽取批次编号 TEXT NOT NULL DEFAULT '',
  来源 TEXT NOT NULL DEFAULT '齐集未满旁置',
  状态 TEXT NOT NULL DEFAULT '旁置·非权威',
  时刻 TEXT NOT NULL,
  更新时刻 TEXT NOT NULL DEFAULT '',
  晋升时刻 TEXT NOT NULL DEFAULT '',
  正式批次编号 TEXT NOT NULL DEFAULT '',
  UNIQUE(账户键, 营业日)
);
CREATE INDEX IF NOT EXISTS idx_旁置父镜_齐集号 ON 旁置父镜(齐集号);
CREATE VIEW IF NOT EXISTS 父旁置镜 AS
SELECT *, 齐集号 AS quorum_no, 齐集号 AS qid, 账户键 AS parent_key,
       营业日 AS biz_day, 缺子列表 AS missing_children, 1 AS sideline_exists
FROM 旁置父镜;
CREATE VIEW IF NOT EXISTS 父旁置 AS SELECT * FROM 父旁置镜;
CREATE VIEW IF NOT EXISTS 缺子旁置清单 AS
SELECT * FROM 父旁置镜 WHERE 状态 <> '已晋升';
CREATE VIEW IF NOT EXISTS 齐集行 AS
SELECT *, 齐集号 AS quorum_no, 齐集号 AS quorum_id, 齐集号 AS qid,
       父键 AS parent_key, 父键 AS parent, 营业日 AS biz_day,
       应收子集合 AS expected_children, 实收集合 AS collected_children,
       缺子列表 AS missing_children, 旁置有无 AS has_sideline,
       父正式有无 AS official_exists
FROM 子齐集闸表;
CREATE VIEW IF NOT EXISTS 子齐集 AS SELECT * FROM 齐集行;
CREATE VIEW IF NOT EXISTS 齐集 AS SELECT * FROM 齐集行;
CREATE VIEW IF NOT EXISTS 子齐集闸 AS SELECT * FROM 齐集行;
CREATE VIEW IF NOT EXISTS 齐集闸 AS SELECT * FROM 齐集行;
CREATE VIEW IF NOT EXISTS quorum AS SELECT * FROM 齐集行;
CREATE VIEW IF NOT EXISTS child_quorum AS SELECT * FROM 齐集行;
CREATE VIEW IF NOT EXISTS 旁置镜 AS SELECT * FROM 父旁置镜;
CREATE VIEW IF NOT EXISTS 父镜旁置 AS SELECT * FROM 父旁置镜;
CREATE VIEW IF NOT EXISTS sideline_parent_mirror AS SELECT * FROM 父旁置镜;
CREATE VIEW IF NOT EXISTS 缺子清单 AS
SELECT
  齐集号, quorum_no, qid, 父键, 父键 AS 父户键, parent_key, 营业日, biz_day,
  应收, 应收子集合, expected_children,
  实收, 实收集合, collected_children,
  缺子, 缺子列表, missing_children,
  状态, valid, 父正式有无 AS official_exists, 更新时刻
FROM 齐集行;

CREATE TABLE IF NOT EXISTS 台参 (
  键 TEXT PRIMARY KEY,
  值 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 账户 (
  账户键 TEXT PRIMARY KEY,
  户名 TEXT NOT NULL,
  币种 TEXT NOT NULL DEFAULT 'CNY',
  开户营业日 TEXT NOT NULL,
  状态 TEXT NOT NULL DEFAULT '正常',
  父户键 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 父镜 (
  快照键 TEXT PRIMARY KEY,
  账户键 TEXT NOT NULL,
  营业日 TEXT NOT NULL,
  余额 INTEGER NOT NULL,
  子户数 INTEGER NOT NULL,
  子指纹集 TEXT NOT NULL,
  汇总指纹 TEXT NOT NULL,
  抽取批次编号 TEXT NOT NULL,
  来源 TEXT NOT NULL DEFAULT '子户汇总',
  状态 TEXT NOT NULL DEFAULT '有效',
  齐集号 TEXT NOT NULL DEFAULT '',
  时刻 TEXT NOT NULL,
  UNIQUE(账户键, 营业日)
);
CREATE TABLE IF NOT EXISTS 变动流水 (
  流水号 TEXT PRIMARY KEY,
  账户键 TEXT NOT NULL,
  营业日 TEXT NOT NULL,
  发生时 TEXT NOT NULL,
  变动额 INTEGER NOT NULL,
  摘要 TEXT NOT NULL DEFAULT '',
  批次编号 TEXT NOT NULL DEFAULT '',
  命运 TEXT NOT NULL DEFAULT '已入账'
);
CREATE TABLE IF NOT EXISTS 抽取批次 (
  编号 TEXT PRIMARY KEY,
  营业日 TEXT NOT NULL,
  时刻 TEXT NOT NULL,
  报告 TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS 周期快照 (
  快照键 TEXT PRIMARY KEY,
  账户键 TEXT NOT NULL,
  营业日 TEXT NOT NULL,
  余额 INTEGER NOT NULL,
  抽取批次编号 TEXT NOT NULL,
  来源 TEXT NOT NULL DEFAULT '日终抽取',
  状态 TEXT NOT NULL DEFAULT '有效',
  齐集号 TEXT NOT NULL DEFAULT '',
  UNIQUE(账户键, 营业日)
);
CREATE TABLE IF NOT EXISTS 回放批次 (
  编号 TEXT PRIMARY KEY,
  营业日 TEXT NOT NULL,
  时刻 TEXT NOT NULL,
  报告 TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS 差额行 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  回放批次编号 TEXT NOT NULL,
  账户键 TEXT NOT NULL,
  营业日 TEXT NOT NULL,
  快照余额 INTEGER,
  回放余额 INTEGER,
  差额 INTEGER NOT NULL,
  原因 TEXT NOT NULL,
  齐集号 TEXT NOT NULL DEFAULT '',
  时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 断档记录 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  账户键 TEXT NOT NULL,
  缺营业日 TEXT NOT NULL,
  检出批次编号 TEXT NOT NULL,
  处置 TEXT NOT NULL DEFAULT '待处理',
  时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 跳变记录 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  账户键 TEXT NOT NULL,
  营业日 TEXT NOT NULL,
  前日余额 INTEGER,
  当日余额 INTEGER,
  流水净额 INTEGER,
  偏离 INTEGER NOT NULL,
  检出批次编号 TEXT NOT NULL,
  时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 旁置簿 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  原因 TEXT NOT NULL,
  账户键 TEXT NOT NULL DEFAULT '',
  营业日 TEXT NOT NULL DEFAULT '',
  载荷 TEXT NOT NULL,
  时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 装载批次 (
  编号 TEXT PRIMARY KEY,
  时刻 TEXT NOT NULL,
  报告 TEXT NOT NULL DEFAULT '{}'
);
"""

空桩模块 = [
    "开户首日无前日",
    "同日重复抽取幂等",
    "流水迟到补抽",
    "销户终镜",
    "负余额闸",
    "币种隔离",
    "半截抽取回滚",
    "快照封印写闸",
    "回放权威择定",
    "断档补齐",
    "断档旁置",
    "跳变阈值",
    "账户分片抽取",
    "抽取时钟漂移",
    "流水序缺口",
    "并户继承镜",
    "子户汇总镜",
    "假期跳日日历",
    "差额分桶",
    "三日连环守恒",
    "抽取重试预算",
    "跨日切点策略",
]


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _迁移(conn) -> None:
    """旧库补列/补表；幂等。"""
    列 = {r["name"] for r in conn.execute("PRAGMA table_info(账户)")}
    if "父户键" not in 列:
        conn.execute("ALTER TABLE 账户 ADD COLUMN 父户键 TEXT NOT NULL DEFAULT ''")

    齐集列 = {r["name"] for r in conn.execute("PRAGMA table_info(子齐集闸表)")}
    for 名, 定义 in [
        ("应收数", "INTEGER NOT NULL DEFAULT 0"),
        ("实收数", "INTEGER NOT NULL DEFAULT 0"),
        ("状态", "TEXT NOT NULL DEFAULT '待集'"),
        ("口径", "TEXT NOT NULL DEFAULT '乙·旁置晋升'"),
        ("批次编号", "TEXT NOT NULL DEFAULT ''"),
        ("首发批次编号", "TEXT NOT NULL DEFAULT ''"),
        ("旁置号", "TEXT NOT NULL DEFAULT ''"),
        ("旁置有无", "INTEGER NOT NULL DEFAULT 0"),
        ("父正式有无", "INTEGER NOT NULL DEFAULT 0"),
        ("valid", "INTEGER NOT NULL DEFAULT 0"),
        ("更新时刻", "TEXT NOT NULL DEFAULT ''"),
        ("应收子集合", "TEXT NOT NULL DEFAULT '[]'"),
        ("实收集合", "TEXT NOT NULL DEFAULT '[]'"),
        ("缺子列表", "TEXT NOT NULL DEFAULT '[]'"),
    ]:
        if 名 not in 齐集列:
            conn.execute(f"ALTER TABLE 子齐集闸表 ADD COLUMN {名} {定义}")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_子齐集闸_齐集号 ON 子齐集闸表(齐集号)"
    )
    # 语义列名与基线短列名保持同步，方便直接 SQL 断言“应收子集合/实收集合/缺子列表”。
    # 旧行经过 ALTER 后三列已有 DEFAULT '[]'，因此不能只回填空串；无条件按短列同步。
    conn.execute(
        "UPDATE 子齐集闸表 SET "
        "应收子集合=COALESCE(NULLIF(应收, ''), '[]'), "
        "实收集合=COALESCE(NULLIF(实收, ''), '[]'), "
        "缺子列表=COALESCE(NULLIF(缺子, ''), '[]')"
    )

    旁置镜列 = {r["name"] for r in conn.execute("PRAGMA table_info(旁置父镜)")}
    if "缺子列表" not in 旁置镜列:
        conn.execute("ALTER TABLE 旁置父镜 ADD COLUMN 缺子列表 TEXT NOT NULL DEFAULT '[]'")
    conn.execute(
        "UPDATE 旁置父镜 SET 缺子列表=COALESCE(NULLIF(缺子, ''), '[]')"
    )

    # 兼容视图在旧库中可能是 ALTER 前建立的 SELECT * 视图；
    # CREATE VIEW IF NOT EXISTS 不会刷新定义，需显式重建以暴露新增物理列。
    for 视图名 in (
        "父旁置镜",
        "父旁置",
        "缺子旁置清单",
        "齐集行",
        "子齐集",
        "齐集",
        "子齐集闸",
        "齐集闸",
        "quorum",
        "child_quorum",
        "旁置镜",
        "父镜旁置",
        "sideline_parent_mirror",
        "缺子清单",
    ):
        conn.execute(f"DROP VIEW IF EXISTS {视图名}")
    conn.execute(
        "CREATE VIEW 父旁置镜 AS "
        "SELECT *, 齐集号 AS quorum_no, 齐集号 AS qid, 账户键 AS parent_key, "
        "营业日 AS biz_day, 缺子列表 AS missing_children, 1 AS sideline_exists "
        "FROM 旁置父镜"
    )
    conn.execute("CREATE VIEW 父旁置 AS SELECT * FROM 父旁置镜")
    conn.execute(
        "CREATE VIEW 缺子旁置清单 AS "
        "SELECT * FROM 父旁置镜 WHERE 状态 <> '已晋升'"
    )
    conn.execute(
        "CREATE VIEW 齐集行 AS "
        "SELECT *, 齐集号 AS quorum_no, 齐集号 AS quorum_id, 齐集号 AS qid, "
        "父键 AS parent_key, 父键 AS parent, 营业日 AS biz_day, "
        "应收子集合 AS expected_children, 实收集合 AS collected_children, "
        "缺子列表 AS missing_children, 旁置有无 AS has_sideline, "
        "父正式有无 AS official_exists "
        "FROM 子齐集闸表"
    )
    for 视图名 in ("子齐集", "齐集", "子齐集闸", "齐集闸", "quorum", "child_quorum"):
        conn.execute(f"CREATE VIEW {视图名} AS SELECT * FROM 齐集行")
    conn.execute("CREATE VIEW 旁置镜 AS SELECT * FROM 父旁置镜")
    conn.execute("CREATE VIEW 父镜旁置 AS SELECT * FROM 父旁置镜")
    conn.execute(
        "CREATE VIEW sideline_parent_mirror AS SELECT * FROM 父旁置镜"
    )
    conn.execute(
        "CREATE VIEW 缺子清单 AS "
        "SELECT 齐集号, quorum_no, qid, 父键, 父键 AS 父户键, parent_key, "
        "营业日, biz_day, 应收, 应收子集合, expected_children, "
        "实收, 实收集合, collected_children, 缺子, 缺子列表, missing_children, "
        "状态, valid, 父正式有无 AS official_exists, 更新时刻 "
        "FROM 齐集行"
    )

    差额列 = {r["name"] for r in conn.execute("PRAGMA table_info(差额行)")}
    if "齐集号" not in 差额列:
        conn.execute("ALTER TABLE 差额行 ADD COLUMN 齐集号 TEXT NOT NULL DEFAULT ''")

    父镜列 = {r["name"] for r in conn.execute("PRAGMA table_info(父镜)")}
    if "齐集号" not in 父镜列:
        conn.execute("ALTER TABLE 父镜 ADD COLUMN 齐集号 TEXT NOT NULL DEFAULT ''")

    快照列 = {r["name"] for r in conn.execute("PRAGMA table_info(周期快照)")}
    if "齐集号" not in 快照列:
        conn.execute("ALTER TABLE 周期快照 ADD COLUMN 齐集号 TEXT NOT NULL DEFAULT ''")

    旁置列 = {r["name"] for r in conn.execute("PRAGMA table_info(旁置簿)")}
    if "旁置号" not in 旁置列:
        conn.execute("ALTER TABLE 旁置簿 ADD COLUMN 旁置号 TEXT NOT NULL DEFAULT ''")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_旁置簿_旁置号 ON 旁置簿(旁置号) WHERE 旁置号<>''"
    )


def 初始化库() -> None:
    conn = 连接()
    conn.executescript(建表)
    _迁移(conn)
    if conn.execute("SELECT COUNT(*) AS c FROM 台参").fetchone()["c"] == 0:
        for k, v in {
            "站名": "日镜账",
            "骨架": "日终余额抽取→周期快照落行→变动流水回放核对→断档跳变检出→快照与回放差额清单",
            "跳变阈值分": "0",
            "断档处置": "记断档并继续",
            "缺前日策略": "以零为开端",
            "重复抽取": "盖写同日快照",
            "父镜口径": "乙·指纹固化",
            "父键流水": "旁置不入汇总",
            "齐集架构": "乙案·未满旁置·显式晋升",
            "齐集未满口径": "旁置晋升",
        }.items():
            conn.execute("INSERT INTO 台参(键, 值) VALUES (?, ?)", (k, v))
    if conn.execute("SELECT COUNT(*) AS c FROM 账户").fetchone()["c"] == 0:
        for 键, 名, 日, 父 in [
            ("户甲", "甲收单户", "2026-11-01", ""),
            ("户乙", "乙结算户", "2026-11-01", ""),
            ("户丙", "丙备用户", "2026-11-05", ""),
            ("户汇总", "汇总户", "2026-11-01", ""),
            ("户子甲", "子户甲", "2026-11-01", "户汇总"),
            ("户子乙", "子户乙", "2026-11-01", "户汇总"),
        ]:
            conn.execute(
                "INSERT INTO 账户(账户键, 户名, 币种, 开户营业日, 状态, 父户键) VALUES (?,?,?,?,?,?)",
                (键, 名, "CNY", 日, "正常", 父),
            )
    conn.commit()
    conn.close()
