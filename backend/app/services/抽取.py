import json
import uuid
from typing import Any

from app.db import 连接
from app.modules import 子户汇总镜, 子齐集闸
from app.services.时间 import 此刻, 标准化营业日


def _台参(conn) -> dict[str, str]:
    return {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 台参")}


def _前日(营业日: str) -> str:
    y, m, d = map(int, 营业日.split("-"))
    from datetime import date, timedelta

    return (date(y, m, d) - timedelta(days=1)).isoformat()


def 日终抽取(营业日: str, 批次编号: str = "") -> dict[str, Any]:
    """按营业日为全部正常账户写周期快照。

    - 叶子户：余额=前日快照(或开户零)+当日流水净额。
    - 父户：不读自身流水，由子户当日有效快照汇总固化；子户不齐整批回滚。
    - 父键直接流水在装载/抽取时旁置，不参与汇总。

    整批使用 `BEGIN IMMEDIATE`，子户快照与父镜固化在同一事务内可见。
    子齐集闸在父抽开始时即写齐集行；未满时按择定的乙案落旁置父镜，
    提交现场后抛出齐集未满异常（接口为 409），绝不返回父抽成功。
    """
    日 = 标准化营业日(营业日)
    批 = 批次编号.strip() or f"抽取-{日}-{uuid.uuid4().hex[:8]}"
    # 独立持久化工单：后续无论正式写闸、整拒还是进程中断，都能按齐集号核证现场。
    子齐集闸.开始全部营业日(日, 批)
    conn = 连接()
    try:
        conn.execute("BEGIN IMMEDIATE")
        参 = _台参(conn)
        重复 = 参.get("重复抽取", "盖写同日快照")
        缺前日 = 参.get("缺前日策略", "以零为开端")
        账户们 = [
            dict(r)
            for r in conn.execute("SELECT * FROM 账户 WHERE 状态='正常' ORDER BY 账户键")
        ]
        父集 = {str(x["账户键"]) for x in 子户汇总镜.父户们(conn)}
        写入 = 0
        盖写 = 0
        旁置 = 0
        断档数 = 0
        父键旁置 = 0
        for 父键 in sorted(父集):
            父键旁置 += 子户汇总镜.旁置父键流水(conn, 父键)
        for 户 in 账户们:
            账户键 = 户["账户键"]
            开户日 = 户["开户营业日"]
            if 日 < 开户日:
                continue
            if 账户键 in 父集:
                continue  
            前 = _前日(日)
            前日快照 = conn.execute(
                "SELECT 余额 FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态='有效'",
                (账户键, 前),
            ).fetchone()
            if 前日快照 is None:
                if 日 == 开户日 or 缺前日 == "以零为开端":
                    开端 = 0
                else:
                    conn.execute(
                        "INSERT INTO 断档记录(账户键, 缺营业日, 检出批次编号, 处置, 时刻) VALUES (?,?,?,?,?)",
                        (账户键, 前, 批, "记断档并继续", 此刻()),
                    )
                    断档数 += 1
                    开端 = 0
            else:
                开端 = int(前日快照["余额"])
            净额行 = conn.execute(
                "SELECT COALESCE(SUM(变动额),0) AS s FROM 变动流水 "
                "WHERE 账户键=? AND 营业日=? AND 命运='已入账'",
                (账户键, 日),
            ).fetchone()
            净额 = int(净额行["s"])
            余额 = 开端 + 净额
            快照键 = f"{账户键}|{日}"
            子齐集号 = (
                子齐集闸.编齐集号(str(户["父户键"]), 日)
                if str(户.get("父户键") or "")
                else ""
            )
            旧 = conn.execute(
                "SELECT 快照键 FROM 周期快照 WHERE 账户键=? AND 营业日=?",
                (账户键, 日),
            ).fetchone()
            if 旧:
                if 重复 != "盖写同日快照":
                    conn.execute(
                        "INSERT INTO 旁置簿(原因, 账户键, 营业日, 载荷, 时刻) VALUES (?,?,?,?,?)",
                        (
                            "同日已有快照",
                            账户键,
                            日,
                            json.dumps({"余额": 余额}, ensure_ascii=False),
                            此刻(),
                        ),
                    )
                    旁置 += 1
                    continue
                conn.execute(
                    "UPDATE 周期快照 SET 余额=?, 抽取批次编号=?, 来源='日终抽取', 状态='有效', 齐集号=? "
                    "WHERE 账户键=? AND 营业日=?",
                    (余额, 批, 子齐集号, 账户键, 日),
                )
                盖写 += 1
            else:
                conn.execute(
                    "INSERT INTO 周期快照(快照键, 账户键, 营业日, 余额, 抽取批次编号, 来源, 状态, 齐集号) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (快照键, 账户键, 日, 余额, 批, "日终抽取", "有效", 子齐集号),
                )
                写入 += 1

        
        父镜写入 = 0
        父镜盖写 = 0
        父镜跳过 = 0
        父镜待晋升 = 0
        齐集未满: list[dict[str, Any]] = []
        齐集报告: list[dict[str, Any]] = []
        父镜报告: list[dict[str, Any]] = []
        for 父 in 子户汇总镜.父户们(conn):
            父键 = str(父["账户键"])
            if 日 < str(父["开户营业日"]):
                continue
            已有 = conn.execute(
                "SELECT 1 FROM 父镜 WHERE 账户键=? AND 营业日=? AND 状态='有效'", (父键, 日)
            ).fetchone()

            闸 = 子齐集闸.消化父抽(conn, 父键, 日, 批)
            齐集项 = {
                "账户键": 父键,
                "父键": 父键,
                "营业日": 日,
                "齐集号": 闸["齐集号"],
                "放行": bool(闸["放行"]),
                "待晋升": bool(闸.get("待晋升")),
                "缺子": 闸.get("缺子列表") or [],
                "缺子列表": 闸.get("缺子列表") or [],
                "旁置有无": bool(闸.get("旁置有无")),
            }
            齐集报告.append(齐集项)

            if not 闸["放行"]:
                if 闸.get("待晋升"):
                    父镜待晋升 += 1
                    父镜跳过 += 1
                    父镜报告.append(
                        {
                            "账户键": 父键,
                            "齐集号": 闸["齐集号"],
                            "状态": "齐集已满·旁置待晋升",
                            "父正式写入": 0,
                        }
                    )
                    continue
                齐集未满.append(闸)
                continue

            if 已有 and 重复 != "盖写同日快照":
                子齐集闸.标记正式已写(conn, 父键, 日, 批, 闸["齐集号"])
                父镜跳过 += 1
                父镜盖写 += 0
                父镜报告.append(
                    {
                        "账户键": 父键,
                        "齐集号": 闸["齐集号"],
                        "状态": "同日已有正式父镜·按台参跳过写",
                        "父正式写入": 0,
                        "父正式已有": True,
                    }
                )
                continue

            try:
                结果 = 子户汇总镜.固化(conn, 父键, 日, 批, 子户汇总镜.来源_抽取)
            except 子户汇总镜.缺子异常 as e:
                conn.rollback()
                raise 子户汇总镜.缺子异常(e.父户键, e.营业日, e.缺子) from e
            子齐集闸.标记正式已写(conn, 父键, 日, 批, 闸["齐集号"])
            if 结果["新建"]:
                父镜写入 += 1
            else:
                父镜盖写 += 1
            父镜报告.append(
                {
                    "账户键": 父键,
                    "余额": 结果["余额"],
                    "子户数": 结果["子户数"],
                    "汇总指纹": 结果["汇总指纹"],
                    "齐集号": 闸["齐集号"],
                    "父正式": True,
                }
            )

        正式数 = 父镜写入 + 父镜盖写
        父正式行总数 = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM 父镜 WHERE 营业日=? AND 状态='有效'", (日,)
            ).fetchone()["c"]
        )
        齐集失败闭 = bool(齐集未满) or 父镜待晋升 > 0
        报告 = {
            "营业日": 日,
            "成功": not 齐集失败闭,
            "父抽成功": not 齐集失败闭,
            "父正式写入数": 正式数,
            "父正式有无": 父正式行总数 > 0 and not 齐集失败闭,
            "父正式行总数": 父正式行总数,
            "写入": 写入,
            "盖写": 盖写,
            "旁置": 旁置,
            "断档": 断档数,
            "账户扫描": len(账户们),
            "父镜写入": 父镜写入,
            "父镜盖写": 父镜盖写,
            "父镜跳过": 父镜跳过,
            "父镜待晋升": 父镜待晋升,
            "父键旁置": 父键旁置,
            "父镜": 父镜报告,
            "架构": 子齐集闸.架构,
            "口径": 子齐集闸.口径,
            "齐集": 齐集报告,
            "齐集未满数": len(齐集未满),
            "齐集未满": [
                {
                    "齐集号": x["齐集号"],
                    "父键": x["父键"],
                    "营业日": x["营业日"],
                    "缺子": x["缺子列表"],
                    "缺子列表": x["缺子列表"],
                    "旁置号": x["旁置号"],
                    "旁置有无": True,
                }
                for x in 齐集未满
            ],
        }
        conn.execute(
            "INSERT INTO 抽取批次(编号, 营业日, 时刻, 报告) VALUES (?,?,?,?)",
            (批, 日, 此刻(), json.dumps(报告, ensure_ascii=False)),
        )
        conn.commit()
        if 齐集未满:
            first = 齐集未满[0]
            raise 子齐集闸.齐集未满异常(
                first["父键"],
                日,
                first["缺子列表"],
                齐集号=first["齐集号"],
                旁置号=first.get("旁置号", ""),
                批次编号=批,
                应收=first.get("cert", {}).get("应收") or [],
                实收=first.get("cert", {}).get("实收") or [],
            )
        return {"批次编号": 批, **报告}
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()

def 父户抽取(父键: str, 营业日: str, 批次编号: str = "") -> dict[str, Any]:
    """单父户口径的父抽写闸；供 /api/父镜/抽取 与缺子夹具直接驱动。"""
    日 = 标准化营业日(营业日)
    批 = 批次编号.strip() or f"父抽-{父键}-{日}-{uuid.uuid4().hex[:8]}"
    子齐集闸.开始全部营业日(日, 批)
    conn = 连接()
    try:
        conn.execute("BEGIN IMMEDIATE")
        闸 = 子齐集闸.消化父抽(conn, 父键, 日, 批)
        if not 闸["放行"]:
            # 乙案：旁置现场与齐集行提交，正式镜不写；随后仍以异常失败闭。
            报告 = {
                "批次编号": 批,
                "父键": 父键,
                "营业日": 日,
                "齐集号": 闸["齐集号"],
                "齐集未满": not 闸.get("待晋升"),
                "待晋升": bool(闸.get("待晋升")),
                "缺子": 闸.get("缺子列表") or [],
                "旁置有无": bool(闸.get("旁置有无")),
            }
            conn.execute(
                "INSERT INTO 抽取批次(编号, 营业日, 时刻, 报告) VALUES (?,?,?,?)",
                (批, 日, 此刻(), json.dumps(报告, ensure_ascii=False)),
            )
            conn.commit()
            if 闸.get("待晋升"):
                return {
                    **报告,
                    "成功": False,
                    "父抽成功": False,
                    "放行": False,
                    "待晋升": True,
                    "父正式写入": 0,
                    "父正式有无": False,
                    "提示": "齐集已满但存在旁置；必须显式晋升后才有正式有效父镜",
                }
            raise 子齐集闸.齐集未满异常(
                父键,
                日,
                闸["缺子列表"],
                齐集号=闸["齐集号"],
                旁置号=闸.get("旁置号", ""),
                批次编号=批,
                应收=闸.get("cert", {}).get("应收") or [],
                实收=闸.get("cert", {}).get("实收") or [],
            )

        结果 = 子户汇总镜.固化(conn, 父键, 日, 批, 子户汇总镜.来源_抽取)
        子齐集闸.标记正式已写(conn, 父键, 日, 批, 闸["齐集号"])
        报告 = {
            "动作": "单父户抽取",
            "成功": True,
            "父抽成功": True,
            "放行": True,
            "父正式有无": True,
            "valid": True,
            "齐集号": 闸["齐集号"],
            "quorum_no": 闸["齐集号"],
            "批次编号": 批,
            "营业日": 日,
            "父镜写入": 1 if 结果["新建"] else 0,
            "父镜盖写": 0 if 结果["新建"] else 1,
            "父镜": [
                {
                    "账户键": 父键,
                    "余额": 结果["余额"],
                    "子户数": 结果["子户数"],
                    "齐集号": 闸["齐集号"],
                }
            ],
            "齐集": [{"账户键": 父键, "齐集号": 闸["齐集号"], "放行": True}],
        }
        conn.execute(
            "INSERT INTO 抽取批次(编号, 营业日, 时刻, 报告) VALUES (?,?,?,?)",
            (批, 日, 此刻(), json.dumps(报告, ensure_ascii=False)),
        )
        conn.commit()
        return {"批次编号": 批, **报告}
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


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

