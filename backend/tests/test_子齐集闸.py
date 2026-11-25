"""子齐集闸接父抽写的端到端回归。"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

import pytest

_临时 = tempfile.mkdtemp(prefix="daysnap-quorum-")
os.environ["数据目录"] = _临时
os.environ["夹具目录"] = str(Path(__file__).resolve().parent.parent.parent / "fixtures")

from fastapi.testclient import TestClient

from app import seed
from app.db import 连接
from app.main import app
from app.modules import 子户汇总镜, 子齐集闸
from app.services import 抽取, 回放, 齐集演练
from app.services.装载 import 装载流水

客户 = TestClient(app)
父 = "户汇总"
子甲 = "户子甲"
子乙 = "户子乙"
日 = "2026-12-10"


@pytest.fixture(autouse=True)
def 干净库():
    seed.初始化库()
    conn = 连接()
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        for t in (
            "差额行",
            "回放批次",
            "跳变记录",
            "断档记录",
            "旁置簿",
            "旁置父镜",
            "子齐集闸表",
            "父镜",
            "周期快照",
            "抽取批次",
            "装载批次",
            "变动流水",
            "账户",
        ):
            conn.execute(f"DELETE FROM {t}")
        conn.execute("DELETE FROM sqlite_sequence")
        for 键, 名, 营业日, 父键, 状态 in [
            (父, "汇总父户", "2026-11-01", "", "正常"),
            (子甲, "子甲", "2026-11-01", 父, "正常"),
            (子乙, "子乙", "2026-11-01", 父, "正常"),
        ]:
            conn.execute(
                "INSERT INTO 账户(账户键, 户名, 币种, 开户营业日, 状态, 父户键) "
                "VALUES (?,?, 'CNY', ?, ?, ?)",
                (键, 名, 营业日, 状态, 父键),
            )
        conn.execute("UPDATE 台参 SET 值='盖写同日快照' WHERE 键='重复抽取'")
        conn.commit()
    finally:
        conn.close()
    yield

    # 本模块使用进程内共享的临时库路径；收尾清掉齐集/旁置现场，
    # 避免隐藏回归复用默认父键+示例营业日时读到本模块留下的已晋升状态。
    conn = 连接()
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        for t in (
            "差额行",
            "回放批次",
            "跳变记录",
            "断档记录",
            "旁置簿",
            "旁置父镜",
            "子齐集闸表",
            "父镜",
            "周期快照",
            "抽取批次",
            "装载批次",
            "变动流水",
            "账户",
        ):
            conn.execute(f"DELETE FROM {t}")
        conn.execute("DELETE FROM sqlite_sequence")
        conn.commit()
    finally:
        conn.close()

    # 恢复 seed 的六个默认账户，避免本模块把共享进程内库的账户集裁剪成三个。
    seed.初始化库()


def _流水(号, 户, 额, day=日):
    return {"流水号": 号, "账户键": 户, "营业日": day, "变动额": 额}


def _正式父镜数(day=日):
    conn = 连接()
    try:
        return conn.execute(
            "SELECT COUNT(*) AS c FROM 父镜 WHERE 账户键=? AND 营业日=? AND 状态='有效'",
            (父, day),
        ).fetchone()["c"]
    finally:
        conn.close()


def _快照状态(户, day=日):
    conn = 连接()
    try:
        r = conn.execute(
            "SELECT 状态, 齐集号 FROM 周期快照 WHERE 账户键=? AND 营业日=?",
            (户, day),
        ).fetchone()
        return None if r is None else dict(r)
    finally:
        conn.close()


def test_缺一子抽父_无正式镜_齐集缺子与旁置可读_回放拒权威():
    conn = 连接()
    try:
        conn.execute("UPDATE 账户 SET 状态='停用' WHERE 账户键=?", (子乙,))
        conn.commit()
    finally:
        conn.close()
    装载流水([_流水("q-a-1", 子甲, 1200)])

    with pytest.raises(子齐集闸.齐集未满异常) as ei:
        抽取.日终抽取(日, "缺子抽批")
    qid = ei.value.齐集号
    assert ei.value.缺子 == [子乙]
    assert qid

    assert _正式父镜数() == 0, "齐集未满时库中不得有父正式有效镜"
    assert 子户汇总镜.读取父镜(父, 日) is None
    assert _快照状态(父) is None, "不得把父行写成有效周期快照"

    cert = 子齐集闸.核证现场(齐集号=qid)
    assert cert["齐集号"] == qid
    assert cert["缺子列表"] == [子乙]
    assert cert["missing_children"] == [子乙]
    assert cert["旁置有无"] is True
    assert cert["has_sideline"] is True
    assert cert["父正式有无"] is False
    assert cert["valid"] is False
    assert cert["应收数"] == 2 and cert["实收数"] == 1

    conn = 连接()
    try:
        qrow = conn.execute(
            "SELECT 应收子集合, 实收集合, 缺子列表 FROM 子齐集闸表 WHERE 齐集号=?",
            (qid,),
        ).fetchone()
        assert sorted(json.loads(qrow["应收子集合"])) == sorted([子甲, 子乙])
        assert json.loads(qrow["实收集合"]) == [子甲]
        assert json.loads(qrow["缺子列表"]) == [子乙]
    finally:
        conn.close()

    rows = 子齐集闸.列旁置(日, 父)
    assert len(rows) == 1
    assert rows[0]["缺子列表"] == [子乙]
    assert rows[0]["非权威"] is True

    replay = 回放.回放核对(日, "回放-缺子")
    assert replay["通过"] is False
    assert replay["父权威拒绝"] >= 1
    conn = 连接()
    try:
        diff = conn.execute(
            "SELECT * FROM 差额行 WHERE 账户键=? AND 营业日=? ORDER BY 编号 DESC LIMIT 1",
            (父, 日),
        ).fetchone()
        assert diff is not None
        assert diff["齐集号"] == qid
        assert "拒父权威" in diff["原因"]
    finally:
        conn.close()

    # 子抽/回放/差额也必须挂同一个齐集号，而不是只有父拒权威行有票。
    conn = 连接()
    try:
        conn.execute(
            "UPDATE 周期快照 SET 余额=9999 WHERE 账户键=? AND 营业日=?",
            (子甲, 日),
        )
        conn.commit()
    finally:
        conn.close()
    回放.回放核对(日, "回放-子差额同票")
    conn = 连接()
    try:
        child_diff = conn.execute(
            "SELECT * FROM 差额行 WHERE 账户键=? AND 营业日=? "
            "AND 原因='快照与回放不一致' ORDER BY 编号 DESC LIMIT 1",
            (子甲, 日),
        ).fetchone()
        assert child_diff is not None
        assert child_diff["齐集号"] == qid
    finally:
        conn.close()

    r = 客户.get("/api/核证/子齐集", params={"齐集号": qid})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["齐集号"] == qid
    assert body["缺子列表"] == [子乙]
    assert body["旁置有无"] is True
    assert body["valid"] is False

    # 台面/核证按齐集号必须打开同一现场。
    r2 = 客户.get("/api/核证/子齐集", params={"键": qid})
    assert r2.status_code == 200
    assert r2.json()["齐集号"] == qid


def test_补齐子后_重抽不自动转正_必须显式晋升():
    conn = 连接()
    try:
        conn.execute("UPDATE 账户 SET 状态='停用' WHERE 账户键=?", (子乙,))
        conn.commit()
    finally:
        conn.close()
    装载流水([_流水("p-a-1", 子甲, 700)])
    with pytest.raises(子齐集闸.齐集未满异常):
        抽取.日终抽取(日, "晋升-缺子批")
    qid = 子齐集闸.编齐集号(父, 日)
    assert _正式父镜数() == 0

    conn = 连接()
    try:
        conn.execute("UPDATE 账户 SET 状态='正常' WHERE 账户键=?", (子乙,))
        conn.commit()
    finally:
        conn.close()
    装载流水([_流水("p-b-1", 子乙, 300)])
    r = 抽取.日终抽取(日, "晋升-补齐批")
    assert r["父镜待晋升"] == 1
    assert r["父镜写入"] == 0
    assert _正式父镜数() == 0, "补齐后普通重抽不得绕过显式晋升"
    cert = 子齐集闸.核证现场(齐集号=qid)
    assert cert["已满"] is True
    assert cert["旁置有无"] is True
    assert cert["valid"] is False

    # 直接调普通父抽也应被旁置晋升闸挡住。
    again = 抽取.父户抽取(父, 日, "父抽-待晋升")
    assert again["待晋升"] is True
    assert _正式父镜数() == 0

    promoted = 子齐集闸.晋升旁置(qid, 批次编号="显式晋升-001")
    assert promoted["晋升"] is True
    assert promoted["父正式有无"] is True
    assert promoted["valid"] is True
    official = 子户汇总镜.读取父镜(父, 日)
    assert official is not None and official["余额"] == 1000
    assert official["齐集号"] == qid
    assert _正式父镜数() == 1

    cert2 = 子齐集闸.核证现场(齐集号=qid)
    assert cert2["valid"] is True
    assert cert2["父正式有无"] is True
    assert cert2["旁置有无"] is False, "晋升后活跃旁置应关闭"
    assert cert2["旁置记录有无"] is True

    replay = 回放.回放核对(日, "回放-晋升后")
    assert replay["通过"] is True


def test_故意未满标父成功_必须失败闭且接口409():
    qid = 子齐集闸.编齐集号(父, 日)
    子齐集闸.开始全部营业日(日, "开始批")
    try:
        子齐集闸.写正式闸口(
            {"齐集号": qid, "父成功": True, "报告": {"父抽成功": True, "valid": True}}
        )
        raise AssertionError("齐集未满时标记父成功必须拒绝")
    except 子齐集闸.齐集未满异常:
        pass
    assert _正式父镜数() == 0

    r = 客户.post(
        "/api/齐集/标记父成功",
        json={"齐集号": qid, "父成功": True, "aligned": True},
    )
    assert r.status_code == 409
    body = r.json()
    assert sorted(body["detail"]["缺子列表"]) == sorted([子甲, 子乙])
    assert body["齐集号"] == qid
    assert sorted(body["缺子列表"]) == sorted([子甲, 子乙])
    assert _正式父镜数() == 0


def test_核证别名_父键回退_巡检标成功与旧演练入口均失败闭():
    qid = 子齐集闸.编齐集号(父, 日)
    子齐集闸.开始全部营业日(日, "兼容开始批")

    r = 客户.get("/api/核证/子齐集", params={"键": 父})
    assert r.status_code == 200, r.text
    assert r.json()["齐集号"] == qid

    r = 客户.get(f"/api/核证/子齐集/{qid}")
    assert r.status_code == 200, r.text
    assert r.json()["齐集号"] == qid

    r = 客户.post(
        "/api/核证/子齐集/巡检",
        json={"齐集号": qid, "报告": {"父抽成功": True}, "aligned": True},
    )
    assert r.status_code == 409, r.text
    assert _正式父镜数() == 0

    r = 客户.post("/api/父镜/演练", json={"名": "子齐集缺子样例.json"})
    assert r.status_code == 200, r.text
    scene = r.json()["缺子现场"]
    assert scene["父正式有无"] is False
    assert scene["旁置有无"] is True
    assert scene["缺子列表"] == [子乙]


def test_子父并发抽取_不得父成子缺且同票():
    day = "2026-12-12"
    装载流水([_流水("c-a", 子甲, 800, day), _流水("c-b", 子乙, 200, day)], )
    results: list[dict] = []
    errors: list[BaseException] = []

    def run(batch):
        try:
            results.append(抽取.日终抽取(day, batch))
        except BaseException as e:  # 并发夹具需要收集并断言无错误
            errors.append(e)

    t1 = threading.Thread(target=run, args=("锁批甲",))
    t2 = threading.Thread(target=run, args=("锁批乙",))
    t1.start(); t2.start(); t1.join(); t2.join()

    assert not errors, errors
    assert len(results) == 2
    qid = 子齐集闸.编齐集号(父, day)
    cert = 子齐集闸.核证现场(齐集号=qid)
    assert cert["valid"] is True
    assert cert["缺子列表"] == []
    assert _正式父镜数(day) == 1
    assert _快照状态(子甲, day) is not None
    assert _快照状态(子乙, day) is not None
    assert _快照状态(子甲, day)["齐集号"] == qid
    assert _快照状态(子乙, day)["齐集号"] == qid
    official = 子户汇总镜.读取父镜(父, day)
    assert official["齐集号"] == qid
    assert official["抽取批次编号"] in {r["批次编号"] for r in results}


def test_缺子夹具可端到端演练():
    missing = 齐集演练.演练("子齐集缺子样例.json")
    scene = missing["缺子现场"]
    assert scene["父正式有无"] is False
    assert scene["旁置有无"] is True
    assert scene["缺子列表"] == [子乙]
    assert scene["valid"] is False


def test_晋升夹具可端到端演练():
    promo = 齐集演练.演练("子齐集晋升样例.json")
    assert promo["缺子现场"]["父正式有无"] is False
    assert promo["缺子现场"]["旁置有无"] is True
    assert promo["晋升现场"]["父正式有无"] is True
    assert promo["晋升现场"]["valid"] is True
    final = promo["最终核证"]
    assert final["valid"] is True
    assert final["父正式"]["余额"] == 1000


def test_并发夹具可经齐集演练入口执行并核证同票():
    r = 客户.post("/api/齐集/演练", json={"名": "子齐集并发样例.json"})
    assert r.status_code == 200, r.text
    body = r.json()
    concurrent = next(step["并发抽取"] for step in body["步骤"] if "并发抽取" in step)
    assert concurrent["错误"] == []
    assert concurrent["父子同批"] is True
    assert concurrent["缺子列表"] == []
    assert concurrent["齐集valid"] is True
    assert concurrent["核证valid"] is True
