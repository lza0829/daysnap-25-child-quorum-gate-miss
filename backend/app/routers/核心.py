import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db import 夹具目录, 连接
from app.modules import 子户汇总镜
from app.services import 回放, 抽取, 目录, 装载
from app.services import 父镜演练 as 父镜演练服务

路由 = APIRouter(prefix="/api")


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
    名: str


@路由.post("/装载夹具/{名}")
def 装载夹具路径(名: str):
    return _装载夹具文件(名)


@路由.post("/装载夹具")
def 装载夹具体(体: 夹具请求):
    return _装载夹具文件(体.名)


def _装载夹具文件(名: str):
    path = 夹具目录 / 名
    if not path.exists():
        raise HTTPException(404, f"夹具不存在: {名}")
    data = json.loads(path.read_text(encoding="utf-8"))
    流水 = data.get("流水") or data.get("事件") or []
    return 装载.装载流水(流水, str(data.get("批次编号") or ""))


@路由.post("/抽取")
def 执行抽取(体: 营业日请求):
    try:
        return 抽取.日终抽取(体.营业日, 体.批次编号)
    except 子户汇总镜.缺子异常 as e:
        raise HTTPException(
            409, {"原因": "父镜未成·缺子户快照", "父户键": e.父户键, "营业日": e.营业日, "缺子": e.缺子}
        ) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@路由.post("/回放")
def 执行回放(体: 营业日请求):
    try:
        return 回放.回放核对(体.营业日, 体.批次编号)
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
def 列父镜(营业日: str = "", 账户键: str = "", 含失效: bool = False):
    """父对外主读：只返回父镜固化行，不 JOIN 子表。"""
    return 子户汇总镜.列父镜(营业日, 账户键, 含失效)


@路由.get("/父镜/行")
def 取父镜(账户键: str, 营业日: str):
    """父对外主读单行：只读父镜固化表，不 JOIN 子表。"""
    row = 子户汇总镜.读取父镜(账户键, 营业日)
    if row is None:
        raise HTTPException(404, f"父镜不存在: {账户键} {营业日}")
    return row


@路由.post("/父镜/核证")
def 核证父镜(体: 父镜请求):
    """只读核证：固化值 vs 现场重算 + 指纹匹配。不改任何固化行。"""
    return 子户汇总镜.核证(体.账户键, 体.营业日)


@路由.post("/父镜/重汇总")
def 重汇总父镜(体: 父镜请求):
    try:
        return 子户汇总镜.重汇总(体.账户键, 体.营业日, 体.批次编号)
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
        return 父镜演练服务.演练(体.名)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except (子户汇总镜.缺子异常, 子户汇总镜.配置异常) as e:
        raise HTTPException(409, str(e)) from e

from app.modules import 子齐集闸 as _bf_mod_25


@路由.get("/核证/子齐集")
def 取核证_25(键: str | None = None):
    conn = 连接()
    try:
        return _bf_mod_25.查现场(conn, 键)
    finally:
        conn.close()


@路由.post("/核证/子齐集/巡检")
def 巡检核证_25(payload: dict | None = None):
    return _bf_mod_25.巡检包(payload or {})

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

