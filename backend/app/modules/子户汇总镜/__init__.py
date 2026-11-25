"""子户汇总镜 · 父户日终有效镜由子户当日有效镜汇总固化。

口径：**乙 · 指纹固化**（全局只贯彻这一种）

- 抽取时把父余额与每个子户快照的指纹一并写入 `父镜`，父行是求和结果。
- 父对外主读只读 `周期快照` 的父行 / `父镜` 固化行，**读时绝不 JOIN 子表**。
- 子快照被直接改库篡改后，父主读保持原值；只有显式重汇总才刷新。
- 核证接口现场重算子集合与指纹，失配即报 `指纹匹配=False / valid=False`，
  但核证本身只读，不修改任何固化行。
"""

import hashlib
import json
import uuid
from typing import Any

from app.db import 连接
from app.services.时间 import 此刻, 标准化营业日

启用 = True

来源_抽取 = "子户汇总"
来源_重汇总 = "显式重汇总"


class 缺子异常(Exception):
    """父镜所需的子户当日有效快照不齐。"""

    def __init__(self, 父户键: str, 营业日: str, 缺子: list[str]):
        self.父户键 = 父户键
        self.营业日 = 营业日
        self.缺子 = list(缺子)
        super().__init__(f"父镜未成：{父户键} {营业日} 缺子户快照 {', '.join(self.缺子)}")


class 配置异常(Exception):
    """父子配置非法。"""


def _行(r) -> dict[str, Any]:
    return dict(r)


def 子户列表(conn, 父户键: str) -> list[dict[str, Any]]:
    return [
        _行(r)
        for r in conn.execute(
            "SELECT * FROM 账户 WHERE 父户键=? ORDER BY 账户键", (父户键,)
        )
    ]


def 是父户(conn, 账户键: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM 账户 WHERE 父户键=? LIMIT 1", (账户键,)
        ).fetchone()
        is not None
    )


def 父户们(conn) -> list[dict[str, Any]]:
    """全部父户（在册且有子户）。有意不过滤状态：停用父户仍须按父镜路径处理，
    否则会被当成叶子户直接写快照，绕过子户汇总。"""
    return [
        _行(r)
        for r in conn.execute(
            "SELECT a.* FROM 账户 a WHERE "
            "EXISTS(SELECT 1 FROM 账户 c WHERE c.父户键=a.账户键) "
            "ORDER BY a.账户键"
        )
    ]


def 子指纹(账户键: str, 营业日: str, 余额: int, 抽取批次编号: str) -> str:
    raw = f"{账户键}|{营业日}|{int(余额)}|{抽取批次编号}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def 汇总指纹(子集合: list[dict[str, Any]]) -> str:
    raw = "\n".join(
        f"{x['账户键']}:{x['指纹']}"
        for x in sorted(子集合, key=lambda x: str(x["账户键"]))
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _期望子户(conn, 父户键: str, 营业日: str) -> list[dict[str, Any]]:
    """父镜口径下应参与汇总的子户：在册且已开户。

    有意不过滤 `状态`：子户停用/销户后若从期望集悄悄消失，父镜会静默缩小，
    正是「误吞子户」。停用子户须先解绑或补齐当日镜，否则父镜整批失败。
    """
    return [
        c for c in 子户列表(conn, 父户键) if str(c["开户营业日"]) <= 营业日
    ]


def 现场汇总(conn, 父户键: str, 营业日: str, 严格: bool = True) -> dict[str, Any]:
    """现场按子户当日有效快照求和。严格模式缺子即抛 `缺子异常`。

    这是核证/重汇总专用的现场计算路径；父对外主读不会调用它。
    """
    日 = 标准化营业日(营业日)
    父 = conn.execute("SELECT * FROM 账户 WHERE 账户键=?", (父户键,)).fetchone()
    if not 父:
        raise 配置异常(f"父户不存在: {父户键}")
    期望 = _期望子户(conn, 父户键, 日)
    子集合: list[dict[str, Any]] = []
    缺子: list[str] = []
    for c in 期望:
        快照 = conn.execute(
            "SELECT 快照键, 账户键, 营业日, 余额, 抽取批次编号 FROM 周期快照 "
            "WHERE 账户键=? AND 营业日=? AND 状态='有效'",
            (c["账户键"], 日),
        ).fetchone()
        if 快照 is None:
            缺子.append(str(c["账户键"]))
            continue
        子集合.append(
            {
                "账户键": str(快照["账户键"]),
                "营业日": str(快照["营业日"]),
                "快照键": str(快照["快照键"]),
                "余额": int(快照["余额"]),
                "抽取批次编号": str(快照["抽取批次编号"]),
                "指纹": 子指纹(
                    str(快照["账户键"]),
                    str(快照["营业日"]),
                    int(快照["余额"]),
                    str(快照["抽取批次编号"]),
                ),
            }
        )
    if 缺子 and 严格:
        raise 缺子异常(父户键, 日, 缺子)
    return {
        "账户键": 父户键,
        "营业日": 日,
        "余额": sum(int(x["余额"]) for x in 子集合),
        "子户数": len(子集合),
        "期望子户": len(期望),
        "子集合": 子集合,
        "汇总指纹": 汇总指纹(子集合),
        "缺子": 缺子,
    }


def _写父镜(
    conn,
    父户键: str,
    营业日: str,
    批次编号: str,
    来源: str,
    结果: dict[str, Any],
) -> bool:
    """把现场汇总结果固化成父行。返回是否新建（否则为盖写）。"""
    快照键 = f"{父户键}|{营业日}"
    齐集号 = f"齐集-{父户键}-{营业日}"
    子JSON = json.dumps(结果["子集合"], ensure_ascii=False, sort_keys=True)
    旧 = conn.execute(
        "SELECT 快照键 FROM 父镜 WHERE 账户键=? AND 营业日=?", (父户键, 营业日)
    ).fetchone()
    if 旧:
        conn.execute(
            "UPDATE 父镜 SET 余额=?, 子户数=?, 子指纹集=?, 汇总指纹=?, "
            "抽取批次编号=?, 来源=?, 状态='有效', 齐集号=?, 时刻=? "
            "WHERE 账户键=? AND 营业日=?",
            (
                int(结果["余额"]),
                int(结果["子户数"]),
                子JSON,
                结果["汇总指纹"],
                批次编号,
                来源,
                齐集号,
                此刻(),
                父户键,
                营业日,
            ),
        )
        新建 = False
    else:
        conn.execute(
            "INSERT INTO 父镜(快照键, 账户键, 营业日, 余额, 子户数, 子指纹集, "
            "汇总指纹, 抽取批次编号, 来源, 状态, 齐集号, 时刻) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                快照键,
                父户键,
                营业日,
                int(结果["余额"]),
                int(结果["子户数"]),
                子JSON,
                结果["汇总指纹"],
                批次编号,
                来源,
                "有效",
                齐集号,
                此刻(),
            ),
        )
        新建 = True

    
    旧快照 = conn.execute(
        "SELECT 快照键 FROM 周期快照 WHERE 账户键=? AND 营业日=?", (父户键, 营业日)
    ).fetchone()
    if 旧快照:
        conn.execute(
            "UPDATE 周期快照 SET 余额=?, 抽取批次编号=?, 来源=?, 状态='有效', 齐集号=? "
            "WHERE 账户键=? AND 营业日=?",
            (int(结果["余额"]), 批次编号, 来源, 齐集号, 父户键, 营业日),
        )
    else:
        conn.execute(
            "INSERT INTO 周期快照(快照键, 账户键, 营业日, 余额, 抽取批次编号, 来源, 状态, 齐集号) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (快照键, 父户键, 营业日, int(结果["余额"]), 批次编号, 来源, "有效", 齐集号),
        )
    return 新建


def 固化(conn, 父户键: str, 营业日: str, 批次编号: str, 来源: str = 来源_抽取) -> dict[str, Any]:
    """抽取批内调用：现场汇总并固化父镜。子户不齐时抛 `缺子异常`，不写任何父行。"""
    日 = 标准化营业日(营业日)
    结果 = 现场汇总(conn, 父户键, 日, 严格=True)
    结果["新建"] = _写父镜(conn, 父户键, 日, 批次编号, 来源, 结果)
    return 结果


def 旁置父键流水(conn, 父户键: str) -> int:
    """父键直接发生的流水必须旁置，不参与任何父镜汇总或回放。"""
    行们 = conn.execute(
        "SELECT * FROM 变动流水 WHERE 账户键=? AND 命运='已入账'", (父户键,)
    ).fetchall()
    for r in 行们:
        conn.execute(
            "INSERT INTO 旁置簿(原因, 账户键, 营业日, 载荷, 时刻) VALUES (?,?,?,?,?)",
            (
                "父键直接流水",
                父户键,
                str(r["营业日"]),
                json.dumps(_行(r), ensure_ascii=False),
                此刻(),
            ),
        )
        conn.execute(
            "UPDATE 变动流水 SET 命运='旁置·父键直接' WHERE 流水号=?", (r["流水号"],)
        )
    return len(行们)


def _读父镜(conn, 父户键: str, 营业日: str):
    # 对外“正式有效镜”主读：旁置/失效行不得从此口读出权威值。
    return conn.execute(
        "SELECT * FROM 父镜 WHERE 账户键=? AND 营业日=? AND 状态='有效'",
        (父户键, 营业日),
    ).fetchone()


def _解析父镜(row) -> dict[str, Any]:
    d = _行(row)
    try:
        d["子集合"] = json.loads(d.get("子指纹集") or "[]")
    except Exception:
        d["子集合"] = []
    d.pop("子指纹集", None)
    return d


def 读取父镜(父户键: str, 营业日: str) -> dict[str, Any] | None:
    """只读父对外主读行（父镜固化表），不触碰子快照。"""
    conn = 连接()
    try:
        row = _读父镜(conn, 父户键, 标准化营业日(营业日))
        return None if row is None else _解析父镜(row)
    finally:
        conn.close()


def 列父镜(营业日: str = "", 账户键: str = "", 含失效: bool = False) -> list[dict[str, Any]]:
    conn = 连接()
    try:
        sql = "SELECT * FROM 父镜 WHERE 1=1"
        args: list[Any] = []
        if not 含失效:
            sql += " AND 状态='有效'"
        if 营业日:
            sql += " AND 营业日=?"
            args.append(标准化营业日(营业日))
        if 账户键:
            sql += " AND 账户键=?"
            args.append(账户键)
        sql += " ORDER BY 营业日 DESC, 账户键 LIMIT 300"
        return [_解析父镜(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


def 核证(父户键: str, 营业日: str) -> dict[str, Any]:
    """父镜只读核证：固化余额/子指纹集 vs 现场重算。

    乙口径下，子行被篡改后 `固化` 与主读都不变，但本接口会报
    `指纹匹配=False`、`valid=False` 并给出失配子户。
    """
    日 = 标准化营业日(营业日)
    conn = 连接()
    try:
        父镜行 = _读父镜(conn, 父户键, 日)
        现场 = 现场汇总(conn, 父户键, 日, 严格=False)
        if 父镜行 is None:
            return {
                "账户键": 父户键,
                "营业日": 日,
                "找到": False,
                "固化": None,
                "固化余额": None,
                "固化指纹": None,
                "现场": 现场,
                "现场重算余额": 现场["余额"],
                "现场指纹": 现场["汇总指纹"],
                "缺子": 现场["缺子"],
                "失配子": [],
                "子集变化": False,
                "余额匹配": False,
                "指纹匹配": False,
                "valid": False,
                "原因": "父镜未固化",
            }
        固化 = _解析父镜(父镜行)
        固定集 = {str(x["账户键"]): x for x in 固化["子集合"]}
        现场集 = {str(x["账户键"]): x for x in 现场["子集合"]}
        失配子 = sorted(
            k
            for k in 固定集.keys() & 现场集.keys()
            if str(固定集[k].get("指纹")) != str(现场集[k].get("指纹"))
        )
        子集变化 = set(固定集) != set(现场集)
        缺子 = list(现场["缺子"])
        余额匹配 = int(固化["余额"]) == int(现场["余额"])
        指纹匹配 = (
            str(固化.get("汇总指纹")) == str(现场["汇总指纹"])
            and not 缺子
            and not 子集变化
            and not 失配子
        )
        valid = 指纹匹配 and 固化.get("状态") == "有效" and 余额匹配
        原因 = ""
        if 固化.get("状态") != "有效":
            原因 = "父镜已失效"
        elif 缺子:
            原因 = "子户当日快照不齐"
        elif 失配子:
            原因 = "子户快照指纹失配"
        elif 子集变化:
            原因 = "子户集合变化"
        elif not 指纹匹配:
            原因 = "汇总指纹失配"
        elif not 余额匹配:
            原因 = "父余额与现场重算不一致"
        return {
            "账户键": 父户键,
            "营业日": 日,
            "找到": True,
            "固化": 固化,
            "固化余额": int(固化["余额"]),
            "固化指纹": str(固化.get("汇总指纹") or ""),
            "现场": 现场,
            "现场重算余额": int(现场["余额"]),
            "现场指纹": 现场["汇总指纹"],
            "缺子": 缺子,
            "失配子": 失配子,
            "子集变化": 子集变化,
            "余额匹配": 余额匹配,
            "指纹匹配": 指纹匹配,
            "valid": valid,
            "原因": 原因,
        }
    finally:
        conn.close()


def 重汇总(父户键: str, 营业日: str, 批次编号: str = "") -> dict[str, Any]:
    """显式重汇总：重新按现场子快照固化父镜。子户不齐则整体失败、不改旧行。"""
    日 = 标准化营业日(营业日)
    批 = 批次编号.strip() or f"重汇总-{日}-{uuid.uuid4().hex[:8]}"
    conn = 连接()
    try:
        conn.execute("BEGIN IMMEDIATE")
        子 = 子户列表(conn, 父户键)
        if not 子:
            raise 配置异常(f"父户无子户: {父户键}")
        旧 = _读父镜(conn, 父户键, 日)
        try:
            结果 = 现场汇总(conn, 父户键, 日, 严格=True)
        except 缺子异常:
            conn.rollback()
            raise
        结果["新建"] = _写父镜(conn, 父户键, 日, 批, 来源_重汇总, 结果)
        # 显式重汇总也是显式晋升动作：同步齐集核证和旁置状态。
        from app.modules import 子齐集闸 as _齐集

        q = _齐集.开始齐集(conn, 父户键, 日, 批)
        conn.execute(
            "UPDATE 旁置父镜 SET 状态='已晋升', 晋升时刻=?, 正式批次编号=?, 更新时刻=? "
            "WHERE 账户键=? AND 营业日=? AND 状态<>'已晋升'",
            (此刻(), 批, 此刻(), 父户键, 日),
        )
        conn.execute(
            "UPDATE 旁置簿 SET 原因='齐集旁置已显式晋升' "
            "WHERE 账户键=? AND 营业日=? AND 旁置号<>''",
            (父户键, 日),
        )
        _齐集.标记正式已写(conn, 父户键, 日, 批, str(q["齐集号"]))
        conn.execute(
            "INSERT INTO 抽取批次(编号, 营业日, 时刻, 报告) VALUES (?,?,?,?)",
            (
                批,
                日,
                此刻(),
                json.dumps(
                    {
                        "动作": "父镜重汇总",
                        "账户键": 父户键,
                        "余额": 结果["余额"],
                        "子户数": 结果["子户数"],
                        "汇总指纹": 结果["汇总指纹"],
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        conn.commit()
        return {
            "账户键": 父户键,
            "营业日": 日,
            "批次编号": 批,
            "余额": 结果["余额"],
            "子户数": 结果["子户数"],
            "子集合": 结果["子集合"],
            "汇总指纹": 结果["汇总指纹"],
            "前余额": None if 旧 is None else int(旧["余额"]),
            "前指纹": None if 旧 is None else str(旧["汇总指纹"]),
            "新建": 结果["新建"],
        }
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def _校验配置(conn, 子户键: str, 父户键: str) -> tuple[dict, dict]:
    子 = conn.execute("SELECT * FROM 账户 WHERE 账户键=?", (子户键,)).fetchone()
    父 = conn.execute("SELECT * FROM 账户 WHERE 账户键=?", (父户键,)).fetchone()
    if not 子:
        raise 配置异常(f"子户不存在: {子户键}")
    if not 父:
        raise 配置异常(f"父户不存在: {父户键}")
    if 子户键 == 父户键:
        raise 配置异常("子户不得同时作为自己的父户")
    if str(父["父户键"] or ""):
        raise 配置异常(f"父户本身已是子户，仅支持单层汇总: {父户键}")
    if 是父户(conn, 子户键):
        raise 配置异常(f"已有子户的账户不得再作为子户: {子户键}")
    return _行(子), _行(父)


def _设父户(conn, 子户键: str, 父户键: str) -> int:
    子, 父 = _校验配置(conn, 子户键, 父户键)
    conn.execute("UPDATE 账户 SET 父户键=? WHERE 账户键=?", (父户键, 子户键))
    return 旁置父键流水(conn, 父户键)


def 配置父户(子户键: str, 父户键: str) -> dict[str, Any]:
    conn = 连接()
    try:
        conn.execute("BEGIN IMMEDIATE")
        旁置 = _设父户(conn, 子户键, 父户键)
        conn.commit()
        return {
            "子户键": 子户键,
            "父户键": 父户键,
            "父键流水旁置": 旁置,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def 解绑父户(子户键: str) -> dict[str, Any]:
    conn = 连接()
    try:
        conn.execute("BEGIN IMMEDIATE")
        子 = conn.execute("SELECT * FROM 账户 WHERE 账户键=?", (子户键,)).fetchone()
        if not 子:
            raise 配置异常(f"子户不存在: {子户键}")
        原父 = str(子["父户键"] or "")
        conn.execute("UPDATE 账户 SET 父户键='' WHERE 账户键=?", (子户键,))
        conn.commit()
        return {"子户键": 子户键, "原父户键": 原父, "已解绑": bool(原父)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def 说明():
    return "子户汇总镜（乙·指纹固化）：父镜由子户当日有效镜汇总并固化指纹"
