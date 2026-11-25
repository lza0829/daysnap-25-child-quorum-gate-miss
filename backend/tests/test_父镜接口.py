"""父镜接口契约测试（FastAPI TestClient）。"""

import os
import tempfile
from pathlib import Path

import pytest

_临时 = tempfile.mkdtemp(prefix="daysnap-api-")
os.environ["数据目录"] = _临时
os.environ["夹具目录"] = str(Path(__file__).resolve().parent.parent.parent / "fixtures")

from fastapi.testclient import TestClient  

from app import seed  
from app.db import 连接  
from app.main import app  

客户 = TestClient(app)
父 = "户汇总"


@pytest.fixture(autouse=True)
def 干净库():
    seed.初始化库()
    conn = 连接()
    try:
        for t in ("变动流水", "抽取批次", "周期快照", "父镜", "回放批次", "差额行", "断档记录", "跳变记录", "旁置簿", "装载批次", "账户"):
            conn.execute(f"DELETE FROM {t}")
        conn.execute("UPDATE 台参 SET 值='盖写同日快照' WHERE 键='重复抽取'")
        for 键, 日, 父键 in [
            ("户子甲", "2026-11-01", 父),
            ("户子乙", "2026-11-01", 父),
            (父, "2026-11-01", ""),
        ]:
            conn.execute(
                "INSERT INTO 账户(账户键, 户名, 币种, 开户营业日, 状态, 父户键) VALUES (?,?,?,?,?,?)",
                (键, 键, "CNY", 日, "正常", 父键),
            )
        conn.commit()
    finally:
        conn.close()
    yield


def _装(流水):
    r = 客户.post("/api/装载", json={"流水": 流水})
    assert r.status_code == 200, r.text
    return r.json()


def _抽(日):
    return 客户.post("/api/抽取", json={"营业日": 日})


def test_主读与核证接口():
    日 = "2026-12-01"
    _装(
        [
            {"流水号": "x1", "账户键": "户子甲", "营业日": 日, "变动额": 1000},
            {"流水号": "x2", "账户键": "户子乙", "营业日": 日, "变动额": 2500},
        ]
    )
    assert _抽(日).status_code == 200
    r = 客户.get("/api/父镜/行", params={"账户键": 父, "营业日": 日})
    assert r.status_code == 200
    assert r.json()["余额"] == 3500
    assert len(r.json()["子集合"]) == 2

    
    conn = 连接()
    try:
        conn.execute("UPDATE 周期快照 SET 余额=9999 WHERE 账户键='户子乙' AND 营业日=?", (日,))
        conn.commit()
    finally:
        conn.close()

    
    assert 客户.get("/api/父镜/行", params={"账户键": 父, "营业日": 日}).json()["余额"] == 3500
    
    h = 客户.post("/api/父镜/核证", json={"账户键": 父, "营业日": 日}).json()
    assert h["指纹匹配"] is False and h["valid"] is False
    assert h["固化余额"] == 3500
    assert h["现场重算余额"] == 10999
    assert h["失配子"] == ["户子乙"]
    
    g = 客户.post("/api/父镜/重汇总", json={"账户键": 父, "营业日": 日}).json()
    assert g["余额"] == 10999
    assert 客户.post("/api/父镜/核证", json={"账户键": 父, "营业日": 日}).json()["valid"] is True


def test_抽取缺子返回409且不留父行():
    日 = "2026-12-02"
    _装([{"流水号": "y1", "账户键": "户子甲", "营业日": 日, "变动额": 100}])
    conn = 连接()
    try:
        conn.execute("UPDATE 账户 SET 状态='停用' WHERE 账户键='户子乙'")
        conn.commit()
    finally:
        conn.close()
    r = _抽(日)
    assert r.status_code == 409
    body = r.json()["detail"]
    assert body["缺子"] == ["户子乙"]
    assert 客户.get("/api/父镜/行", params={"账户键": 父, "营业日": 日}).status_code == 404


def test_父键流水经接口旁置():
    日 = "2026-12-03"
    r = _装([{"流水号": "z1", "账户键": 父, "营业日": 日, "变动额": 777}])
    assert r["旁置"] == 1
    assert _抽(日).status_code == 200
    assert 客户.get("/api/父镜/行", params={"账户键": 父, "营业日": 日}).json()["余额"] == 0


def test_父子配置接口与单层约束():
    r = 客户.post("/api/父镜/配置", json={"子户键": "户子甲", "父户键": "户子甲"})
    assert r.status_code == 400
    r = 客户.post("/api/父镜/配置", json={"子户键": "户子甲", "父户键": 父})
    assert r.status_code == 200
    
    r = 客户.post("/api/父镜/配置", json={"子户键": 父, "父户键": "户子乙"})
    assert r.status_code == 400


def test_三个父镜夹具可端到端演练():
    客户.post("/api/重置业务库")
    r = 客户.post("/api/父镜/演练", json={"名": "父子汇总样例.json"})
    assert r.status_code == 200, r.text
    步骤 = r.json()["步骤"]
    抽取 = next(s["抽取"] for s in 步骤 if "抽取" in s)
    assert 抽取[0]["父镜"][0]["余额"] == 20000  
    assert 抽取[0]["父镜"][0]["子户数"] == 2
    装载 = next(s["装载"] for s in 步骤 if "装载" in s)
    assert 装载["旁置"] == 1  

    r = 客户.post("/api/父镜/演练", json={"名": "篡改子镜样例.json"})
    assert r.status_code == 200, r.text
    篡 = next(s["篡改子镜"] for s in r.json()["步骤"] if "篡改子镜" in s)
    assert 篡["主读不变"] is True
    assert 篡["后指纹匹配"] is False and 篡["后valid"] is False
    assert 篡["后失配子"] == ["户子乙"]

    r = 客户.post("/api/父镜/演练", json={"名": "父子并发样例.json"})
    assert r.status_code == 200, r.text
    并 = next(s["并发抽取"] for s in r.json()["步骤"] if "并发抽取" in s)
    assert 并["错误"] == []
    assert 并["父子同批"] is True
    assert 并["父镜"]["子户数"] == 2
    assert 并["核证valid"] is True
