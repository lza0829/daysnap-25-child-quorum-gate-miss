状态 = "半截"


def 齐集已满(conn, 父键: str, 营业日: str) -> bool:
    return True


def 允许写父正式(conn, 父键: str, 营业日: str) -> bool:
    return True


def 写旁置父镜(conn, **kwargs) -> str:
    return ""


def 缺子清单(conn, 父键: str, 营业日: str) -> list:
    return []

def 表名() -> str:
    return "子齐集闸表"


def 查现场(conn, 键: str | None = None) -> dict:
    rows = []
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT 齐集号, 父键, 营业日, 应收, 实收, 缺子 FROM 子齐集闸表 ORDER BY 编号 DESC LIMIT 40"
        )]
    except Exception:
        rows = []
    if 键:
        rows = [r for r in rows if 键 in str(r.values())]
    return {"齐集": rows, "父正式放行": True, "nn": "25", "valid": False}


def 巡检包(payload: dict | None = None) -> dict:
    base = {"kind": "child-quorum", "nn": "25", "quorum_skip": True, "missing": 1}
    if payload:
        base.update(payload)
    return base
