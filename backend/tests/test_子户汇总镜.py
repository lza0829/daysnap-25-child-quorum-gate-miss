"""子户汇总镜（乙·指纹固化）回归测试。

运行：cd backend && ../.venv/bin/python -m pytest tests -q
"""

import json
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest


_临时 = tempfile.mkdtemp(prefix="daysnap-测试-")
os.environ["数据目录"] = _临时
os.environ["夹具目录"] = str(Path(__file__).resolve().parent.parent.parent / "fixtures")

from app import seed  
from app.db import 连接, 库路径  
from app.modules import 子户汇总镜  
from app.services import 抽取, 回放  
from app.services.装载 import 装载流水  

户甲 = "户甲"
户乙 = "户乙"
父 = "户汇总"
子甲 = "户子甲"
子乙 = "户子乙"


@pytest.fixture(autouse=True)
def 干净库():
    seed.初始化库()
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
            "账户",
        ):
            conn.execute(f"DELETE FROM {t}")
        conn.execute("UPDATE 台参 SET 值='盖写同日快照' WHERE 键='重复抽取'")
        for 键, 名, 日, 父键 in [
            ("户甲", "甲", "2026-11-01", ""),
            ("户乙", "乙", "2026-11-01", ""),
            ("户汇总", "汇总", "2026-11-01", ""),
            ("户子甲", "子甲", "2026-11-01", "户汇总"),
            ("户子乙", "子乙", "2026-11-01", "户汇总"),
        ]:
            conn.execute(
                "INSERT INTO 账户(账户键, 户名, 币种, 开户营业日, 状态, 父户键) VALUES (?,?,?,?,?,?)",
                (键, 名, "CNY", 日, "正常", 父键),
            )
        conn.commit()
    finally:
        conn.close()
    yield


def _流水(流水号, 账户键, 日, 额):
    return {"流水号": 流水号, "账户键": 账户键, "营业日": 日, "变动额": 额}


def _读快照(账户键, 日, conn=None):
    c = conn or 连接()
    try:
        r = c.execute(
            "SELECT 余额, 状态, 来源 FROM 周期快照 WHERE 账户键=? AND 营业日=?",
            (账户键, 日),
        ).fetchone()
        return None if r is None else dict(r)
    finally:
        if conn is None:
            c.close()


def _篡改子快照(账户键, 日, 新余额):
    """模拟直接改库：只动子快照余额，不改批次/指纹源。"""
    conn = 连接()
    try:
        conn.execute(
            "UPDATE 周期快照 SET 余额=? WHERE 账户键=? AND 营业日=?",
            (新余额, 账户键, 日),
        )
        conn.commit()
    finally:
        conn.close()


def test_两子抽后抽父_父等于子和():
    日 = "2026-11-20"
    装载流水([_流水("a1", 子甲, 日, 1000), _流水("b1", 子乙, 日, 2000)])
    r = 抽取.日终抽取(日)
    assert r["父镜写入"] == 1
    父镜 = 子户汇总镜.读取父镜(父, 日)
    assert 父镜 is not None
    assert 父镜["余额"] == 3000
    assert 父镜["子户数"] == 2
    assert {x["账户键"] for x in 父镜["子集合"]} == {子甲, 子乙}
    
    assert _读快照(父, 日)["余额"] == 3000


def test_父键流水旁置不入汇总():
    日 = "2026-11-21"
    装 = 装载流水(
        [
            _流水("a2", 子甲, 日, 500),
            _流水("p1", 父, 日, 99999),
        ]
    )
    assert 装["旁置"] == 1, "父键直接流水应在装载即旁置"
    r = 抽取.日终抽取(日)
    父镜 = 子户汇总镜.读取父镜(父, 日)
    assert 父镜["余额"] == 500, "父键直接流水不得计入父镜"
    conn = 连接()
    try:
        旁置 = conn.execute(
            "SELECT * FROM 旁置簿 WHERE 原因='父键直接流水' AND 账户键=?", (父,)
        ).fetchall()
        assert len(旁置) == 1
        
        assert (
            conn.execute("SELECT 1 FROM 变动流水 WHERE 流水号='p1'").fetchone() is None
        )
        assert r["父键旁置"] == 0
    finally:
        conn.close()


def test_先装流水后配父户_配置时旁置父键流水():
    """账户先以叶子身份装流水、后被配成父户：配置当下即旁置其直接流水。"""
    日 = "2026-11-29"
    装载流水([_流水("q1", 户甲, 日, 1234)])
    conn = 连接()
    try:
        assert conn.execute("SELECT 命运 FROM 变动流水 WHERE 流水号='q1'").fetchone()["命运"] == "已入账"
    finally:
        conn.close()

    报告 = 子户汇总镜.配置父户(子户键=户乙, 父户键=户甲)
    assert 报告["父键流水旁置"] == 1
    
    装2 = 装载流水([_流水("q2", 户甲, 日, 55)])
    assert 装2["旁置"] == 1
    r = 抽取.日终抽取(日)
    assert r["父键旁置"] == 0, "已被旁置的父键流水不应重复计数"
    父镜 = 子户汇总镜.读取父镜(户甲, 日)
    assert 父镜 is not None and 父镜["余额"] == 0
    conn = 连接()
    try:
        assert conn.execute("SELECT 命运 FROM 变动流水 WHERE 流水号='q1'").fetchone()["命运"] != "已入账"
        assert conn.execute("SELECT 1 FROM 变动流水 WHERE 流水号='q2'").fetchone() is None
    finally:
        conn.close()


def test_篡改子快照_父主读不变且指纹失配():
    日 = "2026-11-22"
    装载流水([_流水("a3", 子甲, 日, 1000), _流水("b3", 子乙, 日, 2000)])
    抽取.日终抽取(日)
    原 = 子户汇总镜.读取父镜(父, 日)

    _篡改子快照(子乙, 日, 7777)

    
    主读 = 子户汇总镜.读取父镜(父, 日)
    assert 主读["余额"] == 原["余额"] == 3000
    assert 主读["汇总指纹"] == 原["汇总指纹"]
    assert _读快照(父, 日)["余额"] == 3000

    
    核证 = 子户汇总镜.核证(父, 日)
    assert 核证["找到"] is True
    assert 核证["固化余额"] == 3000
    assert 核证["现场重算余额"] == 8777
    assert 核证["指纹匹配"] is False
    assert 核证["valid"] is False
    assert 核证["失配子"] == [子乙]
    
    assert 子户汇总镜.读取父镜(父, 日)["余额"] == 3000


def test_显式重汇总后父主读刷新():
    日 = "2026-11-23"
    装载流水([_流水("a4", 子甲, 日, 1000), _流水("b4", 子乙, 日, 2000)])
    抽取.日终抽取(日)
    _篡改子快照(子乙, 日, 5000)
    r = 子户汇总镜.重汇总(父, 日)
    assert r["余额"] == 6000
    assert r["前余额"] == 3000
    assert 子户汇总镜.读取父镜(父, 日)["余额"] == 6000
    assert _读快照(父, 日)["余额"] == 6000
    assert 子户汇总镜.核证(父, 日)["valid"] is True


def test_子户未齐_父镜不得假成功():
    """显式重汇总时子户当日有效快照不齐：整体失败，旧父行不被改写。"""
    日 = "2026-11-24"
    装入 = 装载流水([_流水("a5", 子甲, 日, 1000), _流水("b5", 子乙, 日, 500)])
    assert 装入["入账"] == 2
    抽取.日终抽取(日)
    原 = 子户汇总镜.读取父镜(父, 日)
    assert 原["余额"] == 1500

    
    conn = 连接()
    try:
        conn.execute("DELETE FROM 周期快照 WHERE 账户键=? AND 营业日=?", (子乙, 日))
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(子户汇总镜.缺子异常) as ei:
        子户汇总镜.重汇总(父, 日)
    assert 子乙 in ei.value.缺子
    
    assert 子户汇总镜.读取父镜(父, 日)["余额"] == 原["余额"]


def test_抽取整批原子性_父失败则子行回滚():
    """父镜固化失败时，同批写入的子快照必须一并回滚。"""
    日 = "2026-11-28"
    装载流水([_流水("a8", 子甲, 日, 800), _流水("b8", 子乙, 日, 200)])

    def 爆(conn, 父户键, 营业日, 批次编号, 来源="x"):
        raise 子户汇总镜.缺子异常(父户键, 营业日, [子乙])

    原 = 子户汇总镜.固化
    子户汇总镜.固化 = 爆
    try:
        with pytest.raises(子户汇总镜.缺子异常):
            抽取.日终抽取(日)
    finally:
        子户汇总镜.固化 = 原
    assert _读快照(子甲, 日) is None, "父失败时同批子行不得留存"
    assert _读快照(子乙, 日) is None
    assert 子户汇总镜.读取父镜(父, 日) is None


def test_子父并发抽取_不得父成功子缺日():
    """两个线程同时抽同一天：事务串行化，终态父子必齐且父=子和。"""
    import threading

    日 = "2026-11-27"
    装载流水([_流水("a9", 子甲, 日, 800), _流水("b9", 子乙, 日, 200)])
    结果: list[dict] = []
    错误: list[BaseException] = []

    def 跑(批: str):
        try:
            结果.append(抽取.日终抽取(日, 批))
        except BaseException as e:  
            错误.append(e)

    t1 = threading.Thread(target=跑, args=("并发甲",))
    t2 = threading.Thread(target=跑, args=("并发乙",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert not 错误, f"并发抽取不应失败: {错误}"
    assert len(结果) == 2
    父镜 = 子户汇总镜.读取父镜(父, 日)
    assert 父镜 is not None
    assert 父镜["子户数"] == 2
    assert 父镜["余额"] == 1000
    assert _读快照(子甲, 日) is not None and _读快照(子乙, 日) is not None
    
    assert 父镜["抽取批次编号"] in {r["批次编号"] for r in 结果}
    assert 子户汇总镜.核证(父, 日)["valid"] is True


def test_并发抽取_不得父成功子缺日():
    """子户与父在同一事务内落行：任一子缺，父必然整体失败。"""
    日 = "2026-11-25"
    装载流水([_流水("a6", 子甲, 日, 700), _流水("b6", 子乙, 日, 300)])
    抽取.日终抽取(日)
    父镜 = 子户汇总镜.读取父镜(父, 日)
    快照 = {k: _读快照(k, 日) for k in (子甲, 子乙, 父)}
    assert all(v is not None for v in 快照.values()), "父成功时子必齐"
    assert 父镜["余额"] == 1000
    assert sum(v["余额"] for k, v in 快照.items() if k in (子甲, 子乙)) == 1000
    
    批 = _读快照(父, 日)["来源"]
    assert 批 == "子户汇总"


def test_回放对父镜走指纹核对而非流水():
    日 = "2026-11-26"
    装载流水([_流水("a7", 子甲, 日, 400), _流水("b7", 子乙, 日, 600)])
    抽取.日终抽取(日)
    r = 回放.回放核对(日)
    assert r["通过"] is True
    _篡改子快照(子甲, 日, 9999)
    r2 = 回放.回放核对(日)
    assert r2["通过"] is False
    assert r2["差额"] >= 1


def test_禁止读时JOIN_父主读只查父镜表():
    """结构守卫：主读函数源码不得出现子表 JOIN。"""
    import inspect

    src = inspect.getsource(子户汇总镜.读取父镜)
    assert "JOIN" not in src.upper()
    assert "周期快照" not in src, "父主读不得读子快照表"


def test_重复抽取旁置口径下父镜不静默改写():
    日 = "2026-11-30"
    装载流水([_流水("a9", 子甲, 日, 100), _流水("b9", 子乙, 日, 200)])
    抽取.日终抽取(日)
    conn = 连接()
    try:
        conn.execute("UPDATE 台参 SET 值='旁置同日载荷' WHERE 键='重复抽取'")
        conn.commit()
    finally:
        conn.close()
    原 = 子户汇总镜.读取父镜(父, 日)
    r = 抽取.日终抽取(日)
    assert r["父镜跳过"] == 1
    assert r["父镜盖写"] == 0
    后 = 子户汇总镜.读取父镜(父, 日)
    assert 后["余额"] == 原["余额"] and 后["汇总指纹"] == 原["汇总指纹"]
