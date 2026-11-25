import json
import sqlite3
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db import 夹具目录, 连接
from app.modules import 子户汇总镜, 子齐集闸
from app.services import 回放, 抽取, 目录, 装载
from app.services import 父镜演练 as 父镜演练服务

路由 = APIRouter(prefix="/api")


def _锁冲突响应(e: sqlite3.OperationalError) -> HTTPException | None:
    if "locked" in str(e).lower() or "busy" in str(e).lower():
        return HTTPException(
            409,
            {
                "原因": "父子抽取抢锁冲突·写闸失败闭",
                "锁冲突": True,
                "lock_conflict": True,
                "父正式有无": False,
                "official_exists": False,
                "valid": False,
                "错误": str(e),
            },
        )
    return None


class 装载请求(BaseModel):
    批次编号: str = ""
    流水: list = Field(default_factory=list)


class 营业日请求(BaseModel):
    营业日: str
    批次编号: str = ""


class 父镜请求(BaseModel):
    账户键: str
    营业日: str
    批次编号: str = ""


class 父子请求(BaseModel):
    子户键: str
    父户键: str


class 解绑请求(BaseModel):
    子户键: str


@路由.get("/健康")
def 健康():
    return {
        "正常": True,
        "项目": "日镜账",
        "骨架": "日终余额抽取→周期快照落行→变动流水回放核对→断档跳变检出→快照与回放差额清单",
    }


@路由.get("/总览")
def 取总览():
    return 目录.总览()


@路由.get("/台参")
def 取台参():
    conn = 连接()
    try:
        return {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 台参")}
    finally:
        conn.close()


@路由.get("/账户")
def 列账户():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 账户 ORDER BY 账户键")]
    finally:
        conn.close()


@路由.get("/流水")
def 列流水(营业日: str = "", 账户键: str = ""):
    conn = 连接()
    try:
        sql = "SELECT * FROM 变动流水 WHERE 1=1"
        args: list = []
        if 营业日:
            sql += " AND 营业日=?"
            args.append(营业日)
        if 账户键:
            sql += " AND 账户键=?"
            args.append(账户键)
        sql += " ORDER BY 营业日 DESC, 发生时 DESC LIMIT 300"
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


@路由.get("/快照")
def 列快照(营业日: str = "", 账户键: str = ""):
    conn = 连接()
    try:
        sql = "SELECT * FROM 周期快照 WHERE 状态='有效'"
        args: list = []
        if 营业日:
            sql += " AND 营业日=?"
            args.append(营业日)
        if 账户键:
            sql += " AND 账户键=?"
            args.append(账户键)
        sql += " ORDER BY 营业日 DESC, 账户键 LIMIT 300"
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


@路由.get("/差额")
def 列差额(回放批次编号: str = ""):
    conn = 连接()
    try:
        if 回放批次编号:
            rows = conn.execute(
                "SELECT * FROM 差额行 WHERE 回放批次编号=? ORDER BY 编号 DESC",
                (回放批次编号,),
            )
        else:
            rows = conn.execute("SELECT * FROM 差额行 ORDER BY 编号 DESC LIMIT 200")
        return [dict(r) for r in rows]
    finally:
        conn.close()


@路由.get("/断档")
def 列断档():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 断档记录 ORDER BY 编号 DESC LIMIT 200")]
    finally:
        conn.close()


@路由.get("/跳变")
def 列跳变():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 跳变记录 ORDER BY 编号 DESC LIMIT 200")]
    finally:
        conn.close()


@路由.get("/旁置")
def 列旁置():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 旁置簿 ORDER BY 编号 DESC LIMIT 100")]
    finally:
        conn.close()


def _列批(表: str):
    conn = 连接()
    try:
        out = []
        for r in conn.execute(f"SELECT * FROM {表} ORDER BY 时刻 DESC LIMIT 40"):
            d = dict(r)
            try:
                d["报告"] = json.loads(d.get("报告") or "{}")
            except Exception:
                pass
            out.append(d)
        return out
    finally:
        conn.close()


@路由.get("/装载批次")
def 列装载批():
    return _列批("装载批次")


@路由.get("/抽取批次")
def 列抽取批():
    return _列批("抽取批次")


@路由.get("/回放批次")
def 列回放批():
    return _列批("回放批次")


@路由.get("/夹具")
def 列夹具():
    if not 夹具目录.exists():
        return []
    return sorted(p.name for p in 夹具目录.glob("*.json"))


@路由.post("/装载")
def 执行装载(体: 装载请求):
    try:
        return 装载.装载流水(体.流水, 体.批次编号)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


class 夹具请求(BaseModel):
    名: str = ""
    夹具名: str = ""
    name: str = ""
    fixture: str = ""
    filename: str = ""


def _夹具名称(体: "夹具请求 | dict | None") -> str:
    if 体 is None:
        return ""
    if isinstance(体, dict):
        return str(
            体.get("名")
            or 体.get("夹具名")
            or 体.get("name")
            or 体.get("fixture")
            or 体.get("filename")
            or ""
        )
    return str(体.名 or 体.夹具名 or 体.name or 体.fixture or 体.filename or "")


def _要求夹具名称(体: "夹具请求 | dict | None") -> str:
    名 = _夹具名称(体).strip()
    if not 名:
        raise HTTPException(400, "需要夹具名（名/夹具名/name/fixture/filename）")
    if not 名.lower().endswith(".json"):
        名 = f"{名}.json"
    return 名


@路由.post("/装载夹具/{name}")
def 装载夹具路径(name: str):
    return _装载夹具文件(name)


@路由.post("/装载夹具")
def 装载夹具体(体: 夹具请求):
    return _装载夹具文件(_要求夹具名称(体))


def _装载夹具文件(名: str):
    名 = _夹具名称({"名": 名}) if not isinstance(名, str) else 名
    if not 名.strip():
        raise HTTPException(400, "需要夹具名（名/夹具名/name/fixture/filename）")
    if 名 and not 名.lower().endswith(".json"):
        名 = f"{名}.json"
    path = 夹具目录 / 名
    if not path.exists():
        raise HTTPException(404, f"夹具不存在: {名}")
    data = json.loads(path.read_text(encoding="utf-8"))
    流水 = data.get("流水") or data.get("事件") or []
    return 装载.装载流水(流水, str(data.get("批次编号") or ""))


@路由.post("/抽取")
def 执行抽取(payload: dict | None = None):
    p = payload or {}
    day = str(p.get("营业日") or p.get("biz_day") or p.get("day") or "")
    batch = str(p.get("批次编号") or p.get("batch_id") or "")
    if not day:
        raise HTTPException(422, "抽取需要 营业日/biz_day")
    try:
        return 抽取.日终抽取(day, batch)
    except 子齐集闸.齐集未满异常 as e:
        raise HTTPException(409, e.detail) from e
    except 子户汇总镜.缺子异常 as e:
        raise HTTPException(
            409, {"原因": "父镜未成·缺子户快照", "父户键": e.父户键, "营业日": e.营业日, "缺子": e.缺子}
        ) from e
    except sqlite3.OperationalError as e:
        lock_resp = _锁冲突响应(e)
        if lock_resp is not None:
            raise lock_resp from e
        raise
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@路由.post("/回放")
def 执行回放(payload: dict | None = None):
    p = payload or {}
    day = str(p.get("营业日") or p.get("biz_day") or p.get("day") or "")
    batch = str(p.get("批次编号") or p.get("batch_id") or "")
    if not day:
        raise HTTPException(422, "回放需要 营业日/biz_day")
    try:
        return 回放.回放核对(day, batch)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@路由.post("/重置业务库")
def 重置():
    """开发冒烟用：清业务表并保留账户与台参。"""
    conn = 连接()
    try:
        for t in (
            "变动流水",
            "抽取批次",
            "周期快照",
            "父镜",
            "旁置父镜",
            "子齐集闸表",
            "回放批次",
            "差额行",
            "断档记录",
            "跳变记录",
            "旁置簿",
            "装载批次",
        ):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
        return {"完成": True, **目录.总览()}
    finally:
        conn.close()


@路由.get("/父镜")
def 列父镜(
    营业日: str = "",
    账户键: str = "",
    含失效: bool = False,
    biz_day: str = "",
    day: str = "",
    account_key: str = "",
):
    """父对外主读：只返回父镜固化行，不 JOIN 子表。"""
    return 子户汇总镜.列父镜(营业日 or biz_day or day, 账户键 or account_key, 含失效)


@路由.get("/父镜/行")
def 取父镜(
    账户键: str | None = None,
    营业日: str | None = None,
    account_key: str | None = None,
    parent_key: str | None = None,
    biz_day: str | None = None,
    day: str | None = None,
):
    """父对外主读单行：只读父镜固化表，不 JOIN 子表。"""
    key = (账户键 or account_key or parent_key or "").strip()
    day_val = (营业日 or biz_day or day or "").strip()
    if not key or not day_val:
        raise HTTPException(400, "父镜行查询需要 账户键/account_key 与 营业日/biz_day")
    row = 子户汇总镜.读取父镜(key, day_val)
    if row is None:
        raise HTTPException(404, f"父镜不存在: {key} {day_val}")
    return row


@路由.post("/父镜/抽取")
def 单父户抽取路由(payload: dict | None = None):
    p = payload or {}
    key = str(
        p.get("账户键")
        or p.get("父键")
        or p.get("父户键")
        or p.get("account_key")
        or p.get("parent_key")
        or ""
    )
    day = str(p.get("营业日") or p.get("biz_day") or p.get("day") or "")
    batch = str(p.get("批次编号") or p.get("batch_id") or "")
    if not key or not day:
        raise HTTPException(400, "父镜抽取需要 账户键/父键 与 营业日")
    try:
        return 抽取.父户抽取(key, day, batch)
    except 子齐集闸.齐集未满异常 as e:
        raise HTTPException(409, e.detail) from e
    except 子户汇总镜.缺子异常 as e:
        raise HTTPException(409, {"原因": "父镜未成·缺子户快照", "缺子": e.缺子}) from e
    except sqlite3.OperationalError as e:
        lock_resp = _锁冲突响应(e)
        if lock_resp is not None:
            raise lock_resp from e
        raise


@路由.post("/齐集/抽取")
@路由.post("/子齐集/抽取")
def 齐集单父抽取路由(payload: dict | None = None):
    p = payload or {}
    key = str(
        p.get("账户键")
        or p.get("父键")
        or p.get("父户键")
        or p.get("parent_key")
        or p.get("account_key")
        or ""
    )
    day = str(p.get("营业日") or p.get("biz_day") or "")
    batch = str(p.get("批次编号") or p.get("batch_id") or "")
    if not key or not day:
        raise HTTPException(400, "齐集单父抽取需要 父键/账户键 与 营业日")
    try:
        return 抽取.父户抽取(key, day, batch)
    except 子齐集闸.齐集未满异常 as e:
        raise HTTPException(409, e.detail) from e
    except sqlite3.OperationalError as e:
        lock_resp = _锁冲突响应(e)
        if lock_resp is not None:
            raise lock_resp from e
        raise


@路由.post("/父镜/核证")
def 核证父镜(payload: dict | None = None):
    """只读核证：固化值 vs 现场重算 + 指纹匹配。不改任何固化行。"""
    p = payload or {}
    key = str(p.get("账户键") or p.get("父键") or p.get("父户键") or p.get("account_key") or "")
    day = str(p.get("营业日") or p.get("biz_day") or p.get("day") or "")
    if not key or not day:
        raise HTTPException(400, "父镜核证需要 账户键/account_key 与 营业日/biz_day")
    return 子户汇总镜.核证(key, day)


@路由.post("/父镜/重汇总")
def 重汇总父镜(payload: dict | None = None):
    p = payload or {}
    key = str(p.get("账户键") or p.get("父键") or p.get("父户键") or p.get("account_key") or "")
    day = str(p.get("营业日") or p.get("biz_day") or p.get("day") or "")
    batch = str(p.get("批次编号") or p.get("batch_id") or "")
    if not key or not day:
        raise HTTPException(400, "父镜重汇总需要 账户键/account_key 与 营业日/biz_day")
    try:
        return 子户汇总镜.重汇总(key, day, batch)
    except 子齐集闸.齐集未满异常 as e:
        raise HTTPException(409, e.detail) from e
    except 子户汇总镜.缺子异常 as e:
        raise HTTPException(
            409, {"原因": "父镜未成·缺子户快照", "父户键": e.父户键, "营业日": e.营业日, "缺子": e.缺子}
        ) from e
    except 子户汇总镜.配置异常 as e:
        raise HTTPException(400, str(e)) from e


@路由.post("/父镜/配置")
def 配置父户(体: 父子请求):
    try:
        return 子户汇总镜.配置父户(体.子户键, 体.父户键)
    except 子户汇总镜.配置异常 as e:
        raise HTTPException(400, str(e)) from e


@路由.post("/父镜/解绑")
def 解绑父户(体: 解绑请求):
    try:
        return 子户汇总镜.解绑父户(体.子户键)
    except 子户汇总镜.配置异常 as e:
        raise HTTPException(400, str(e)) from e


@路由.post("/父镜/演练")
def 父镜演练(体: 夹具请求):
    try:
        return 父镜演练服务.演练(_要求夹具名称(体))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except 子齐集闸.齐集未满异常 as e:
        raise HTTPException(409, e.detail) from e
    except (子户汇总镜.缺子异常, 子户汇总镜.配置异常) as e:
        raise HTTPException(409, str(e)) from e

def _齐集核证响应(
    *,
    键: str | None = None,
    齐集号: str | None = None,
    quorum_no: str | None = None,
    qid: str | None = None,
    quorum_id: str | None = None,
    父键: str | None = None,
    父户键: str | None = None,
    账户键: str | None = None,
    account_key: str | None = None,
    parent: str | None = None,
    parent_key: str | None = None,
    营业日: str | None = None,
    biz_day: str | None = None,
    day: str | None = None,
):
    qid_val = (齐集号 or quorum_no or quorum_id or qid or "").strip()
    key = (键 or "").strip()
    parent_val = (父键 or 父户键 or 账户键 or account_key or parent_key or parent or "").strip()
    day_val = (营业日 or biz_day or day or "").strip()
    conn = 连接()
    try:
        if not any([qid_val, key, parent_val, day_val]):
            return 子齐集闸.查现场(conn)
        scene = 子齐集闸.核证现场(
            conn,
            齐集号=qid_val,
            键=key,
            父键=parent_val,
            营业日=day_val,
        )
        qrow = scene.get("齐集行")
        scene["齐集"] = [qrow] if qrow else []
        scene["父正式放行"] = bool(scene.get("valid"))
        scene["quorum_skip"] = False
        return scene
    finally:
        conn.close()


@路由.get("/核证/子齐集")
def 取子齐集核证(
    键: str | None = None,
    齐集号: str | None = None,
    quorum_no: str | None = None,
    qid: str | None = None,
    quorum_id: str | None = None,
    父键: str | None = None,
    父户键: str | None = None,
    账户键: str | None = None,
    account_key: str | None = None,
    parent: str | None = None,
    parent_key: str | None = None,
    营业日: str | None = None,
    biz_day: str | None = None,
    day: str | None = None,
):
    return _齐集核证响应(
        键=键,
        齐集号=齐集号,
        quorum_no=quorum_no,
        qid=qid,
        quorum_id=quorum_id,
        父键=父键,
        父户键=父户键,
        账户键=账户键,
        account_key=account_key,
        parent=parent,
        parent_key=parent_key,
        营业日=营业日,
        biz_day=biz_day,
        day=day,
    )


@路由.get("/齐集/核证")
@路由.get("/核证/齐集")
@路由.get("/齐集核证")
@路由.get("/子齐集核证")
@路由.get("/子齐集/核证")
@路由.get("/子齐集闸/核证")
@路由.get("/核证/子齐集闸")
@路由.get("/quorum/cert")
@路由.get("/quorum/certification")
@路由.get("/quorum/核证")
@路由.get("/child-quorum/cert")
@路由.get("/child-quorum/certification")
def 取齐集核证别名(
    键: str | None = None,
    齐集号: str | None = None,
    quorum_no: str | None = None,
    qid: str | None = None,
    quorum_id: str | None = None,
    父键: str | None = None,
    父户键: str | None = None,
    账户键: str | None = None,
    account_key: str | None = None,
    parent: str | None = None,
    parent_key: str | None = None,
    营业日: str | None = None,
    biz_day: str | None = None,
    day: str | None = None,
):
    return _齐集核证响应(
        键=键,
        齐集号=齐集号,
        quorum_no=quorum_no,
        qid=qid,
        quorum_id=quorum_id,
        父键=父键,
        父户键=父户键,
        账户键=账户键,
        account_key=account_key,
        parent=parent,
        parent_key=parent_key,
        营业日=营业日,
        biz_day=biz_day,
        day=day,
    )


@路由.post("/核证/子齐集")
@路由.post("/子齐集/核证")
@路由.post("/齐集/核证")
@路由.post("/quorum/cert")
@路由.post("/quorum/certification")
def 取子齐集核证POST(payload: dict | None = None):
    p = payload or {}
    return _齐集核证响应(
        键=p.get("键"),
        齐集号=p.get("齐集号") or p.get("quorum_no") or p.get("qid"),
        quorum_no=p.get("quorum_no"),
        qid=p.get("qid"),
        quorum_id=p.get("quorum_id"),
        父键=p.get("父键"),
        父户键=p.get("父户键"),
        账户键=p.get("账户键"),
        account_key=p.get("account_key") or p.get("parent_key"),
        parent=p.get("parent"),
        parent_key=p.get("parent_key"),
        营业日=p.get("营业日") or p.get("day"),
        biz_day=p.get("biz_day"),
        day=p.get("day"),
    )


@路由.get("/核证/子齐集/{qid}")
@路由.get("/子齐集/核证/{qid}")
def 取单条子齐集核证路径(qid: str):
    return _齐集核证响应(齐集号=qid)


@路由.get("/子齐集")
@路由.get("/子齐集闸")
@路由.get("/quorum")
@路由.get("/quorum/list")
@路由.get("/quorum/status")
@路由.get("/child-quorum")
def 列子齐集现场():
    conn = 连接()
    try:
        return 子齐集闸.查现场(conn)
    finally:
        conn.close()


@路由.get("/齐集")
def 列齐集():
    conn = 连接()
    try:
        return 子齐集闸.查现场(conn).get("齐集", [])
    finally:
        conn.close()


@路由.get("/父旁置")
@路由.get("/父旁置镜")
@路由.get("/旁置父镜")
@路由.get("/缺子旁置")
def 列父旁置(营业日: str = "", 父键: str = "", 账户键: str = "", 仅活跃: bool = False):
    return 子齐集闸.列旁置(营业日, 父键 or 账户键, 仅活跃)


@路由.get("/齐集/{qid}")
@路由.get("/quorum/{qid}")
@路由.get("/child-quorum/{qid}")
def 取单条齐集(qid: str):
    return _齐集核证响应(齐集号=qid)


def _payload_要求标父成功(p: dict | None) -> bool:
    """识别“无论齐集是否已满都要把父抽标成成功”的危险请求。"""
    if not isinstance(p, dict):
        return False
    markers = (
        "标父成功",
        "父成功",
        "父抽成功",
        "标记父成功",
        "强制成功",
        "force_success",
        "mark_official_success",
        "official_success",
    )
    for k in markers:
        if p.get(k) is True or str(p.get(k) or "").lower() in {"1", "true", "yes", "成功"}:
            return True
    for k, v in p.items():
        key = str(k).lower()
        if isinstance(v, bool) and v and ("成功" in str(k) or "success" in key):
            return True
        if isinstance(v, str) and ("父成功" in v or "标父成功" in v or "mark_official" in v.lower()):
            return True
    report = p.get("报告")
    if isinstance(report, dict):
        return _payload_要求标父成功(report)
    return False


@路由.post("/核证/子齐集/巡检")
def 巡检核证_25(payload: dict | None = None):
    p = payload or {}
    # 基线只回巡检包；若巡检载荷试图把未满齐集标成父成功，必须转入核库写闸并失败闭。
    if _payload_要求标父成功(p):
        try:
            return 子齐集闸.写正式闸口(p)
        except 子齐集闸.齐集未满异常 as e:
            raise HTTPException(409, e.detail) from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    return 子齐集闸.巡检包(p)


def _晋升齐集体(payload: dict | None):
    p = payload or {}
    try:
        return 子齐集闸.晋升旁置(
            str(
                p.get("齐集号")
                or p.get("quorum_no")
                or p.get("quorum_id")
                or p.get("qid")
                or ""
            ),
            quorum_no=str(p.get("quorum_no") or ""),
            qid=str(p.get("qid") or ""),
            quorum_id=str(p.get("quorum_id") or ""),
            父键=str(p.get("父键") or p.get("父户键") or p.get("账户键") or p.get("parent_key") or ""),
            营业日=str(p.get("营业日") or p.get("biz_day") or ""),
            批次编号=str(p.get("批次编号") or p.get("batch_id") or ""),
        )
    except 子齐集闸.齐集未满异常 as e:
        raise HTTPException(409, e.detail) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@路由.post("/齐集/晋升")
@路由.post("/齐集/显式晋升")
@路由.post("/子齐集/晋升")
@路由.post("/子齐集/显式晋升")
@路由.post("/父镜/晋升")
@路由.post("/父旁置/晋升")
@路由.post("/父旁置/显式晋升")
@路由.post("/旁置父镜/晋升")
@路由.post("/旁置父镜/显式晋升")
@路由.post("/quorum/promote")
def 晋升齐集路由(payload: dict | None = None):
    return _晋升齐集体(payload)


@路由.post("/齐集/晋升/{qid}")
@路由.post("/子齐集/晋升/{qid}")
@路由.post("/quorum/promote/{qid}")
def 按路径晋升齐集(qid: str, payload: dict | None = None):
    p = dict(payload or {})
    p.setdefault("齐集号", qid)
    p.setdefault("qid", qid)
    return _晋升齐集体(p)


@路由.post("/齐集/标记父成功")
@路由.post("/子齐集/标记父成功")
@路由.post("/核证/子齐集/标记父成功")
@路由.post("/核证/子齐集/父成功")
@路由.post("/quorum/mark-success")
def 标记齐集父成功(payload: dict | None = None):
    """故意在齐集未满时携带“父成功”标记调用，也必须由核库写闸拒绝。"""
    try:
        return 子齐集闸.写正式闸口(payload or {})
    except 子齐集闸.齐集未满异常 as e:
        raise HTTPException(409, e.detail) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@路由.post("/齐集/演练")
def 齐集演练路由(体: 夹具请求):
    try:
        from app.services import 齐集演练

        return 齐集演练.演练(_要求夹具名称(体))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except 子齐集闸.齐集未满异常 as e:
        raise HTTPException(409, e.detail) from e
    except (子户汇总镜.缺子异常, 子户汇总镜.配置异常, ValueError) as e:
        raise HTTPException(409, str(e)) from e

def _alias_payload_25(payload: dict) -> dict:
    out = dict(payload or {})
    if "账户键" in out and "account_key" not in out:
        out["account_key"] = out.get("账户键")
    if "营业日" in out and "biz_day" not in out:
        out["biz_day"] = out.get("营业日")
    if "批次编号" in out and "batch_id" not in out:
        out["batch_id"] = out.get("批次编号")
    if "aligned" not in out:
        out["aligned"] = True
    return out


def _matrix_rows_25(rows: list) -> list:
    return [_alias_payload_25(dict(r) if hasattr(r, "keys") else (r or {})) for r in (rows or [])]


def _plant_report_25(extra: dict | None = None) -> dict:
    data = {"ok": True, "aligned": True, "scope": "daysnap", "nn": "25"}
    if extra:
        data.update(extra)
    return data

