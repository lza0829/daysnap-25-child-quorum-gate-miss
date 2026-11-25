"""子齐集闸端到端演练：缺子抽父、旁置可读、回放拒权威、补齐后显式晋升。"""

from __future__ import annotations

import json
from typing import Any

from app.db import 夹具目录, 连接
from app.modules import 子户汇总镜, 子齐集闸
from app.services import 回放, 抽取
from app.services.装载 import 装载流水


def _读夹具(名: str) -> dict[str, Any]:
    原名 = str(名 or "").strip()
    if not 原名:
        raise ValueError("夹具名不能为空")
    候选 = [原名]
    if not 原名.lower().endswith(".json"):
        候选.append(f"{原名}.json")
    别名 = {
        "quorum-missing": "子齐集缺子样例.json",
        "child-quorum-missing": "子齐集缺子样例.json",
        "missing-child": "子齐集缺子样例.json",
        "missing": "子齐集缺子样例.json",
        "quorum-promote": "子齐集晋升样例.json",
        "child-quorum-promote": "子齐集晋升样例.json",
        "promotion": "子齐集晋升样例.json",
        "quorum-concurrent": "子齐集并发样例.json",
        "child-quorum-concurrent": "子齐集并发样例.json",
        "concurrency": "子齐集并发样例.json",
    }
    逻辑名 = 原名[:-5] if 原名.lower().endswith(".json") else 原名
    if 逻辑名 in 别名:
        候选.insert(0, 别名[逻辑名])
    path = None
    for 名候选 in 候选:
        p = 夹具目录 / 名候选
        if p.exists():
            path = p
            break
    if path is None:
        raise FileNotFoundError(f"夹具不存在: {名}")
    return json.loads(path.read_text(encoding="utf-8"))


def _配置(项: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for x in 项 or []:
        try:
            out.append(子户汇总镜.配置父户(str(x["子户键"]), str(x["父户键"])))
        except 子户汇总镜.配置异常 as e:
            out.append({"子户键": x.get("子户键"), "错误": str(e)})
    return out


def _设状态(keys: list[str], 状态: str) -> None:
    if not keys:
        return
    conn = 连接()
    try:
        conn.execute("BEGIN IMMEDIATE")
        for key in keys:
            conn.execute("UPDATE 账户 SET 状态=? WHERE 账户键=?", (状态, str(key)))
        conn.commit()
    finally:
        conn.close()


def _抽取日(日: str, 批: str = "", *, 单父: str = "") -> dict[str, Any]:
    try:
        if 单父:
            return 抽取.父户抽取(单父, 日, 批)
        return 抽取.日终抽取(日, 批)
    except 子齐集闸.齐集未满异常 as e:
        return {"错误": "齐集未满·失败闭", "HTTP状态": 409, **e.detail}


def 演练(名: str) -> dict[str, Any]:
    f = _读夹具(名)

    # 纯并发夹具沿用父镜演练器里已经验证的多线程入口；
    # 缺子/晋升夹具才走本文件的状态机。这样 /api/齐集/演练 也能直接跑并发夹具。
    if f.get("并发抽取") and not (f.get("缺子抽取") or f.get("补齐")):
        from app.services import 父镜演练

        return 父镜演练.演练(名)

    parent = str(f.get("父户键") or f.get("父键") or "户汇总")
    day = str(f.get("营业日") or "")
    report: dict[str, Any] = {"夹具": 名, "说明": f.get("说明", ""), "步骤": [], "架构": 子齐集闸.架构}

    if f.get("账户配置"):
        cfg = _配置(f["账户配置"])
        report["步骤"].append({"配置": cfg})

    停用 = f.get("停用账户") or f.get("初始停用") or []
    if 停用:
        _设状态([str(x) for x in 停用], "停用")
        report["步骤"].append({"停用账户": 停用})

    if f.get("流水"):
        load = 装载流水(f["流水"], str(f.get("批次编号") or ""))
        report["步骤"].append({"装载": load})

    missing_cfg = f.get("缺子抽取")
    if missing_cfg:
        m = missing_cfg if isinstance(missing_cfg, dict) else {"营业日": day}
        mday = str(m.get("营业日") or day)
        before = _抽取日(
            mday,
            str(m.get("批次编号") or ""),
            单父=str(m.get("父户键") or parent if m.get("单父") else ""),
        )
        qid = str(before.get("齐集号") or 子齐集闸.编齐集号(parent, mday))
        conn = 连接()
        try:
            cert = 子齐集闸.核证现场(conn, 齐集号=qid)
        finally:
            conn.close()
        official = 子户汇总镜.读取父镜(parent, mday)
        replay = None
        if m.get("回放", True):
            try:
                replay = 回放.回放核对(mday)
            except Exception as e:  # 演练需要把错误结构化返回
                replay = {"错误": str(e)}
        block = {
            "缺子抽父": before,
            "齐集核证": cert,
            "父正式有无": official is not None and official.get("状态") == "有效",
            "父正式行": official,
            "回放": replay,
        }
        report["步骤"].append(block)
        report["缺子现场"] = {
            "齐集号": qid,
            "缺子列表": cert.get("缺子列表") or [],
            "旁置有无": bool(cert.get("旁置有无")),
            "父正式有无": block["父正式有无"],
            "valid": bool(cert.get("valid")),
        }

    patch = f.get("补齐") or {}
    if patch:
        启用 = patch.get("启用账户") or []
        if 启用:
            _设状态([str(x) for x in 启用], "正常")
        if patch.get("流水"):
            load2 = 装载流水(patch["流水"], str(patch.get("批次编号") or ""))
            report["步骤"].append({"补齐装载": load2})
        pday = str(patch.get("营业日") or day)
        if patch.get("抽取", True):
            after_extract = _抽取日(pday, str(patch.get("批次编号") or ""))
            report["步骤"].append({"补齐后抽取": after_extract})

    if f.get("晋升") or patch.get("晋升"):
        pday = day
        qid = 子齐集闸.编齐集号(parent, pday)
        try:
            promo = 子齐集闸.晋升旁置(qid, 父键=parent, 营业日=pday)
            report["步骤"].append({"晋升": promo})
            report["晋升现场"] = {
                "齐集号": qid,
                "父正式有无": bool(promo.get("父正式有无")),
                "旁置有无": bool(promo.get("旁置有无")),
                "valid": bool(promo.get("valid")),
            }
        except Exception as e:
            report["步骤"].append({"晋升错误": str(e)})
            report["晋升失败"] = str(e)

    if f.get("最终回放", True) and day:
        try:
            final_replay = 回放.回放核对(day)
            report["步骤"].append({"最终回放": final_replay})
        except Exception as e:
            report["步骤"].append({"最终回放错误": str(e)})

    if day:
        conn = 连接()
        try:
            final_cert = 子齐集闸.核证现场(conn, 父键=parent, 营业日=day)
            report["最终核证"] = final_cert
        finally:
            conn.close()

    return report
